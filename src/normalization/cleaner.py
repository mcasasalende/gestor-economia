import csv
import os
import yaml
from datetime import datetime
from pathlib import Path
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

    def _default_training_csv(self) -> Path:
        return Path(__file__).parent.parent.parent / "data" / "training" / "training_data.csv"

    def _format_date_for_csv(self, date_val) -> str:
        if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
            return ""
        s = str(date_val).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        # already DD/MM/YYYY
        if "/" in s and len(s.split("/")[0]) == 2:
            return s
        return s

    def persist_manual_correction(self, description: str, amount: float, date_val, category_name: str, csv_path: str | Path | None = None) -> bool:
        """Append a manual correction to training_data.csv (durable, survives DB wipe)."""
        try:
            target = Path(csv_path) if csv_path else self._default_training_csv()
            target.parent.mkdir(parents=True, exist_ok=True)

            date_str = self._format_date_for_csv(date_val)
            desc = (description or "").strip()
            cat = (category_name or "").strip()
            if not desc or not cat:
                return False

            # deduplicate against existing CSV (concept + amount + category)
            if target.exists() and target.stat().st_size > 0:
                try:
                    existing = pd.read_csv(target)
                    if not existing.empty and 'concept' in existing.columns:
                        # exact concept+category match and amount within 0.001
                        mask = (existing['concept'].astype(str).str.strip() == desc) & (existing['category'].astype(str).str.strip() == cat)
                        if 'amount' in existing.columns:
                            try:
                                mask = mask & (pd.to_numeric(existing['amount'], errors='coerce').fillna(0).sub(float(amount)).abs() < 0.001)
                            except Exception:
                                pass
                        if mask.any():
                            return False
                        # next id
                        try:
                            next_id = int(pd.to_numeric(existing['id'], errors='coerce').max()) + 1
                        except Exception:
                            next_id = len(existing) + 1
                    else:
                        next_id = 1
                except pd.errors.EmptyDataError:
                    next_id = 1
                header = False
            else:
                existing = None
                next_id = 1
                header = True
                # need to write header; will be handled by to_csv header logic below
                if target.exists():
                    header = target.stat().st_size == 0
                else:
                    header = True

            # if we already determined header/mask, reconstruct flag
            if target.exists() and target.stat().st_size > 0:
                header = False
            else:
                header = True

            row = pd.DataFrame([{
                'id': next_id,
                'date': date_str,
                'concept': desc,
                'amount': float(amount) if amount is not None else "",
                'category': cat,
            }])
            # Use csv quoting for commas in concept
            row.to_csv(target, mode='a', header=header, index=False, quoting=csv.QUOTE_MINIMAL)
            return True
        except Exception as e:
            print(f"Warning: could not persist manual correction to CSV: {e}")
            return False

    def persist_all_manual_to_csv(self, csv_path: str | Path | None = None) -> int:
        """Bulk-export all manual rows not yet in CSV (used as backup before DB wipe)."""
        try:
            df_manual = pd.read_sql(text(
                "SELECT date, description, amount, category_name FROM transactions WHERE prediction_source='manual'"
            ), self.engine)
        except Exception as e:
            print(f"Warning: could not read manual rows: {e}")
            return 0
        if df_manual.empty:
            return 0
        appended = 0
        for _, r in df_manual.iterrows():
            if self.persist_manual_correction(r['description'], r['amount'], r['date'], r['category_name'], csv_path=csv_path):
                appended += 1
        if appended:
            print(f"Backed up {appended} manual correction(s) to training_data.csv")
        return appended

    def set_manual_category(self, transaction_id: int, category_id: int, category_name: str):
        """Set category from manual correction in the dashboard (also persists to CSV)."""
        self.update_transaction_category(
            transaction_id,
            category_id,
            category_name=category_name,
            predicted_category=category_name,
            prediction_confidence=1.0,
            prediction_source='manual',
        )
        # persist to durable CSV so it survives normalized.db wipe on next ingest (main.py:55-59)
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT date, description, amount FROM transactions WHERE id = :id"
                ), {"id": transaction_id}).fetchone()
            if row:
                self.persist_manual_correction(row[1], row[2], row[0], category_name)
        except Exception as e:
            print(f"Warning: manual DB update succeeded but CSV persist failed: {e}")

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
