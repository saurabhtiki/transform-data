"""What the user takes away: the tables as Excel or JSON, and the recipe (steps, no data)."""

import json
import logging

import pandas as pd

from .engine.exceptions import PipelineStorageError, TransformExportError
from .engine.export import build_transform_workbook
from .engine.template import SavedPipeline, capture, from_json, to_json
from .engine.workspace import NamedFrame, name_key
from .state import TransformStore

logger = logging.getLogger(__name__)

RECIPE_KIND = "transform-data recipe"


def chosen_tables(store: TransformStore, names: list[str]) -> list[tuple[str, NamedFrame]]:
    """The tables picked for download, in the page's order. Raises TransformExportError."""
    if not names:
        raise TransformExportError("Tick at least one table to download.")
    wanted = {name_key(name) for name in names}
    chosen = [(held, table) for held, table in store.result.items() if name_key(held) in wanted]
    if len(chosen) != len(wanted):
        raise TransformExportError("Some of those tables are gone. Pick again and download.")
    return chosen


def excel_bytes(store: TransformStore, names: list[str]) -> bytes:
    """One sheet per table, plus a sheet listing the steps."""
    chosen = chosen_tables(store, names)
    return build_transform_workbook(store.result, [held for held, _ in chosen], store.steps)


def json_bytes(store: TransformStore, names: list[str]) -> bytes:
    """{"table name": [{"column": value, …}, …], …}. Dates as yyyy-mm-dd(Thh:mm:ss)."""
    payload = {}
    for held, table in chosen_tables(store, names):
        text = table.frame.to_json(orient="records", date_format="iso", force_ascii=False)
        rows = json.loads(text)
        # pandas writes dates as 2026-04-01T00:00:00.000; a plain date reads better.
        for column in table.frame.columns:
            if pd.api.types.is_datetime64_any_dtype(table.frame[column]):
                for row in rows:
                    value = row.get(str(column))
                    if isinstance(value, str):
                        row[str(column)] = value.removesuffix("T00:00:00.000").removesuffix(".000")
        payload[held] = rows
    return json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")


def default_download_names(store: TransformStore) -> list[str]:
    """Pre-ticked in the Download box: the tables the steps made or changed, else all."""
    touched = {name_key(outcome.output_name) for outcome in store.outcomes if outcome.ok}
    names = [held for held in store.result if name_key(held) in touched]
    return names or list(store.result)


# ---------- recipes ----------


def recipe_dict(store: TransformStore, name: str = "") -> dict:
    pipeline = capture(
        name,
        upload_workspace=store.uploads,
        steps=store.steps,
        outputs=default_download_names(store),
    )
    payload = json.loads(to_json(pipeline))
    # A recipe file carries its own name (the Streamlit app kept it in a database column).
    return {"kind": RECIPE_KIND, "name": pipeline.display_name(), **payload}


def read_recipe(text: str) -> SavedPipeline:
    """Raises PipelineStorageError with a plain message."""
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise PipelineStorageError("This file is not a recipe (it isn't valid JSON).") from error
    if not isinstance(payload, dict) or "steps" not in payload:
        raise PipelineStorageError("This file is not a Transform Data recipe.")
    return from_json(text, name=str(payload.get("name", "")))


def missing_tables(store: TransformStore, pipeline: SavedPipeline) -> list[str]:
    """Tables the recipe's steps read that aren't loaded now."""
    loaded = {name_key(name) for name in store.uploads}
    return [table.name for table in pipeline.tables if name_key(table.name) not in loaded]
