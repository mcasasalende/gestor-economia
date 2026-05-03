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
- Food, Transport, Utilities, Rent, Entertainment, Shopping, Salary, Saving, Transfer, Health, Insurance, Subscriptions, **Travel**, Other

### Travel Category
Keywords: booking, hotel, airbnb, vuelos, flight, viaje, travel, bkg, reserva

## Code

- **`src/ml/classifier.py`**
  - **`CategoryClassifier`**: TfidfVectorizer (1–2 grams, max 1000 features) + LogisticRegression (multinomial, balanced class weights). Loads `data/db/category_model.pkl` if present; otherwise initializes an unfitted pipeline.
  - **`train_from_config(config)`**: builds training strings from each keyword (and category name if no keywords); fits and can `save()` to `model_path`.
  - **`train_from_database(db_path)`**: learns from `transactions` joined to `categories`; requires enough rows (code checks `len(X) < 10`).
  - **`predict_with_fallback(descriptions, config, threshold=0.5)`**: ML prediction with keyword fallback when confidence < threshold (0.5 = 50%).
  - **`KeywordClassifier`**: substring keyword counts per description; used as fallback for low-confidence predictions.

## Low-Confidence Fallback

When ML confidence is below 0.5, `KeywordClassifier` is used as fallback:
- `CategoryClassifier.predict_with_fallback()` combines ML confidence scores with keyword matching
- Enabled by default in `DataNormalizer.update_categories()` via `use_fallback=True`
- Falls back to keyword matching for: "booking" (Travel), "Splinters" (Subscriptions), "alquiler" (Rent), self-transfers (Saving)

- **Artifact**: `data/db/category_model.pkl` (joblib dict with `pipeline` and `categories`). Delete to force retraining.

## CLI

From `main.py`:

- **`--skip-ml`**: categorize with **`KeywordClassifier`** instead of the fitted ML pipeline.

Full ingest → normalize → categorize commands: [gestor-economía-workflow](../gestor-economía-workflow/SKILL.md).

## Schema note

Training from DB expects `transactions` linked to **`categories`** by `category_id`. Normalized/denormalized `category_name` on rows is what the dashboard reads; keep classifier and DB migrations consistent when changing schema.
