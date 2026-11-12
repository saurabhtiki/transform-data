# Transform Data

Reusable Django add-on: upload CSV / Excel / JSON, change it step by step (join, filter, formulas, group, pivot, clean up…), then download Excel or JSON. Data stays in memory only.

## Add it to a project
```
uv add "transform-data @ git+https://github.com/saurabhtiki/transform-data"
```
This also installs `data-core` from https://github.com/saurabhtiki/data-core.
To change both packages together locally, run `uv add --editable ../data-core` (don't commit that).

```python
INSTALLED_APPS += ["django.contrib.messages", "django_datatable", "transform_data"]
DATA_CORE = {"MAX_FILE_MB": 20, "SESSION_MEMORY_MB": 150}
TRANSFORM_DATA = {"BASE_TEMPLATE": "base.html"}  # your page frame (htmx 2, Alpine 3, DaisyUI 5)
# urls.py
path("transform/", include("transform_data.urls")),
```
Your Tailwind build must scan `transform_data/templates` and `transform_data/*.py`.

The server must run as **one process** (threads are fine): each user's data lives in that process's memory.

## Run the demo
```
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8020
```
Open http://localhost:8020/transform/. Environments: `DJANGO_ENV=development | test | production` (reads `.env.<env>`).

## Tests
```
uv run pytest
```

## CSS
After changing classes: `.\tools\build_css.ps1` (uses `tools\tailwindcss.exe`, or My Insights' copy next door).
