---
name: gestor-economia-workflow
description: Runs ingestion, normalization, ML categorization, and Streamlit dashboard for gestor-economia. Use when ingesting bank XLS files, SQLite ingestion/normalized DBs, category_model.pkl, config/categories.yaml, European decimals, locked DB _v2 files, or the finance dashboard pipeline.
disable-model-invocation: true
---

# gestor-economia workflow

## Quick commands (Windows, repo root)

Install:

```powershell
.venv/Scripts/pip.exe install -r requirements.txt
```

Full pipeline (ingest → normalize → categorize → summary):

```powershell
.venv/Scripts/python.exe main.py --file "path/to/file.xls"
```

Ingest latest file already under `data/raw/`:

```powershell
.venv/Scripts/python.exe main.py --raw
```

Dashboard (reads normalized DB):

```powershell
.venv/Scripts/python.exe -m streamlit run src/dashboard/app.py
```

## Pipeline order

1. **Ingestion**: XLS → `data/db/ingestion.db`; source file moved to `data/raw/` unless `--no-move`.
2. **Normalization**: → `data/db/normalized.db` (or `*_v2` if locked).
3. **Categorization**: `src/ml/classifier.py` on description text; model at `data/db/category_model.pkl`; keywords/categories from `config/categories.yaml` — detail: [gestor-ml-categories](../gestor-ml-categories/SKILL.md).
4. **Dashboard**: `src/dashboard/app.py` (Plotly), uses normalized DB — detail: [gestor-dashboard](../gestor-dashboard/SKILL.md).

## CLI flags (`main.py`)

| Flag | Effect |
|------|--------|
| `--file` / `-f` | Path to XLS |
| `--raw` / `-r` | Pick latest file from `data/raw/` |
| `--skip-ml` | Keyword classifier instead of ML |
| `--no-move` | Leave XLS in place (no move to `data/raw/`) |
| `--no-clear` | Do not delete ingestion DB before ingest |
| `--reset` | Remove ingestion DB only, exit |
| `--reset-normalized` | Remove normalized DB only, exit |
| `--summary` / `-s` | Print DB summary only, exit |

## Domain rules

- **European decimals** in XLS (`1.234,56`): handled in `src/ingestion/reader.py` (`_parse_european_number`); do not break the int/float guard before string parsing.
- **Expenses** are stored as **negative** amounts in SQLite.
- **`category_name`** on `transactions` is denormalized for simpler queries.
- **Locked DBs**: code may create `ingestion_v2.db` / `normalized_v2.db`; treat `_v2` as the active DB if present.

## File patterns

- Typical export name: `transactions_YYYY-MM-DDTHH_MM_SS.XXXZ.xls`
- Raw archive: `data/raw/`

## Tuning categories

See [gestor-ml-categories](../gestor-ml-categories/SKILL.md).

## Related skills

- [gestor-dashboard](../gestor-dashboard/SKILL.md) — Streamlit app, Plotly, `normalized.db` wiring
- [gestor-ml-categories](../gestor-ml-categories/SKILL.md) — `categories.yaml`, ML vs keyword, `category_model.pkl`

## More context

[AGENTS.md](../../../AGENTS.md) indexes `.claude/skills/`.
