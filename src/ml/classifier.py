import os
import re
import joblib
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, f1_score
import pandas as pd


MODEL_VERSION = 2
SHORT_KEYWORD_MAX_LEN = 3


def augment_text(description: str, amount: float = None) -> str:
    """Build model input from description and optional amount sign."""
    text = (description or '').lower()
    if amount is not None:
        if amount > 0:
            sign = 'income'
        elif amount < 0:
            sign = 'expense'
        else:
            sign = 'zero'
        text = f"{text} | amt:{sign}"
    return text


class CategoryClassifier:
    """ML classifier for transaction categorization based on description."""

    def __init__(self, model_path: str = None, load_existing: bool = True):
        self.model_path = model_path or "data/db/category_model.pkl"
        self.pipeline = None
        self.categories = []
        self.last_trained_at = None
        self.manual_label_count_at_train = 0
        if load_existing:
            self._load_or_initialize()
        else:
            self._init_pipeline()

    def _load_or_initialize(self):
        if os.path.exists(self.model_path):
            if not self.load():
                self._init_pipeline()
        else:
            self._init_pipeline()

    def _init_pipeline(self):
        self.pipeline = Pipeline([
            ('tfidf', FeatureUnion([
                ('word', TfidfVectorizer(
                    max_features=2000,
                    ngram_range=(1, 3),
                    lowercase=True,
                    strip_accents='unicode',
                    min_df=1,
                    max_df=0.95,
                    analyzer='word',
                )),
                ('char', TfidfVectorizer(
                    max_features=1000,
                    ngram_range=(3, 5),
                    lowercase=True,
                    strip_accents='unicode',
                    min_df=1,
                    max_df=0.95,
                    analyzer='char_wb',
                )),
            ])),
            ('clf', LogisticRegression(
                class_weight='balanced',
                max_iter=1000,
                random_state=42,
            )),
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
                    X.append(augment_text(kw))
                    y.append(category)
            else:
                X.append(augment_text(category))
                y.append(category)

        return X, y

    def _create_training_data_from_database(self, db_path: str) -> tuple:
        """Create training data from existing categorized transactions."""
        from sqlalchemy import create_engine, text

        engine = create_engine(f'sqlite:///{db_path}')

        df = pd.read_sql(text("""
            SELECT description, amount, c.name as category_name
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE c.name != 'Other'
        """), engine.connect())

        X = [augment_text(desc, amt) for desc, amt in zip(df['description'], df['amount'])]
        y = df['category_name'].tolist()

        return X, y

    def _create_training_data_from_csv(self, csv_path: str) -> tuple:
        """Create training data from manually labeled CSV file."""
        df = pd.read_csv(csv_path)

        amounts = df['amount'] if 'amount' in df.columns else [None] * len(df)
        X = [
            augment_text(concept, amt if pd.notna(amt) else None)
            for concept, amt in zip(df['concept'].fillna(''), amounts)
        ]
        y = df['category'].tolist()

        return X, y

    def _merge_training_data(self, sources: list) -> tuple:
        """
        Merge training samples from multiple sources.
        sources: list of (X, y, priority) where higher priority wins conflicts.
        """
        merged = {}

        for X, y, priority in sources:
            for text, category in zip(X, y):
                if category == 'Other':
                    continue
                key = (text, category)
                if key not in merged or priority > merged[key][0]:
                    merged[key] = (priority, text, category)

        if not merged:
            return [], []

        items = sorted(merged.values(), key=lambda item: item[1])
        return [item[1] for item in items], [item[2] for item in items]

    def train_combined(
        self,
        config: dict,
        db_path: str = None,
        csv_path: str = None,
        save: bool = True,
        manual_label_count: int = 0,
    ) -> bool:
        """Train model merging config keywords, DB labels, and optional CSV."""
        sources = []
        cfg_count = csv_count = db_count = 0

        X_cfg, y_cfg = self._create_training_data_from_config(config)
        cfg_count = len(X_cfg)
        if X_cfg:
            sources.append((X_cfg, y_cfg, 0))

        if csv_path and os.path.exists(csv_path):
            X_csv, y_csv = self._create_training_data_from_csv(csv_path)
            csv_count = len(X_csv)
            if X_csv:
                sources.append((X_csv, y_csv, 1))

        if db_path and os.path.exists(db_path):
            X_db, y_db = self._create_training_data_from_database(db_path)
            db_count = len(X_db)
            if X_db:
                sources.append((X_db, y_db, 2))

        X, y = self._merge_training_data(sources)

        if not X:
            print("No training data available")
            return False

        self.categories = sorted(set(y))
        self.pipeline.fit(X, y)
        self.manual_label_count_at_train = manual_label_count
        self.last_trained_at = pd.Timestamp.now().isoformat()

        print(
            f"Trained on {len(X)} combined samples "
            f"(config: {cfg_count}, csv: {csv_count}, db: {db_count})"
        )

        if save:
            self.save()

        return True

    def train_from_config(self, config: dict, save: bool = True):
        """Train model using category keywords from config."""
        return self.train_combined(config, save=save)

    def train_from_database(self, db_path: str, save: bool = True):
        """Retrain model using existing categorized transactions."""
        X, y = self._create_training_data_from_database(db_path)

        if len(X) < 10:
            print("Not enough training data in database")
            return False

        self.categories = sorted(set(y))
        self.pipeline.fit(X, y)

        if save:
            self.save()

        print(f"Trained on {len(X)} samples from database")
        return True

    def train_from_csv(self, csv_path: str, save: bool = True):
        """Train model from manually labeled CSV file."""
        X, y = self._create_training_data_from_csv(csv_path)

        if not X:
            print("No training data in CSV")
            return False

        self.categories = sorted(set(y))
        self.pipeline.fit(X, y)

        if save:
            self.save()

        print(f"Trained on {len(X)} labeled samples from CSV")
        return True

    def needs_retrain(self, manual_label_count: int) -> bool:
        """Return True if manual labels were added since last training."""
        if not self.is_trained():
            return True
        return manual_label_count > self.manual_label_count_at_train

    def _prepare_inputs(self, descriptions: list, amounts: list = None) -> list:
        if amounts is None:
            return [augment_text(desc) for desc in descriptions]
        return [
            augment_text(desc, amt)
            for desc, amt in zip(descriptions, amounts)
        ]

    def predict(self, descriptions: list, amounts: list = None) -> list:
        """Predict categories for a list of descriptions."""
        if self.pipeline is None:
            raise ValueError("Model not trained")

        inputs = self._prepare_inputs(descriptions, amounts)
        predictions = self.pipeline.predict(inputs)
        return predictions.tolist()

    def predict_proba(self, descriptions: list, amounts: list = None) -> list:
        """Predict category probabilities for descriptions."""
        if self.pipeline is None:
            raise ValueError("Model not trained")

        inputs = self._prepare_inputs(descriptions, amounts)
        probas = self.pipeline.predict_proba(inputs)
        classes = self.pipeline.named_steps['clf'].classes_

        results = []
        for proba in probas:
            cat_probas = list(zip(classes, proba))
            cat_probas.sort(key=lambda x: x[1], reverse=True)
            results.append(cat_probas)

        return results

    def _predict_ml_details(self, descriptions: list, amounts: list = None) -> list:
        probas = self.predict_proba(descriptions, amounts)
        ml_predictions = self.predict(descriptions, amounts)

        details = []
        for i, prob_list in enumerate(probas):
            details.append({
                'category': ml_predictions[i],
                'confidence': float(prob_list[0][1]),
                'source': 'ml',
            })
        return details

    def predict_with_fallback(
        self,
        descriptions: list,
        config: dict,
        threshold: float = 0.5,
        amounts: list = None,
    ) -> list:
        """Predict with keyword fallback for low-confidence ML predictions."""
        keyword_clf = KeywordClassifier(config)
        ml_details = self._predict_ml_details(descriptions, amounts)

        final = []
        for i, ml_detail in enumerate(ml_details):
            if ml_detail['confidence'] >= threshold:
                final.append(ml_detail['category'])
            else:
                keyword_preds = keyword_clf.predict([descriptions[i]])
                final.append(keyword_preds[0])
        return final

    def predict_hybrid(
        self,
        descriptions: list,
        config: dict,
        amounts: list = None,
    ) -> list:
        """Keyword-first, ML fallback for unmapped categories."""
        return [d['category'] for d in self.predict_hybrid_details(descriptions, config, amounts)]

    def predict_hybrid_details(
        self,
        descriptions: list,
        config: dict,
        amounts: list = None,
    ) -> list:
        """Keyword-first strategy with per-prediction metadata."""
        keyword_clf = KeywordClassifier(config)
        keyword_preds = keyword_clf.predict(descriptions)
        ml_details = self._predict_ml_details(descriptions, amounts)

        details = []
        for kw_pred, ml_detail in zip(keyword_preds, ml_details):
            if kw_pred == 'Other':
                details.append(ml_detail)
            else:
                details.append({
                    'category': kw_pred,
                    'confidence': 1.0,
                    'source': 'keyword',
                })
        return details

    def predict_with_fallback_details(
        self,
        descriptions: list,
        config: dict,
        threshold: float = 0.5,
        amounts: list = None,
    ) -> list:
        """ML-first strategy with per-prediction metadata."""
        keyword_clf = KeywordClassifier(config)
        ml_details = self._predict_ml_details(descriptions, amounts)

        details = []
        for i, ml_detail in enumerate(ml_details):
            if ml_detail['confidence'] >= threshold:
                details.append(ml_detail)
            else:
                keyword_preds = keyword_clf.predict([descriptions[i]])
                kw_cat = keyword_preds[0]
                details.append({
                    'category': kw_cat,
                    'confidence': 1.0 if kw_cat != 'Other' else ml_detail['confidence'],
                    'source': 'keyword',
                })
        return details

    def predict_with_strategy(
        self,
        descriptions: list,
        config: dict,
        strategy: str = 'hybrid',
        threshold: float = 0.5,
        amounts: list = None,
    ) -> list:
        if strategy == 'ml_fallback':
            return self.predict_with_fallback(descriptions, config, threshold, amounts)
        return self.predict_hybrid(descriptions, config, amounts)

    def predict_with_strategy_details(
        self,
        descriptions: list,
        config: dict,
        strategy: str = 'hybrid',
        threshold: float = 0.5,
        amounts: list = None,
    ) -> list:
        if strategy == 'ml_fallback':
            return self.predict_with_fallback_details(descriptions, config, threshold, amounts)
        return self.predict_hybrid_details(descriptions, config, amounts)

    def evaluate(
        self,
        config: dict,
        db_path: str = None,
        csv_path: str = None,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> dict:
        """Evaluate model and inference strategies on holdout data."""
        sources = []

        if db_path and os.path.exists(db_path):
            X_db, y_db = self._create_training_data_from_database(db_path)
            if X_db:
                sources.append((X_db, y_db, 2))

        if csv_path and os.path.exists(csv_path):
            X_csv, y_csv = self._create_training_data_from_csv(csv_path)
            if X_csv:
                sources.append((X_csv, y_csv, 1))

        X, y = self._merge_training_data(sources)

        if len(X) < 10:
            X_cfg, y_cfg = self._create_training_data_from_config(config)
            X, y = self._merge_training_data([(X_cfg, y_cfg, 0)] + sources)

        if len(X) < 5:
            return {'error': 'Not enough labeled data for evaluation (need at least 5 samples)'}

        stratify = y if len(set(y)) > 1 and min(pd.Series(y).value_counts()) >= 2 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=stratify,
        )

        eval_classifier = CategoryClassifier(load_existing=False)
        eval_classifier.pipeline.fit(X_train, y_train)
        eval_classifier.categories = sorted(set(y_train))

        raw_descriptions = [text.split(' | amt:')[0] for text in X_test]
        raw_amounts = []
        for text in X_test:
            if ' | amt:' in text:
                sign = text.rsplit(' | amt:', 1)[1]
                raw_amounts.append(1.0 if sign == 'income' else -1.0 if sign == 'expense' else 0.0)
            else:
                raw_amounts.append(None)

        strategies = {
            'ml_only': lambda: eval_classifier.predict(raw_descriptions, raw_amounts),
            'hybrid': lambda: eval_classifier.predict_hybrid(raw_descriptions, config, raw_amounts),
            'ml_fallback': lambda: eval_classifier.predict_with_fallback(
                raw_descriptions, config, 0.5, raw_amounts,
            ),
        }

        results = {
            'samples': len(X),
            'train_size': len(X_train),
            'test_size': len(X_test),
            'strategies': {},
        }

        best_strategy = None
        best_f1 = -1.0

        for name, predict_fn in strategies.items():
            y_pred = predict_fn()
            macro_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
            report = classification_report(y_test, y_pred, zero_division=0)
            results['strategies'][name] = {
                'macro_f1': macro_f1,
                'report': report,
            }
            if macro_f1 > best_f1:
                best_f1 = macro_f1
                best_strategy = name

        results['best_strategy'] = best_strategy
        results['best_macro_f1'] = best_f1
        return results

    def save(self):
        """Save the model to disk."""
        Path(self.model_path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            'pipeline': self.pipeline,
            'categories': self.categories,
            'last_trained_at': self.last_trained_at,
            'manual_label_count_at_train': self.manual_label_count_at_train,
            'model_version': MODEL_VERSION,
        }, self.model_path)
        print(f"Model saved to {self.model_path}")

    def load(self) -> bool:
        """Load the model from disk. Returns False if the artifact is outdated."""
        data = joblib.load(self.model_path)
        if data.get('model_version') != MODEL_VERSION:
            print(f"Model at {self.model_path} is outdated; will retrain")
            return False
        self.pipeline = data['pipeline']
        self.categories = data.get('categories', [])
        self.last_trained_at = data.get('last_trained_at')
        self.manual_label_count_at_train = data.get('manual_label_count_at_train', 0)
        print(f"Model loaded from {self.model_path}")
        return True

    def is_trained(self) -> bool:
        """Check if model is trained."""
        if self.pipeline is None:
            return False
        clf = self.pipeline.named_steps.get('clf')
        if clf is not None and hasattr(clf, 'classes_') and len(clf.classes_) > 0:
            return True
        return len(self.categories) > 0


class KeywordClassifier:
    """Fallback keyword-based classifier."""

    def __init__(self, config: dict):
        self.categories = {}
        self.priority_keywords = [
            kw.lower() for kw in config.get('priority_keywords', [])
        ]

        for cat in config.get('categories', []):
            name = cat['name']
            keywords = [kw.lower() for kw in cat.get('keywords', [])]
            self.categories[name] = keywords

    @staticmethod
    def _keyword_matches(keyword: str, text: str) -> bool:
        if len(keyword) <= SHORT_KEYWORD_MAX_LEN:
            pattern = r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])'
            return re.search(pattern, text) is not None
        return keyword in text

    def predict(self, descriptions: list) -> list:
        """Predict category based on keyword matching."""
        predictions = []

        for desc in descriptions:
            desc_lower = desc.lower()
            best_match = 'Other'
            best_score = 0

            priority_match = None
            for priority_kw in self.priority_keywords:
                if self._keyword_matches(priority_kw, desc_lower):
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
                score = sum(
                    len(kw) for kw in keywords
                    if self._keyword_matches(kw, desc_lower)
                )
                if score > best_score:
                    best_score = score
                    best_match = cat_name

            predictions.append(best_match)

        return predictions
