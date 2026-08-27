---
name: gestor-ml-categories
description: ML and keyword transaction categorization for gestor-economia using config/categories.yaml, sklearn pipeline in src/ml/classifier.py, and data/db/category_model.pkl. Use when editing categories or keywords, retraining the model after changes, training or loading the model, KeywordClassifier fallback, or main.py --skip-ml.
disable-model-invocation: true
---

# gestor-economia ML and categories

## Config

- **`config/categories.yaml`**: category `name`, per-category `keywords`, `priority_keywords`, and `inference_strategy` (`hybrid` or `ml_fallback`).
- The ML trainer skips the **Other** category when building synthetic examples from keywords.
- After changing keywords or category list, retrain or re-run the full pipeline so behavior matches.

## Categories

### Standard Categories (in categories.yaml)
- Supermarket, Restaurant, Transport, Party, Utilities, Rent, Entertainment, Shopping, Salary, Saving, Transfer, Health, Insurance, Gym, Subscriptions, Travel, Other

## Code

- **`src/ml/classifier.py`**
  - **`CategoryClassifier`**: FeatureUnion of word TF-IDF (1–3 grams) + char TF-IDF (3–5 grams) + `LogisticRegression(class_weight='balanced')`. Loads `data/db/category_model.pkl` if present.
  - **`train_combined(config, db_path, csv_path)`**: merges config keywords, DB labels, and CSV; DB/CSV win over synthetic keyword samples on conflicts.
  - **`train_from_csv(csv_path)`**: trains on manually labeled CSV (e.g., `data/training/training_data.csv`).
  - **`train_from_database(db_path)`**: learns from `transactions` joined to `categories`.
  - **`evaluate(config, db_path, csv_path)`**: holdout evaluation with macro-F1 and strategy comparison.
  - **`predict(descriptions, amounts)`**: ML-only predictions with optional amount sign feature (`| amt:income/expense`).
  - **`predict_hybrid(descriptions, config)`**: **Default strategy** — keyword-first, ML fallback when keyword returns `"Other"`.
  - **`predict_with_fallback(descriptions, config, threshold=0.5)`**: ML-first; keyword fallback when confidence < threshold.
  - **`KeywordClassifier`**: keyword matching with word-boundary checks for short keywords; uses `priority_keywords` from config.

## Training Data

- **`data/training/training_data.csv`**: Manually labeled transactions for ML training
  - Columns: `id`, `date`, `concept`, `amount`, `category`
  - To add more: select varied transactions, label manually, append to this file
- **DB labeled rows**: all categorized transactions in `normalized.db` (excluding Other)
- **Config keywords**: one synthetic sample per keyword

## Hybrid Classification (Default)

Set `inference_strategy: hybrid` in `config/categories.yaml` (default):

1. First runs `KeywordClassifier` on the description
2. If keyword returns `"Other"`, uses ML prediction instead
3. Combines high precision of keyword rules with ML's ability to learn patterns

Example:
- "Mercadona" → keyword matches → **Supermarket**
- "Compra Amazon" → keyword matches → **Shopping**
- "Transferencia De Aily Labs Iberia Nomina" → keyword returns `"Other"` → ML predicts **Salary**

## Low-Confidence Fallback

Set `inference_strategy: ml_fallback` to use ML-first with keyword rescue:

- If ML confidence < threshold (default 0.5), falls back to keyword matching

## Prediction Metadata

Transactions store:
- `predicted_category`, `prediction_confidence`, `prediction_source` (`ml`, `keyword`, `manual`)

Manual corrections in the dashboard Review tab set `prediction_source='manual'` and trigger retraining on next `--retrain-ml` or when new manual labels exceed the count at last train.

## CLI

From `main.py`:

- **`--skip-ml`**: categorize with **`KeywordClassifier`** instead of the fitted ML pipeline.
- **`--retrain-ml`**: force model retraining even if cached model exists.
- **`--evaluate-ml`**: print holdout metrics and compare `ml_only`, `hybrid`, and `ml_fallback` strategies.
- **`--recategorize-low-confidence`**: re-run categorization on low-confidence non-manual transactions.

- **Artifact**: `data/db/category_model.pkl` (joblib dict with `pipeline`, `categories`, `last_trained_at`, `manual_label_count_at_train`).

Full ingest → normalize → categorize commands: [gestor-economía-workflow](../gestor-economía-workflow/SKILL.md).

## Schema note

Training from DB expects `transactions` linked to **`categories`** by `category_id`. Normalized/denormalized `category_name` on rows is what the dashboard reads; keep classifier and DB migrations consistent when changing schema.
