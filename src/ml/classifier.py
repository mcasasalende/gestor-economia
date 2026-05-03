import os
import re
import joblib
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import pandas as pd


class CategoryClassifier:
    """ML classifier for transaction categorization based on description."""

    def __init__(self, model_path: str = None):
        self.model_path = model_path or "data/db/category_model.pkl"
        self.pipeline = None
        self.categories = []
        self._load_or_initialize()

    def _load_or_initialize(self):
        if os.path.exists(self.model_path):
            self.load()
        else:
            self._init_pipeline()

    def _init_pipeline(self):
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(
                max_features=1000,
                ngram_range=(1, 2),
                lowercase=True,
                strip_accents='unicode'
            )),
            ('clf', LogisticRegression(
                max_iter=1000,
                class_weight='balanced',
                random_state=42,
                multi_class='multinomial'
            ))
        ])

    def _create_training_data_from_config(self, config: dict) -> tuple:
        """Create training data from category keywords in config."""
        X = []
        y = []
        
        for cat in config.get('categories', []):
            category = cat['name']
            keywords = cat.get('keywords', [])
            
            if category == 'Other':
                continue
                
            if keywords:
                for kw in keywords:
                    X.append(kw.lower())
                    y.append(category)
            else:
                X.append(category.lower())
                y.append(category)
        
        return X, y

    def _create_training_data_from_database(self, db_path: str) -> tuple:
        """Create training data from existing categorized transactions."""
        from sqlalchemy import create_engine, text
        import pandas as pd
        
        engine = create_engine(f'sqlite:///{db_path}')
        
        df = pd.read_sql(text("""
            SELECT description, c.name as category_name
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE c.name != 'Other'
        """), engine.connect())
        
        X = df['description'].str.lower().tolist()
        y = df['category_name'].tolist()
        
        return X, y

    def train_from_config(self, config: dict, save: bool = True):
        """Train model using category keywords from config."""
        X, y = self._create_training_data_from_config(config)
        
        if not X:
            print("No training data from config")
            return
        
        self.categories = list(set(y))
        
        self.pipeline.fit(X, y)
        
        if save:
            self.save()
        
        print(f"Trained on {len(X)} samples from config")

    def train_from_database(self, db_path: str, save: bool = True):
        """Retrain model using existing categorized transactions."""
        X, y = self._create_training_data_from_database(db_path)
        
        if len(X) < 10:
            print("Not enough training data in database")
            return
        
        self.categories = list(set(y))
        
        self.pipeline.fit(X, y)
        
        if save:
            self.save()
        
        print(f"Trained on {len(X)} samples from database")

    def predict(self, descriptions: list) -> list:
        """Predict categories for a list of descriptions."""
        if self.pipeline is None:
            raise ValueError("Model not trained")
        
        predictions = self.pipeline.predict(descriptions)
        return predictions.tolist()

    def predict_with_fallback(self, descriptions: list, config: dict, threshold: float = 0.5) -> list:
        """Predict with keyword fallback for low-confidence ML predictions."""
        keyword_clf = KeywordClassifier(config)
        
        probas = self.predict_proba(descriptions)
        ml_predictions = self.predict(descriptions)
        
        final = []
        for i, prob_list in enumerate(probas):
            top_proba = prob_list[0][1]
            if top_proba >= threshold:
                final.append(ml_predictions[i])
            else:
                keyword_preds = keyword_clf.predict([descriptions[i]])
                final.append(keyword_preds[0])
        
        return final

    def predict_proba(self, descriptions: list) -> list:
        """Predict category probabilities for descriptions."""
        if self.pipeline is None:
            raise ValueError("Model not trained")
        
        probas = self.pipeline.predict_proba(descriptions)
        
        results = []
        for i, proba in enumerate(probas):
            cat_probas = list(zip(self.pipeline.classes_, proba))
            cat_probas.sort(key=lambda x: x[1], reverse=True)
            results.append(cat_probas)
        
        return results

    def save(self):
        """Save the model to disk."""
        Path(self.model_path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            'pipeline': self.pipeline,
            'categories': self.categories
        }, self.model_path)
        print(f"Model saved to {self.model_path}")

    def load(self):
        """Load the model from disk."""
        data = joblib.load(self.model_path)
        self.pipeline = data['pipeline']
        self.categories = data['categories']
        print(f"Model loaded from {self.model_path}")

    def is_trained(self) -> bool:
        """Check if model is trained."""
        return self.pipeline is not None and len(self.categories) > 0


class KeywordClassifier:
    """Fallback keyword-based classifier."""

    PRIORITY_KEYWORDS = ['alquiler', 'rent', 'booking', 'hotel', 'airbnb', 'splintersmma', 'splinters', 'gym', 'ahorro', 'saving', 'salary', 'nomina']

    def __init__(self, config: dict):
        self.categories = {}
        
        for cat in config.get('categories', []):
            name = cat['name']
            keywords = [kw.lower() for kw in cat.get('keywords', [])]
            self.categories[name] = keywords

    def predict(self, descriptions: list) -> list:
        """Predict category based on keyword matching."""
        predictions = []
        
        for desc in descriptions:
            desc_lower = desc.lower()
            best_match = 'Other'
            best_score = 0
            
            priority_match = None
            for priority_kw in self.PRIORITY_KEYWORDS:
                if priority_kw in desc_lower:
                    priority_match = priority_kw
                    break
            
            if priority_match:
                for cat_name, keywords in self.categories.items():
                    if priority_match in keywords:
                        predictions.append(cat_name)
                        break
                else:
                    predictions.append('Other')
                continue
            
            for cat_name, keywords in self.categories.items():
                score = sum(len(kw) for kw in keywords if kw in desc_lower)
                if score > best_score:
                    best_score = score
                    best_match = cat_name
            
            predictions.append(best_match)
        
        return predictions