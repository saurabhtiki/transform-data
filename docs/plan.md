# Phase 1 — thin end-to-end slice (done)

Goal: upload → steps → preview → download Excel/JSON, with recipes. Reuse, don't rewrite.

## Decisions (agreed)
- Shared **data-core** package for loading + formulas (copied from My Insights, `Workspace` replaced by a slim `DataStore`). My Insights is not changed yet (Phase 4).
- Data is loaded through DuckDB, then each table is held as a **pandas** DataFrame; steps run the prototype's pandas operations.
- Recipes: JSON file download/upload + host hooks (`RECIPE_SAVE` / `RECIPE_LOAD`).

## What was built
- `../data-core`: `store.py` (DataStore, StoreRegistry, session glue), `loading.py`, `json_loading.py`, `uploads.py`, `formula.py`, `frames.py` (DuckDB ↔ pandas, formula on a DataFrame). 61 tests.
- `transform_data/engine`: the prototype's `transform` + `cleaner` modules. All 35 operations came along (planned: 10) because they share code and already had tests.
- Calculated column and if/else answers now use the data-core formula (`[Col]`, IF, text, dates) instead of the old number-only `expressions.py`.
- Prototype bugs fixed: rank choices; one number reader everywhere (₹1,200, (300), 300-); join/lookup unmatched counts; lookup key picked twice; append overwriting a "source table" column; pivot duplicate column names; recipe JSON silently turning values into text.
- Screens: `home.html` (tables, steps, preview via django-datatable), step picker with search, step form drawn from each operation's ParamSpecs (redraws on table change), live formula check, Download dialog, Recipe save/load.
- Tests: 889 ported engine tests (adjusted to the new formula syntax) + 28 new view / fix tests = 917.

## How to check
```
uv run pytest            # in data-core and in transform-data
uv run python manage.py runserver 8020   # then open /transform/
```
Upload two CSVs → Join → Add calculated column `[Sales] - [Cost]` → Group by → Download Excel & JSON → Save recipe → Start over → upload again → Load recipe.

## Known limits (next phases)
- Recipe tables are matched by **name** only (Phase 2 adds matching by file and renaming).
- Every step change re-runs the whole step list (fine for ≤ a few hundred thousand rows).
- Only CSV / Excel / JSON sources (API and SQL in Phase 3).
