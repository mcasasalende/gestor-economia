---
name: gestor-ml-categories
description: ML and keyword transaction categorization for gestor-economia using config/categories.yaml, sklearn pipeline in src/ml/classifier.py, and data/db/category_model.pkl. Use when editing categories or keywords, retraining the model after changes, training or loading the model, KeywordClassifier fallback, or main.py --skip-ml.
disable-model-invocation: true
---

# gestor-economia ML and categories

## Config

- **`config/categories.yaml`**: category `name` and per-category `keywords`. The ML trainer skips the **Other** category when building synthetic examples from keywords.
- After changing keywords or category list, retrain or re-run the full pipeline so behavior matches.

## Categories

### Standard Categories (in categories.yaml)
- Supermarket, Restaurant, Transport, Party, Utilities, Rent, Entertainment, Shopping, Salary, Saving, Transfer, Health, Gym, Subscriptions, Travel, Other

Note: **Insurance** was removed from categories.

## Code

- **`src/ml/classifier.py`**
  - **`CategoryClassifier`**: TfidfVectorizer (1–3 grams, max 2000 features) + GradientBoostingClassifier (150 estimators, max_depth=5). Loads `data/db/category_model.pkl` if present; otherwise initializes an unfitted pipeline.
  - **`train_from_config(config)`**: builds training strings from each keyword (and category name if no keywords); fits and can `save()` to `model_path`.
  - **`train_from_csv(csv_path)`**: trains on manually labeled CSV (e.g., `data/training/training_data.csv`).
  - **`train_from_database(db_path)`**: learns from `transactions` joined to `categories`; requires enough rows (code checks `len(X) < 10`).
  - **`predict(descriptions)`**: ML-only predictions.
  - **`predict_hybrid(descriptions, config)`**: **Keyword-first + ML fallback**. Uses keywords first, falls back to ML only when keyword returns "Other".
  - **`predict_with_fallback(descriptions, config, threshold=0.5)`**: ML prediction with keyword fallback when confidence < threshold.
  - **`KeywordClassifier`**: substring keyword counts per description; used as fallback for low-confidence predictions.

## Training Data

- **`data/training/training_data.csv`**: Manually labeled transactions for ML training
  - Columns: `id`, `date`, `concept`, `amount`, `category`
  - Currently 70 labeled samples
  - To add more: select varied transactions, label manually, append to this file

## Hybrid Classification (Default)

The classifier now uses a **keyword-first + ML fallback** approach:
1. First runs `KeywordClassifier` on the description
2. If keyword returns "Other", uses ML prediction instead
3. This combines high precision of keyword rules with ML's ability to learn patterns

Example:
- "Mercadona" → keyword matches → **Supermarket**
- "Compra Amazon" → keyword matches → **Shopping**
- "Transferencia De Aily Labs Iberia Nomina" → keyword returns "Other" → ML predicts **Salary**

## Low-Confidence Fallback

When using `predict_with_fallback()`:
- If ML confidence < threshold (default 0.5), falls back to keyword matching
- Enabled by default in `DataNormalizer.update_categories()` via `use_fallback=True`

- **Artifact**: `data/db/category_model.pkl` (joblib dict with `pipeline` and `categories`). Delete to force retraining.

## CLI

From `main.py`:

- **`--skip-ml`**: categorize with **`KeywordClassifier`** instead of the fitted ML pipeline.

Full ingest → normalize → categorize commands: [gestor-economía-workflow](../gestor-economía-workflow/SKILL.md).

## Schema note

Training from DB expects `transactions` linked to **`categories`** by `category_id`. Normalized/denormaled `category_name` on rows is what the dashboard reads; keep classifier and DB migrations consistent when changing schema.