#!/usr/bin/env python3
"""
Economy Manager - Main Entry Point

This script orchestrates the full pipeline:
1. Ingestion: Read XLS file and store in raw database
2. Normalization: Clean data and create normalized tables
3. Categorization: ML-based transaction categorization
"""

import os
import sys
import shutil
import argparse
import yaml
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ingestion.reader import TransactionReader, DatabaseIngestor, FileFinder
from src.normalization.cleaner import DataNormalizer
from src.ml.classifier import CategoryClassifier, KeywordClassifier
from src.export.exporter import export as export_snapshot


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "categories.yaml"
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DB_DIR = DATA_DIR / "db"
INGESTION_DB = DB_DIR / "ingestion.db"
NORMALIZED_DB = DB_DIR / "normalized.db"
MODEL_PATH = DB_DIR / "category_model.pkl"


def load_config() -> dict:
    """Load categories configuration."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_dirs():
    """Ensure required directories exist."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)


def run_ingestion(file_path: str = None, move_raw: bool = True, from_raw: bool = False, clear_db: bool = True):
    """Run the ingestion pipeline."""
    print("\n=== INGESTION ===")
    
    if clear_db:
        reset_database(normalized=False)
        if NORMALIZED_DB.exists():
            NORMALIZED_DB.unlink()
            print(f"Removed: {NORMALIZED_DB}")
    
    if file_path is None:
        search_dir = str(RAW_DIR) if from_raw else None
        try:
            file_path = FileFinder.find_latest(search_dir)
        except FileNotFoundError:
            if not from_raw:
                file_path = FileFinder.find_latest(str(RAW_DIR))
                print(f"Found file in raw directory: {file_path}")
    
    print(f"Reading: {file_path}")
    
    reader = TransactionReader(file_path)
    df = reader.read()
    
    print(f"Found {len(df)} transactions")
    
    ingestor = DatabaseIngestor(str(INGESTION_DB))
    source_file = os.path.basename(file_path)
    ingestor.ingest(df, source_file)
    
    if move_raw and str(RAW_DIR) not in str(file_path):
        dest = RAW_DIR / source_file
        shutil.move(file_path, dest)
        print(f"Moved raw file to: {dest}")
    
    return df


def run_normalization():
    """Run the normalization pipeline."""
    print("\n=== NORMALIZATION ===")
    
    config = load_config()
    normalizer = DataNormalizer(str(INGESTION_DB), str(NORMALIZED_DB))
    normalizer.run(config)
    
    return normalizer


def run_categorization(normalizer, use_ml: bool = True):
    """Run the categorization pipeline."""
    print("\n=== CATEGORIZATION ===")
    
    config = load_config()
    
    if use_ml:
        classifier = CategoryClassifier(str(MODEL_PATH))
        
        classifier.train_from_config(config)
        
        if os.path.exists(NORMALIZED_DB):
            classifier.train_from_database(str(NORMALIZED_DB))
        
        normalizer.update_categories(classifier)
    else:
        classifier = KeywordClassifier(config)
        
        from src.normalization.cleaner import NormalizedDatabase
        db = NormalizedDatabase(str(NORMALIZED_DB))
        
        df = db.get_unclassified_transactions()
        if not df.empty:
            predictions = classifier.predict(df['description'].tolist())
            
            for idx, (_, row) in enumerate(df.iterrows()):
                cat_id = db.get_category_id(predictions[idx])
                if cat_id:
                    db.update_transaction_category(row['id'], cat_id)
            
            db.update_monthly_summary()
            print(f"Categorized {len(df)} transactions")


def show_summary():
    """Display summary of the data."""
    print("\n=== SUMMARY ===")
    
    from sqlalchemy import create_engine, text
    import pandas as pd
    
    engine = create_engine(f'sqlite:///{NORMALIZED_DB}')
    
    summary = pd.read_sql(text("""
        SELECT 
            c.name as category,
            COUNT(*) as count,
            SUM(t.amount) as total
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        GROUP BY c.name
        ORDER BY total
    """), engine.connect())
    
    print("\nBy Category:")
    print(summary.to_string(index=False))
    
    monthly = pd.read_sql(text("""
        SELECT year_month, SUM(total_amount) as total
        FROM monthly_summary
        GROUP BY year_month
        ORDER BY year_month DESC
        LIMIT 10
    """), engine.connect())
    
    print("\nMonthly Totals:")
    print(monthly.to_string(index=False))


def reset_database(normalized: bool = False):
    """Reset databases."""
    if normalized and NORMALIZED_DB.exists():
        NORMALIZED_DB.unlink()
        print(f"Removed: {NORMALIZED_DB}")
    
    if INGESTION_DB.exists():
        INGESTION_DB.unlink()
        print(f"Removed: {INGESTION_DB}")


def main():
    parser = argparse.ArgumentParser(description="Economy Manager")
    parser.add_argument('--file', '-f', help='Transaction file path')
    parser.add_argument('--raw', '-r', action='store_true', help='Look for file in data/raw/ directory')
    parser.add_argument('--skip-ml', action='store_true', help='Use keyword classifier instead of ML')
    parser.add_argument('--no-move', action='store_true', help='Do not move raw file')
    parser.add_argument('--reset', action='store_true', help='Reset databases')
    parser.add_argument('--reset-normalized', action='store_true', help='Reset normalized database only')
    parser.add_argument('--no-clear', action='store_true', help='Do not clear database before ingestion')
    parser.add_argument('--export', action='store_true', help='Export snapshot.json.gz for the mobile app')
    parser.add_argument('--summary', '-s', action='store_true', help='Show summary only')
    
    args = parser.parse_args()
    
    ensure_dirs()
    
    if args.reset:
        reset_database(normalized=False)
        return
    
    if args.reset_normalized:
        reset_database(normalized=True)
        return
    
    if args.summary:
        show_summary()
        return

    if args.export and not (args.file or args.raw):
        export_snapshot()
        return

    df = run_ingestion(file_path=args.file, move_raw=not args.no_move, from_raw=args.raw, clear_db=not args.no_clear)
    
    if len(df) == 0:
        print("No transactions found")
        return
    
    normalizer = run_normalization()
    
    run_categorization(normalizer, use_ml=not args.skip_ml)
    
    show_summary()

    if args.export:
        export_snapshot()

    print("\n=== COMPLETE ===")


if __name__ == "__main__":
    main()