import os
import yaml
from datetime import datetime
from sqlalchemy import create_engine, text
import pandas as pd


class NormalizedDatabase:
    """Manages the normalized database schema."""

    PREDICTION_COLUMNS = [
        ('predicted_category', 'TEXT'),
        ('prediction_confidence', 'REAL'),
        ('prediction_source', 'TEXT'),
    ]

    _TRANSACTION_SELECT = """
        SELECT
            t.id,
            t.date,
            t.description,
            t.amount,
            t.category_id,
            COALESCE(t.category_name, c.name) AS category_name,
            t.source,
            t.predicted_category,
            t.prediction_confidence,
            t.prediction_source,
            t.created_at
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}')
        self._ensure_tables()

    def _ensure_tables(self):
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    keywords TEXT
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category_id INTEGER,
                    category_name TEXT,
                    source TEXT,
                    predicted_category TEXT,
                    prediction_confidence REAL,
                    prediction_source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories(id)
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS monthly_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    year_month TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    transaction_count INTEGER DEFAULT 0,
                    FOREIGN KEY (category_id) REFERENCES categories(id),
                    UNIQUE(category_id, year_month)
                )
            """))

            conn.commit()

        self._migrate_prediction_columns()

    def _migrate_prediction_columns(self):
        existing = pd.read_sql("PRAGMA table_info(transactions)", self.engine)
        existing_cols = set(existing['name'].tolist())

        with self.engine.connect() as conn:
            for col_name, col_type in self.PREDICTION_COLUMNS:
                if col_name not in existing_cols:
                    conn.execute(text(
                        f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type}"
                    ))
            conn.commit()

    def load_categories_from_config(self, config: dict):
        """Load categories from config dictionary."""
        with self.engine.connect() as conn:
            for cat in config.get('categories', []):
                keywords = ','.join(cat.get('keywords', []))
                conn.execute(text("""
                    INSERT OR IGNORE INTO categories (name, keywords)
                    VALUES (:name, :keywords)
                """), {"name": cat['name'], "keywords": keywords})
            conn.commit()

    def get_categories(self) -> pd.DataFrame:
        """Get all categories."""
        return pd.read_sql("SELECT * FROM categories", self.engine)

    def get_category_id(self, category_name: str) -> int:
        """Get category ID by name."""
        with self.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT id FROM categories WHERE name = :name"
            ), {"name": category_name}).fetchone()
            return result[0] if result else None

    def get_category_names(self) -> list:
        """Get sorted category names."""
        df = self.get_categories()
        return sorted(df['name'].tolist())

    def insert_transaction(self, date: str, description: str, amount: float, category_id: int = None, category_name: str = None, source: str = None):
        """Insert a normalized transaction."""
        with self.engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO transactions (date, description, amount, category_id, category_name, source)
                VALUES (:date, :desc, :amount, :cat_id, :cat_name, :source)
            """), {
                "date": date,
                "desc": description,
                "amount": amount,
                "cat_id": category_id,
                "cat_name": category_name,
                "source": source
            })
            conn.commit()

    def bulk_insert_transactions(self, transactions: list):
        """Bulk insert transactions."""
        if not transactions:
            return

        df = pd.DataFrame(transactions)
        df.to_sql('transactions', self.engine, if_exists='append', index=False)

    def update_transaction_category(
        self,
        transaction_id: int,
        category_id: int,
        category_name: str = None,
        predicted_category: str = None,
        prediction_confidence: float = None,
        prediction_source: str = None,
    ):
        """Update the category of a transaction."""
        if category_name is None:
            with self.engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT name FROM categories WHERE id = :cat_id"
                ), {"cat_id": category_id}).fetchone()
                category_name = result[0] if result else None

        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE transactions
                SET category_id = :cat_id,
                    category_name = :cat_name,
                    predicted_category = COALESCE(:predicted_category, predicted_category),
                    prediction_confidence = COALESCE(:prediction_confidence, prediction_confidence),
                    prediction_source = COALESCE(:prediction_source, prediction_source)
                WHERE id = :id
            """), {
                "cat_id": category_id,
                "cat_name": category_name,
                "predicted_category": predicted_category,
                "prediction_confidence": prediction_confidence,
                "prediction_source": prediction_source,
                "id": transaction_id,
            })
            conn.commit()

    def set_manual_category(self, transaction_id: int, category_id: int, category_name: str):
        """Set category from manual correction in the dashboard."""
        self.update_transaction_category(
            transaction_id,
            category_id,
            category_name=category_name,
            predicted_category=category_name,
            prediction_confidence=1.0,
            prediction_source='manual',
        )

    def get_manual_label_count(self) -> int:
        """Count transactions labeled manually via the dashboard."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM transactions WHERE prediction_source = 'manual'
            """)).fetchone()
            return result[0] if result else 0

    def update_monthly_summary(self):
        """Recalculate monthly summaries from transactions."""
        with self.engine.connect() as conn:
            conn.execute(text("DELETE FROM monthly_summary"))
            conn.commit()

        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    category_id,
                    strftime('%Y-%m', date) as year_month,
                    SUM(amount) as total_amount,
                    COUNT(*) as transaction_count
                FROM transactions
                WHERE category_id IS NOT NULL
                GROUP BY category_id, year_month
            """))

            summaries = result.fetchall()
            for row in summaries:
                conn.execute(text("""
                    INSERT INTO monthly_summary (category_id, year_month, total_amount, transaction_count)
                    VALUES (:cat_id, :ym, :total, :count)
                """), {"cat_id": row[0], "ym": row[1], "total": row[2], "count": row[3]})
            conn.commit()

    def get_transactions(self, category_id: int = None, year_month: str = None) -> pd.DataFrame:
        """Get transactions with optional filters."""
        query = self._TRANSACTION_SELECT
        params = {}

        if category_id or year_month:
            conditions = []
            if category_id:
                conditions.append("t.category_id = :cat_id")
                params["cat_id"] = category_id
            if year_month:
                conditions.append("strftime('%Y-%m', t.date) = :ym")
                params["ym"] = year_month
            query += " WHERE " + " AND ".join(conditions)

        return pd.read_sql(text(query), self.engine, params=params)

    def get_monthly_summary(self, year_month: str = None) -> pd.DataFrame:
        """Get monthly summary."""
        query = """
            SELECT ms.*, c.name as category_name
            FROM monthly_summary ms
            JOIN categories c ON ms.category_id = c.id
        """
        if year_month:
            query += " WHERE ms.year_month = :ym"
            return pd.read_sql(text(query), self.engine, params={"ym": year_month})
        return pd.read_sql(text(query), self.engine)

    def get_unclassified_transactions(self) -> pd.DataFrame:
        """Get transactions without category."""
        return pd.read_sql(text(f"""
            {self._TRANSACTION_SELECT}
            WHERE t.category_id IS NULL
        """), self.engine)

    def get_low_confidence_transactions(self, threshold: float = 0.5) -> pd.DataFrame:
        """Get categorized transactions with low prediction confidence."""
        return pd.read_sql(text(f"""
            {self._TRANSACTION_SELECT}
            WHERE t.category_id IS NOT NULL
              AND t.prediction_source != 'manual'
              AND (t.prediction_confidence IS NULL OR t.prediction_confidence < :threshold)
            ORDER BY COALESCE(t.prediction_confidence, -1) ASC, t.date DESC
        """), self.engine, params={"threshold": threshold})

    def get_review_transactions(self, threshold: float = 0.5) -> pd.DataFrame:
        """Get unclassified and low-confidence transactions for review."""
        return pd.read_sql(text(f"""
            {self._TRANSACTION_SELECT}
            WHERE t.category_id IS NULL
               OR (t.prediction_source != 'manual'
                   AND (t.prediction_confidence IS NULL OR t.prediction_confidence < :threshold))
            ORDER BY
                CASE WHEN t.category_id IS NULL THEN 0 ELSE 1 END,
                COALESCE(t.prediction_confidence, -1) ASC,
                t.date DESC
        """), self.engine, params={"threshold": threshold})


class DataNormalizer:
    """Normalizes raw data from ingestion database."""

    def __init__(self, source_db_path: str, target_db_path: str):
        self.source_engine = create_engine(f'sqlite:///{source_db_path}')
        self.target_db = NormalizedDatabase(target_db_path)

    def run(self, categories_config: dict):
        """Run the normalization pipeline."""
        self.target_db.load_categories_from_config(categories_config)

        with self.source_engine.connect() as conn:
            df = pd.read_sql(text("SELECT * FROM raw_transactions"), conn)

        transactions = []
        for _, row in df.iterrows():
            transactions.append({
                "date": row['operation_date'],
                "description": row['description'],
                "amount": row['amount'],
                "source": row['source_file']
            })

        self.target_db.bulk_insert_transactions(transactions)
        print(f"Normalized {len(transactions)} transactions")

    def update_categories(
        self,
        ml_classifier,
        strategy: str = 'hybrid',
        fallback_threshold: float = 0.5,
        recategorize_low_confidence: bool = False,
    ):
        """Update transaction categories using ML classifier."""
        from pathlib import Path

        config_path = Path(__file__).parent.parent.parent / "config" / "categories.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        strategy = config.get('inference_strategy', strategy)

        if recategorize_low_confidence:
            df = self.target_db.get_low_confidence_transactions(fallback_threshold)
        else:
            df = self.target_db.get_unclassified_transactions()

        if df.empty:
            print("No transactions to categorize")
            return

        descriptions = df['description'].tolist()
        amounts = df['amount'].tolist()

        if hasattr(ml_classifier, 'predict_with_strategy_details'):
            details = ml_classifier.predict_with_strategy_details(
                descriptions, config, strategy=strategy,
                threshold=fallback_threshold, amounts=amounts,
            )
        elif hasattr(ml_classifier, 'predict_with_fallback'):
            categories = ml_classifier.predict_with_fallback(
                descriptions, config, fallback_threshold, amounts,
            )
            details = [
                {'category': cat, 'confidence': None, 'source': 'ml'}
                for cat in categories
            ]
        else:
            categories = ml_classifier.predict(descriptions, amounts)
            details = [
                {'category': cat, 'confidence': None, 'source': 'keyword'}
                for cat in categories
            ]

        for idx, (_, row) in enumerate(df.iterrows()):
            detail = details[idx]
            cat_id = self.target_db.get_category_id(detail['category'])
            if cat_id:
                self.target_db.update_transaction_category(
                    row['id'],
                    cat_id,
                    detail['category'],
                    predicted_category=detail['category'],
                    prediction_confidence=detail.get('confidence'),
                    prediction_source=detail.get('source'),
                )

        print(f"Categorized {len(df)} transactions")
        self.target_db.update_monthly_summary()
