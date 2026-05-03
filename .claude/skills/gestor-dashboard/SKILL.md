---
name: gestor-dashboard
description: Streamlit + Plotly economy dashboard for gestor-economia; reads categorized transactions from SQLite. Use when editing src/dashboard/app.py, Streamlit layout or filters, Plotly charts, or dashboard DB access.
disable-model-invocation: true
---

# gestor-economia dashboard

## Run (repo root)

```powershell
.venv/Scripts/python.exe -m streamlit run src/dashboard/app.py
```

Default URL: `http://localhost:8501`

## Data source

- Entry: `src/dashboard/app.py`
- DB path is built relative to that file: `data/db/normalized.db` (see `DB_PATH` in the app).
- Query uses `transactions` with `date`, `description`, `amount`, `category_name` (rows with non-null `category_name`).
- **Expenses** are negative `amount`; income is positive. Metrics use that sign convention.
- If the pipeline wrote only `normalized_v2.db`, the dashboard still points at `normalized.db` unless you change `DB_PATH` — align the filename with the active DB.

## Empty UI

If `get_data()` returns no rows, the app shows a warning to run ingestion first. Ensure normalization and categorization have populated `category_name`.

## Full pipeline

Ingestion, CLI flags, and DB layout: [gestor-economía-workflow](../gestor-economía-workflow/SKILL.md).
