# Economy Manager – Personal Finance Tracker

Parses **Santander bank transaction exports** (`.xls` format), stores them in SQLite, and **automatically categorizes every transaction** using a machine learning model. A Streamlit dashboard visualises income, expenses, and trends over time.

---

## What it does

1. **Ingestion** – Reads Santander XLS files (columns: operation date, concept, amount, balance) and stores raw rows in `ingestion.db`.
2. **Normalization** – Cleans the data, converts European number format (`1.234,56` → `1234.56`), and creates a clean schema in `normalized.db`.
3. **Categorization** – Every transaction gets a category (Supermarket, Rent, Salary, Gym, etc.) via:
   - **ML model** – A `GradientBoostingClassifier` with `TfidfVectorizer` (n-grams up to 3) trained on category keywords and your past corrections. The pipeline is saved to `category_model.pkl`.
   - **Keyword fallback** (`--skip-ml`) – Faster rule-based matching when you don't need the full model.
4. **Summary** – Prints spending totals per category and month to the terminal.

---

## Quick start

```bash
# 1. Install dependencies
.venv\Scripts\pip.exe install -r requirements.txt

# 2. Run the full pipeline (auto-detects latest XLS in current dir)
.venv\Scripts\python.exe main.py

# 3. Or point to a specific file
.venv\Scripts\python.exe main.py --file "C:\Users\you\Downloads\transactions_2026-05-03.xls"
```

### Options

| Flag | Description |
|------|-------------|
| `-f, --file` | Path to Santander XLS file |
| `--raw` | Look for file in `data/raw/` directory |
| `--no-move` | Keep original file in place (don't move to `data/raw/`) |
| `--no-clear` | Don't clear database before ingestion |
| `--skip-ml` | Use keyword classifier instead of ML model |
| `-s, --summary` | Show summary only (no ingestion) |
| `--reset` | Reset both databases |
| `--reset-normalized` | Reset normalized database only |

### Examples

```bash
# Process a specific export
.venv\Scripts\python.exe main.py -f "C:\Users\mcasa\Downloads\movimientos.xls"

# Re-run with keyword classifier (faster, no ML training)
.venv\Scripts\python.exe main.py --skip-ml -f "data\raw\transactions_2026-05-03.xls"

# Just show the current summary
.venv\Scripts\python.exe main.py --summary

# Start fresh
.venv\Scripts\python.exe main.py --reset
```

---

## How the ML model works

The classifier (`src/ml/classifier.py`) is a scikit-learn pipeline:

```
TfidfVectorizer(max_features=2000, ngram_range=(1,3))
  → GradientBoostingClassifier(n_estimators=150, max_depth=5)
```

It learns to associate transaction descriptions with categories. Training data comes from two sources:

- **`config/categories.yaml`** – Keywords defined for each category (e.g. `"mercadona"`, `"carrefour"` → Supermarket). The model treats these as labeled training samples.
- **Your manual corrections** – When you edit categories directly in `normalized.db`, the model picks them up on the next run and improves.

This means the more you use it, the better it gets at matching your real spending patterns. New categories or keywords can be added simply by editing `config/categories.yaml` and re-running.

---

## Dashboard

An interactive Streamlit + Plotly dashboard lets you explore your finances visually:

```bash
.venv\Scripts\python.exe -m streamlit run src/dashboard/app.py
```

Then open [http://localhost:8501](http://localhost:8501).

| Feature | What it shows |
|---------|---------------|
| **KPI cards** | Total income, total expenses, and net balance for the selected period |
| **Pie chart** | Expense breakdown by category (click a category to see individual transactions) |
| **Bar chart** | Monthly expense totals across all available months |
| **Stacked bar chart** | Cumulative expenses by category over time |

Use the sidebar filters to switch between years and months.

---

## Project structure

```
gestor-economia/
├── main.py                   # Pipeline entry point
├── config/
│   └── categories.yaml       # Category definitions & keywords
├── data/
│   ├── raw/                  # Original XLS files (moved here after ingestion)
│   └── db/
│       ├── ingestion.db      # Raw transaction rows
│       ├── normalized.db     # Clean, categorized transactions
│       └── category_model.pkl # Trained ML pipeline
└── src/
    ├── ingestion/reader.py   # XLS parsing & raw DB storage
    ├── normalization/        # Cleaning and schema creation
    ├── ml/classifier.py      # ML model (GradientBoosting) + keyword fallback
    └── dashboard/app.py      # Streamlit dashboard
```

## Customising categories

Edit `config/categories.yaml` and add keywords for any transaction description patterns. The next pipeline run retrains the model with the new data.

```
categories:
  - name: "Supermarket"
    keywords:
      - "mercadona"
      - "carrefour"
      - "lidl"
```
