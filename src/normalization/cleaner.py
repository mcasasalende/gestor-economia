import os
from datetime import datetime
from sqlalchemy import create_engine, text
import pandas as pd


class NormalizedDatabase:
    """Manages the normalized database schema."""

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

    def update_transaction_category(self, transaction_id: int, category_id: int, category_name: str = None):
        """Update the category of a transaction."""
        if category_name is None:
            with self.engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT name FROM categories WHERE id = :cat_id"
                ), {"cat_id": category_id}).fetchone()
                category_name = result[0] if result else None
        
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE transactions SET category_id = :cat_id, category_name = :cat_name WHERE id = :id
            """), {"cat_id": category_id, "cat_name": category_name, "id": transaction_id})
            conn.commit()

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
        query = "SELECT t.*, c.name as category_name FROM transactions t LEFT JOIN categories c ON t.category_id = c.id"
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
        return pd.read_sql(text("""
            SELECT t.*, c.name as category_name 
            FROM transactions t 
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.category_id IS NULL
        """), self.engine)


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

    def update_categories(self, ml_classifier):
        """Update transaction categories using ML classifier."""
        df = self.target_db.get_unclassified_transactions()
        
        if df.empty:
            print("No unclassified transactions")
            return

        descriptions = df['description'].tolist()
        categories = ml_classifier.predict(descriptions)

        for idx, (_, row) in enumerate(df.iterrows()):
            cat_id = self.target_db.get_category_id(categories[idx])
            if cat_id:
                self.target_db.update_transaction_category(row['id'], cat_id, categories[idx])

        print(f"Categorized {len(df)} transactions")
        self.target_db.update_monthly_summary()