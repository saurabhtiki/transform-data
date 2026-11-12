"""Transform Data settings. A host overrides any of them with one block in settings.py:

TRANSFORM_DATA = {"BASE_TEMPLATE": "base.html", "PREVIEW_ROWS": 2000}

File limits and memory (MAX_FILE_MB, MAX_ROWS, SESSION_MEMORY_MB …) are data-core's:
DATA_CORE = {"MAX_FILE_MB": 20}
"""

from django.conf import settings

DEFAULTS = {
    # Template the pages extend. It must have `title`, `extra_head` and `content` blocks and
    # load htmx 2, Alpine 3, DaisyUI 5 and django-datatable's CSS / JS.
    "BASE_TEMPLATE": "transform_data/base.html",
    # Rows shown in the on-screen preview (the download always has every row).
    "PREVIEW_ROWS": 5000,
    # Recipes: the steps as JSON, no data. With no hooks the user downloads / uploads a
    # .json file. A host can store recipes itself:
    #   RECIPE_SAVE = "myapp.recipes.save"  → save(request, recipe: dict, name) -> str
    #       (the message shown, e.g. "Saved as Monthly sales")
    #   RECIPE_LOAD = "myapp.recipes.load"  → load(request, recipe_id: str) -> dict
    #       (the host's own page links to /transform/recipe/open/?id=7)
    "RECIPE_SAVE": None,
    "RECIPE_LOAD": None,
    "RECIPE_MAX_KB": 512,
}


def get(name: str):
    """One setting, from the host's TRANSFORM_DATA block or the default."""
    return getattr(settings, "TRANSFORM_DATA", {}).get(name, DEFAULTS[name])
