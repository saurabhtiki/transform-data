"""Pages: one screen with 1 · Your tables, 2 · Steps, 3 · Preview, plus Download and
Recipe dialogs. Data lives in memory only (state.TransformStore), one store per session."""

import json
import logging
from urllib.parse import urlencode

import pandas as pd
from data_core import conf as core_conf
from data_core.formula import AGGREGATES, FUNCTIONS, FormulaError
from data_core.loading import UploadRejected, display_value
from data_core.store import MB, ServerBusy
from data_core.uploads import MemoryOnlyUploadHandler
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_POST
from django_datatable.datatable import CHOICE, DATE, NUMBER, TEXT, YES_NO, Column, RowsTable

from . import conf, downloads
from .engine.exceptions import PipelineStorageError, TransformError, TransformExportError
from .engine.ops_derive import formula_preview
from .engine.pipeline import step_headline
from .engine.registry import get_operation
from .engine.workspace import name_key
from .profile import table_profile as profile_of
from .state import StepRefused, TransformStore, registry
from .step_form import build_form, picker_groups, read_step

logger = logging.getLogger(__name__)

TABLE_ID = "transform-preview"
PROFILE_TABLE_ID = "transform-profile"


def _store(request, create: bool = False) -> TransformStore | None:
    store, expired = registry.for_request(request, create=create)
    if expired:
        messages.info(
            request,
            "Your earlier data was cleared because it was not used for a while. "
            "Nothing is kept on the server — please upload again.",
        )
    return store


def _home(table: str = "") -> HttpResponse:
    url = reverse("transform_data:home")
    return redirect(f"{url}?{urlencode({'table': table})}" if table else url)


def _hx_home(table: str = "") -> HttpResponse:
    """Tell htmx to load the home page (after a dialog's form succeeded)."""
    url = reverse("transform_data:home")
    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"{url}?{urlencode({'table': table})}" if table else url
    return response


# ---------- the page ----------


@require_GET
def home(request):
    store = _store(request)
    tables = store.result if store else {}
    selected = request.GET.get("table", "")
    current = store.table(selected) if store and selected else None
    if current is None and tables:  # the last step's answer, else the first table
        last_output = store.outcomes[-1].output_name if store.outcomes else ""
        current = store.table(last_output) or next(iter(tables.values()))
    context = {
        "base_template": conf.get("BASE_TEMPLATE"),
        "store": store,
        "tables": list(tables.values()),
        "current": current,
        "steps": _step_rows(store) if store else [],
        "last_operation": store.steps[-1]["operation"] if store and store.steps else "",
        "groups": picker_groups(),
        "download_names": downloads.default_download_names(store) if store else [],
        "recipe_hooks": bool(conf.get("RECIPE_SAVE")),
        "max_file_mb": core_conf.get("MAX_FILE_MB"),
        "max_files": core_conf.get("MAX_FILES_PER_UPLOAD"),
    }
    if current is not None:
        table = _preview_table(request, current)
        context.update(table=table, preview_rows=conf.get("PREVIEW_ROWS"))
        if table.wants_csv:
            return table.csv_response()
        if request.headers.get("HX-Target") == TABLE_ID:
            return render(request, "transform_data/partials/preview_table.html", context)
    return render(request, "transform_data/home.html", context)


def _step_rows(store: TransformStore) -> list[dict]:
    rows = []
    for index, step in enumerate(store.steps):
        outcome = store.outcomes[index] if index < len(store.outcomes) else None
        rows.append(
            {
                "number": index + 1,
                "headline": step_headline(step, index).split(". ", 1)[-1],
                "status": outcome.status if outcome else "not run",
                "message": outcome.message if outcome else "Not run: an earlier step stopped.",
                "output": step["output"]["name"],
                "last": index == len(store.steps) - 1,
                "rows": outcome.rows_after if outcome and outcome.ok else None,
            }
        )
    return rows


def _preview_table(request, current) -> RowsTable:
    """The table on screen, through django-datatable (filter, sort, pages, CSV)."""
    frame = current.frame.head(conf.get("PREVIEW_ROWS"))
    keys = [f"c{index}" for index in range(len(frame.columns))]
    columns = []
    for key, name in zip(keys, frame.columns, strict=True):
        series = frame[name]
        kind = series.dtype.kind
        if kind == "b":
            columns.append(Column(key, str(name), type=CHOICE, choices=YES_NO))
        elif kind in "iuf":
            columns.append(Column(key, str(name), type=NUMBER))
        elif kind == "M" and not _has_time(series):
            columns.append(Column(key, str(name), type=DATE))
        else:  # text, and dates with a time (shown as text: dd-mm-yyyy hh:mm)
            columns.append(Column(key, str(name), type=TEXT))
    timed = {
        key
        for key, name in zip(keys, frame.columns, strict=True)
        if frame[name].dtype.kind == "M" and _has_time(frame[name])
    }
    rows = [
        {
            key: display_value(_plain(value)) if key in timed else _plain(value)
            for key, value in zip(keys, record, strict=True)
        }
        for record in frame.itertuples(index=False, name=None)
    ]
    return RowsTable(
        request.GET,
        rows,
        columns,
        table_id=TABLE_ID,
        base_url=request.path,
        keep=("table",),
        default_sort=(),
        search_fields=tuple(keys),
        search_placeholder="Search this table",
        noun="rows",
        sticky_header=True,
    )


def _has_time(series) -> bool:
    filled = series.dropna()
    return bool(len(filled)) and bool((filled != filled.dt.normalize()).any())


def _plain(value):
    """A pandas cell as a plain Python value (blank for NaN / NaT / <NA>)."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    if hasattr(value, "to_pydatetime"):
        moment = value.to_pydatetime()
        return moment if moment.hour or moment.minute or moment.second else moment.date()
    if hasattr(value, "item"):  # numpy number / bool
        return value.item()
    return value


# ---------- table profile (popup) ----------


@require_GET
def table_profile(request):
    """What each column of a table holds: type, blanks, distinct values, range, examples."""
    store = _store(request)
    name = request.GET.get("table", "")
    current = store.table(name) if store and name else None
    if not request.headers.get("HX-Request"):  # opened outside the popup, e.g. a reload
        return _home(name)
    if current is None:
        logger.info("Profile asked for a missing table: %s", name)
        return render(request, "transform_data/partials/profile.html", {"missing": name})
    profile = profile_of(current.frame)
    rows = [
        {**row, "smallest": _plain(row["smallest"]), "largest": _plain(row["largest"])}
        for row in profile.rows
    ]
    columns = [
        Column("column", "Column", type=TEXT),
        Column("type", "Looks like", type=CHOICE, choices=_choices(rows, "type")),
        Column("filled", "Filled", type=NUMBER),
        Column("blank", "Blank", type=NUMBER),
        Column("blank_pct", "Blank %", type=NUMBER),
        Column("distinct", "Distinct", type=NUMBER),
        Column("smallest", "Smallest", type=TEXT, sortable=False, filterable=False),
        Column("largest", "Largest", type=TEXT, sortable=False, filterable=False),
        Column("examples", "Examples", type=TEXT, sortable=False),
    ]
    table = RowsTable(
        request.GET,
        rows,
        columns,
        table_id=PROFILE_TABLE_ID,
        base_url=request.path,
        keep=("table",),
        default_sort=(),
        search_fields=("column", "examples"),
        search_placeholder="Find a column",
        noun="columns",
        push_url=False,
        default_per_page=50,
    )
    context = {"current": current, "profile": profile, "table": table}
    if table.wants_csv:
        return table.csv_response()
    if request.headers.get("HX-Target") == PROFILE_TABLE_ID:
        return render(request, "transform_data/partials/profile_table.html", context)
    return render(request, "transform_data/partials/profile.html", context)


def _choices(rows: list[dict], key: str) -> dict[str, str]:
    """The tick-list options for a column: each value it holds, as itself."""
    return {value: value for value in sorted({row[key] for row in rows})}


# ---------- uploads ----------


@csrf_exempt  # CSRF is checked in _receive_upload, after the memory-only handler is set
@require_POST
def upload(request):
    try:
        registry.check_capacity()
    except ServerBusy as error:
        messages.error(request, str(error))
        return _home()
    handler = MemoryOnlyUploadHandler(
        request,
        max_file_bytes=core_conf.get("MAX_FILE_MB") * MB,
        max_files=core_conf.get("MAX_FILES_PER_UPLOAD"),
    )
    request.upload_handlers = [handler]
    return _receive_upload(request, handler)


@csrf_protect
def _receive_upload(request, handler):
    files = request.FILES.getlist("files")
    store = _store(request, create=True)
    for file_name in handler.too_big:
        logger.info("Upload refused, over size limit: %s", file_name)
        messages.error(
            request, f"{file_name}: larger than the {core_conf.get('MAX_FILE_MB')} MB limit."
        )
    if handler.too_many:
        logger.info("Upload refused, too many files: %s", handler.too_many)
        messages.error(
            request,
            f"Only {core_conf.get('MAX_FILES_PER_UPLOAD')} files at once. Upload these again: "
            + ", ".join(handler.too_many),
        )
    if not files and not handler.too_big and not handler.too_many:
        logger.info("Upload refused: no files")
        messages.error(request, "Choose at least one CSV, Excel or JSON file.")
    last = ""
    for uploaded in files:
        try:
            names = store.add_upload(uploaded.name, uploaded.file)
        except UploadRejected as error:
            logger.info("Upload rejected: %s: %s", uploaded.name, error)
            messages.error(request, f"{uploaded.name}: {error}")
            continue
        finally:
            uploaded.close()  # free the file's memory before reading the next one
        last = names[-1]
        rows = sum(len(store.uploads[name].frame) for name in names)
        row_word = "row" if rows == 1 else "rows"
        messages.success(
            request, f"{uploaded.name}: loaded as {', '.join(names)} ({rows:,} {row_word})."
        )
    return _home(last)


@require_POST
def remove_table(request):
    store = _store(request)
    name = request.POST.get("name", "")
    if store is not None:
        try:
            store.remove_upload(name)
            messages.success(request, f"Removed “{name}”.")
        except StepRefused as error:  # logged where it is raised
            messages.error(request, str(error))
    return _home()


@require_POST
def start_over(request):
    registry.clear(request)
    messages.success(request, "Everything was cleared. Upload a file to start again.")
    return _home()


# ---------- steps ----------


@require_GET
def step_picker(request):
    """Dialog body: choose what kind of step to add."""
    return render(
        request,
        "transform_data/partials/step_picker.html",
        {"groups": picker_groups(), "table": request.GET.get("table", "")},
    )


def _form_tables(store: TransformStore, editing: bool):
    return store.tables_before_last() if editing else store.result


def step_form(request):
    """Dialog body: the form for one operation. GET = fresh form; POST = redraw with what
    the user filled in (after picking another table or option)."""
    store = _store(request)
    data = request.POST if request.method == "POST" else request.GET
    operation = data.get("operation", "")
    editing = data.get("edit") == "1"
    if store is None or not store.result:
        return HttpResponseBadRequest("Upload a file first.")
    try:
        get_operation(operation)
    except TransformError:
        return HttpResponseBadRequest("Unknown step.")
    existing = store.steps[-1] if editing and store.steps else None
    tables = _form_tables(store, editing and existing is not None)
    form = build_form(
        operation,
        tables,
        data=request.POST if request.method == "POST" else None,
        existing=existing if request.method == "GET" else None,
        preferred_table=data.get("table", ""),
    )
    form.editing = existing is not None
    return render(request, "transform_data/partials/step_form.html", _form_context(form))


def _form_context(form, error: str = "") -> dict:
    return {
        "form": form,
        "error": error,
        "functions": [
            (name, help_text) for name, help_text in FUNCTIONS.items() if name not in AGGREGATES
        ],
    }


@require_POST
def step_save(request):
    """Add the step (or replace the last one). On a problem, redraw the form with it."""
    store = _store(request)
    if store is None:
        return _hx_home()
    operation = request.POST.get("operation", "")
    try:
        get_operation(operation)
    except TransformError:
        logger.info("Step save refused: unknown operation %r", operation)
        return HttpResponseBadRequest("Unknown step.")
    editing = request.POST.get("edit") == "1" and bool(store.steps)
    tables = _form_tables(store, editing)
    try:
        step = read_step(operation, request.POST, tables)
        outcome = store.replace_last(step, tables) if editing else store.add_step(step)
    except (TransformError, StepRefused) as error:
        logger.info("Step not added: %s", error)
        form = build_form(operation, tables, data=request.POST)
        form.editing = editing
        return render(
            request, "transform_data/partials/step_form.html", _form_context(form, str(error))
        )
    verb = "Changed" if editing else "Added"
    note = f" Note: {outcome.message}" if outcome.message else ""
    messages.success(request, f"{verb} step {len(store.steps)}: {outcome.label}.{note}")
    return _hx_home(outcome.output_name)


@require_POST
def step_undo(request):
    store = _store(request)
    if store is not None and store.steps:
        store.undo_last()
        messages.success(request, "The last step was removed.")
    return _home()


@require_POST
def steps_clear(request):
    store = _store(request)
    if store is not None:
        store.clear_steps()
        messages.success(request, "All steps were removed. Your uploaded tables are unchanged.")
    return _home()


@require_POST
def formula_check(request):
    """Live ✓ / ✗ under the formula box, with example answers from the first rows."""
    store = _store(request)
    formula = request.POST.get("p_expression", "")
    table_name = request.POST.get("in_source", "")
    editing = request.POST.get("edit") == "1"
    context = {"formula": formula}
    if not formula.strip():
        return render(request, "transform_data/partials/formula_check.html", context)
    tables = _form_tables(store, editing and bool(store.steps)) if store else {}
    held = next((t for n, t in tables.items() if name_key(n) == name_key(table_name)), None)
    if held is None:
        context["error"] = "Choose a table first."
    else:
        try:
            kind, examples = formula_preview(held.frame, formula)
            context.update(ok=True, kind=kind, examples=examples)
        except FormulaError as error:
            context["error"] = str(error)
    return render(request, "transform_data/partials/formula_check.html", context)


# ---------- downloads ----------


@require_GET
def download(request):
    store = _store(request)
    if store is None or not store.result:
        logger.info("Download refused: no tables")
        messages.error(request, "There is nothing to download yet. Upload a file first.")
        return _home()
    names = request.GET.getlist("tables")
    file_format = request.GET.get("format", "xlsx")
    try:
        if file_format == "json":
            payload = downloads.json_bytes(store, names)
            content_type, suffix = "application/json", "json"
        else:
            payload = downloads.excel_bytes(store, names)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            suffix = "xlsx"
    except TransformExportError as error:
        logger.info("Download refused: %s", error)
        messages.error(request, str(error))
        return _home()
    file_name = (names[0] if len(names) == 1 else "transformed data").replace('"', "")
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(True, f"{file_name}.{suffix}")
    logger.info("Download: %s table(s) as %s", len(names), suffix)
    return response


# ---------- recipes ----------


@require_POST
def recipe_save(request):
    """Download the recipe as a .json file, or hand it to the host's RECIPE_SAVE hook."""
    store = _store(request)
    if store is None or not store.steps:
        logger.info("Recipe save refused: no steps")
        messages.error(request, "Add at least one step before saving a recipe.")
        return _home()
    name = request.POST.get("name", "").strip() or "recipe"
    recipe = downloads.recipe_dict(store, name)
    hook = conf.get("RECIPE_SAVE")
    if hook:
        try:
            message = import_string(hook)(request, recipe, name)
        except Exception as error:  # the host's own code: show its message, keep the page
            logger.exception("RECIPE_SAVE hook failed")
            messages.error(request, f"The recipe could not be saved ({error}).")
        else:
            messages.success(request, message or f"Saved recipe “{name}”.")
        return _home()
    response = HttpResponse(
        json.dumps(recipe, ensure_ascii=False, indent=2), content_type="application/json"
    )
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_") or "recipe"
    response["Content-Disposition"] = content_disposition_header(True, f"{safe}.recipe.json")
    return response


@require_POST
def recipe_load(request):
    store = _store(request)
    uploaded = request.FILES.get("recipe")
    if store is None or not store.uploads:
        logger.info("Recipe load refused: no tables")
        messages.error(request, "Upload your data files first, then load the recipe.")
        return _home()
    if uploaded is None:
        logger.info("Recipe load refused: no file")
        messages.error(request, "Choose a recipe file (.json).")
        return _home()
    if uploaded.size > conf.get("RECIPE_MAX_KB") * 1024:
        logger.info("Recipe load refused: %s bytes", uploaded.size)
        messages.error(request, f"A recipe file must be under {conf.get('RECIPE_MAX_KB')} KB.")
        return _home()
    try:
        text = uploaded.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        logger.info("Recipe load refused: not UTF-8")
        messages.error(request, "This recipe file is not UTF-8 text.")
        return _home()
    return _apply_recipe(request, store, text)


def recipe_open(request):
    """Open a recipe the host stored (RECIPE_LOAD hook), e.g. /transform/recipe/open/?id=7.
    GET asks first (a link alone must never replace the user's steps); POST applies it."""
    hook = conf.get("RECIPE_LOAD")
    store = _store(request)
    if not hook:
        return HttpResponseBadRequest("Recipes are not stored by this site.")
    if request.method != "POST":
        return render(
            request,
            "transform_data/recipe_open.html",
            {
                "base_template": conf.get("BASE_TEMPLATE"),
                "recipe_id": request.GET.get("id", ""),
                "has_steps": bool(store and store.steps),
            },
        )
    if store is None or not store.uploads:
        logger.info("Recipe open refused: no tables")
        messages.error(request, "Upload your data files first, then open the recipe.")
        return _home()
    try:
        recipe = import_string(hook)(request, request.POST.get("id", ""))
    except Exception as error:  # the host's own code
        logger.exception("RECIPE_LOAD hook failed")
        messages.error(request, f"The recipe could not be opened ({error}).")
        return _home()
    return _apply_recipe(request, store, json.dumps(recipe))


def _apply_recipe(request, store: TransformStore, text: str):
    try:
        pipeline = downloads.read_recipe(text)
    except PipelineStorageError as error:
        logger.info("Recipe refused: %s", error)
        messages.error(request, str(error))
        return _home()
    missing = downloads.missing_tables(store, pipeline)
    try:
        store.load_steps(pipeline.steps)
    except TransformError as error:
        logger.info("Recipe could not run: %s", error)
        messages.error(request, f"This recipe can't be used: {error}")
        store.clear_steps()
        return _home()
    if missing:
        messages.warning(
            request,
            "This recipe expects tables called: "
            + ", ".join(missing)
            + ". Upload them (with the same names) so every step can run.",
        )
    failed = store.failed
    if failed is not None:
        messages.error(
            request, f"Recipe loaded, but step {failed.index + 1} stopped: {failed.message}"
        )
    else:
        messages.success(
            request, f"Recipe “{pipeline.display_name()}” applied: {len(store.steps)} step(s)."
        )
    last = store.outcomes[-1].output_name if store.outcomes else ""
    return _home(last)
