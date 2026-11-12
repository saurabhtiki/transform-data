# Transform Data — scope & requirements

## What it is
A reusable Django add-on: **get data → transform it step by step → download Excel and/or JSON.**
Works on its own, and is stage 1 of the end-to-end product:

```
data-core (load)  →  Transform Data (clean / reshape)  →  My Insights (dashboards)
```

Example: upload `sales.csv` + `customers.xlsx` → join on Customer ID → add `Profit = [Sales] - [Cost]` → group by City → download `result.xlsx`.

## Pieces
| Piece | What it does |
|---|---|
| `data-core` (separate package, `../data-core`) | Loads CSV / Excel / JSON into a private in-memory DuckDB per user; Excel-like formulas. Shared with My Insights. |
| `transform_data.engine` | The step operations (pandas), ported from the Streamlit prototype (`TikitarAi/transform` + `cleaner`). Pure Python, no Django. |
| `transform_data` (views, templates) | One screen: 1 · Your tables (each with a 📊 profile popup: type, blanks, distinct, smallest / largest, tips), 2 · Steps, 3 · Preview; Download and Recipe dialogs. HTMX + Alpine + DaisyUI. |

## Rules
- **No data at rest.** Uploads are read in memory, kept per session, wiped on logout / idle (data-core `IDLE_CLEAR_MINUTES`). The server runs as one process.
- A **step** names the table(s) it reads and where its answer goes (same table / new table). Steps run in order; only the **last** step can be edited or undone.
- A **recipe** = the steps as JSON (no data). Download/upload a `.recipe.json`, or the host stores it via `RECIPE_SAVE` / `RECIPE_LOAD` hooks.
- Downloads: Excel (one sheet per table + a sheet listing the steps) or JSON `{"table": [{row}, …]}`.
- Every table on screen uses `django-datatable`. Every control has a tooltip / help line.

## Operations (35)
Combine (join, lookup, append) · Calculated columns (formula, if/else, ranges, % of total, abs, row min/max) · Summarise (group, pivot, unpivot, rank, running total) · Filter & sort · Columns (type, drop, rename, split, combine, extract) · Dates (part, difference, today, shift, month start/end) · Tidy up (skip rows, blanks, trim, special characters, case, find/replace, fix numbers, round, fill blanks, duplicates).

Formula language (data-core): `[Sales] * 0.18`, `IF([Qty] > 100, "Bulk", "Retail")`, `[First] & " " & [Last]`, `DAYS_BETWEEN([Date], TODAY())`. Text that holds only numbers (`"1,200"`) is read as numbers in a formula.

## Settings (host `settings.py`)
```python
DATA_CORE = {
    "MAX_FILE_MB": 20,
    "MAX_ROWS": 500_000,
    "SESSION_MEMORY_MB": 150,
    "TOTAL_MEMORY_MB": 350,
}
TRANSFORM_DATA = {
    "BASE_TEMPLATE": "base.html",
    "PREVIEW_ROWS": 5000,
    "RECIPE_SAVE": None,
    "RECIPE_LOAD": None,
    "RECIPE_MAX_KB": 512,
}
```
Needs `django.contrib.messages`, `django.contrib.sessions`, `django_datatable`, `transform_data` in `INSTALLED_APPS`; `path("transform/", include("transform_data.urls"))`.

## Roadmap
1. ✅ Thin end-to-end slice (this app + data-core).
2. Recipe replay on next month's files: match uploads to the recipe's tables even when names differ (`matching.py` from the prototype); rename a table.
3. API + SQL sources: move `api_import`, `db_loading`, `db_connect` from My Insights into data-core.
4. My Insights imports its loaders and formula from data-core (its 496 tests must pass unchanged).
5. New operations: keep/reorder columns, anti-join, reconcile two tables, previous-row change, moving average, top N per group, map values, first non-blank, split cell into rows, extract by pattern, pad text, fill missing dates, flag outliers, validation rules, transpose.
6. Hand-off: "Open in My Insights" (results become datasets in the same store); optional plain-English step entry (AI).
