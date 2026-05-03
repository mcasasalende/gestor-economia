# Economy Manager

Personal finance tracker that reads bank transaction files (XLS format), stores them in SQLite databases, and automatically categorizes transactions using ML.

## Project Structure

```
gestor-economia/
├── main.py                   # Main entry point
├── config/
│   └── categories.yaml      # Category definitions
├── data/
│   ├── raw/                 # Raw XLS files (after ingestion)
│   └── db/
│       ├── ingestion.db     # Raw transaction data
│       ├── normalized.db    # Categorized transactions
│       └── category_model.pkl
└── src/
    ├── ingestion/           # XLS reading & storage
    ├── normalization/        # Data cleaning & categorization
    └── ml/                  # ML classification
```

## Requirements

- Python 3.10+
- Virtual environment (`.venv/`)

Install dependencies:
```bash
.venv\Scripts\pip.exe install -r requirements.txt
```

## Usage

### Full Pipeline

Run with the latest transaction file in the current directory:
```bash
.venv\Scripts\python.exe main.py
```

### Specify File

Point to a specific XLS file:
```bash
.venv\Scripts\python.exe main.py --file "path\to\transactions_2026-05-03.xls"
```

### Use Raw Directory

The pipeline automatically looks for new files in the current directory. After ingestion, files are moved to `data/raw/`.

To process a file from `data/raw/`:
```bash
.venv\Scripts\python.exe main.py --file "data\raw\transactions_2026-05-03T11_17_36.697Z.xls"
```

To process all files in `data/raw/`:
```bash
.venv\Scripts\python.exe main.py --file "data\raw\transactions_*.xls"
```

### Options

| Flag | Description |
|------|-------------|
| `-f, --file` | Path to transaction XLS file |
| `--no-move` | Keep original file in place (don't move to `data/raw/`) |
| `--no-clear` | Don't clear database before ingestion (default: clears) |
| `--skip-ml` | Use keyword classifier instead of ML model |
| `-s, --summary` | Show summary only (no ingestion) |
| `--reset` | Reset both databases |
| `--reset-normalized` | Reset normalized database only |

### Examples

```bash
# Process new file
.venv\Scripts\python.exe main.py --file "C:\Users\mcasa\Downloads\transactions_2026-05-03.xls"

# Show current summary
.venv\Scripts\python.exe main.py --summary

# Re-run with keyword classifier (faster, no ML)
.venv\Scripts\python.exe main.py --skip-ml --file "data\raw\transactions_2026-05-03.xls"

# Reset and start fresh
.venv\Scripts\python.exe main.py --reset
```

## Categories

Edit `config/categories.yaml` to customize categories and their keywords. The ML model trains on these keywords initially, then improves as you manually correct categorizations in the database.

## Database Schema

### ingestion.db (Raw)
- `raw_transactions`: operation_date, value_date, description, amount, balance, source_file

### normalized.db (Processed)
- `transactions`: date, description, amount, category_id, source
- `categories`: name, keywords
- `monthly_summary`: category_id, year_month, total_amount, transaction_count

## Workflow

1. **Ingestion**: Read XLS file → store in `ingestion.db` → move file to `data/raw/` (database is cleared first by default)
2. **Normalization**: Clean data → create normalized tables in `normalized.db`
3. **Categorization**: ML model classifies transactions based on description
4. **Summary**: Display spending by category and month

## Dashboard

Run the visualization dashboard:

```bash
.venv\Scripts\python.exe -m streamlit run src/dashboard/app.py
```

Then open http://localhost:8501 in your browser.

The dashboard shows:
- **Pie chart**: Current month expenses by category
- **Bar chart**: Monthly expenses grouped by month
- **Stacked bar**: Cumulative expenses by category over time
- **Metrics**: Total income, expenses, and net balance

Use the sidebar to filter by year and month.