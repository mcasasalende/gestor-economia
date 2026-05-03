import os
import re
import glob
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


class TransactionReader:
    """Reads bank transaction XLS files."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._validate_file()

    def _validate_file(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if not self.file_path.endswith('.xls'):
            raise ValueError(f"Expected .xls file, got: {self.file_path}")

    def _parse_european_number(self, value) -> float:
        """Convert European format (1.234,56) to float."""
        if pd.isna(value):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        value = str(value).strip()
        value = value.replace('.', '').replace(',', '.')
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parse_date(self, value: str) -> str:
        """Parse date from DD/MM/YYYY to YYYY-MM-DD."""
        if pd.isna(value) or value == '':
            return None
        value = str(value).strip()
        try:
            dt = datetime.strptime(value, '%d/%m/%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return None

    def read(self) -> pd.DataFrame:
        """Read and parse the XLS file."""
        df = pd.read_excel(self.file_path, header=None, dtype=str)

        header_row = None
        for idx, row in df.iterrows():
            row_str = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
            if "FECHA OPERACIÓN" in row_str:
                header_row = idx
                break

        if header_row is None:
            raise ValueError("Could not find header row in file")

        df = pd.read_excel(self.file_path, header=header_row)

        df.columns = df.columns.str.strip()

        required_cols = ['FECHA OPERACIÓN', 'CONCEPTO', 'IMPORTE EUR']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        df = df[required_cols + ['FECHA VALOR', 'SALDO'] if 'SALDO' in df.columns else required_cols].copy()

        result = pd.DataFrame()
        result['operation_date'] = df['FECHA OPERACIÓN'].apply(self._parse_date)
        result['value_date'] = df['FECHA VALOR'].apply(self._parse_date) if 'FECHA VALOR' in df.columns else result['operation_date']
        result['description'] = df['CONCEPTO'].fillna('').astype(str)
        result['amount'] = df['IMPORTE EUR'].apply(self._parse_european_number)
        result['balance'] = df['SALDO'].apply(self._parse_european_number) if 'SALDO' in df.columns else 0.0

        result = result[result['description'].str.strip() != ''].reset_index(drop=True)

        return result


class DatabaseIngestor:
    """Handles database operations for raw data storage."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}')
        self._ensure_tables()

    def _ensure_tables(self):
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS raw_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_date TEXT,
                    value_date TEXT,
                    description TEXT,
                    amount REAL,
                    balance REAL,
                    source_file TEXT,
                    imported_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def ingest(self, df: pd.DataFrame, source_file: str):
        """Insert transactions into database."""
        df['source_file'] = source_file
        df.to_sql('raw_transactions', self.engine, if_exists='append', index=False)
        print(f"Ingested {len(df)} transactions from {source_file}")

    def get_latest_file_date(self) -> str:
        """Get the date from the latest imported file."""
        with self.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT source_file FROM raw_transactions ORDER BY imported_at DESC LIMIT 1"
            )).fetchone()
            return result[0] if result else None


class FileFinder:
    """Finds transaction files matching the pattern."""

    @staticmethod
    def find_latest(directory: str = None) -> str:
        """Find the most recent transaction file matching the pattern."""
        if directory is None:
            directory = os.getcwd()
        
        pattern = os.path.join(directory, "transactions_*.xls")
        files = glob.glob(pattern)
        
        if not files:
            raise FileNotFoundError(f"No transaction files found in {directory}")
        
        return max(files, key=os.path.getctime)

    @staticmethod
    def extract_date_from_filename(filename: str) -> str:
        """Extract date from filename like transactions_2026-05-03T11_17_36.697Z.xls"""
        match = re.search(r'transactions_(\d{4}-\d{2}-\d{2})T', filename)
        if match:
            return match.group(1)
        return None