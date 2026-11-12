"""The whole flow through the pages: upload → steps → preview → download → recipe."""

import io
import json

import openpyxl
import pytest
from django.test import override_settings

from tests.conftest import csv_file, store_of

pytestmark = pytest.mark.django_db

CALC = {
    "operation": "add_calculated_column",
    "in_source": "sales",
    "p_new_column": "Profit",
    "p_expression": "[Sales] - [Cost]",
    "p_decimals": "",
    "output_mode": "in_place",
}
JOIN = {
    "operation": "merge",
    "in_left": "sales",
    "in_right": "customers",
    "p_left_on": ["Customer ID"],
    "p_join_type": "keep all rows from the left table",
    "output_mode": "new",
    "output_name": "sales with names",
}


def add(client, data):
    return client.post("/transform/step/save/", data)


def test_empty_page_invites_an_upload(client):
    page = client.get("/transform/").content.decode()
    assert "Start by uploading your data" in page


def test_upload_makes_tables_and_shows_them(loaded):
    store = store_of(loaded)
    assert list(store.result) == ["sales", "customers"]
    assert store.result["sales"].frame["Sales"].tolist()[:2] == [1200, 2500]  # "2,500" read
    page = loaded.get("/transform/?table=customers").content.decode()
    assert "Asha Traders" in page and "Your tables" in page


def test_a_bad_file_is_refused_with_its_name(client):
    response = client.post(
        "/transform/upload/", {"files": [csv_file("notes.txt", "x")]}, follow=True
    )
    assert "notes.txt: Only CSV, XLSX, XLSM, JSON and JSONL" in response.content.decode()


def test_add_a_calculated_column(loaded):
    response = add(loaded, CALC)
    assert response.status_code == 204
    assert response["HX-Redirect"].endswith("?table=sales")
    frame = store_of(loaded).result["sales"].frame
    assert frame["Profit"].tolist()[:3] == [400, 600, 50]


def test_a_failing_step_is_refused_and_the_form_says_why(loaded):
    response = add(loaded, {**CALC, "p_expression": "[Salse] - [Cost]"})
    page = response.content.decode()
    assert response.status_code == 200
    assert "Did you mean" in page and "[Sales]" in page
    assert store_of(loaded).steps == []


def test_join_then_group_then_undo(loaded):
    add(loaded, JOIN)
    response = add(
        loaded,
        {
            "operation": "groupby_aggregate",
            "in_source": "sales with names",
            "p_group_by": ["City"],
            "p_value_columns": ["Sales"],
            "p_aggregation": "sum",
            "output_mode": "new",
            "output_name": "by city",
        },
    )
    assert response.status_code == 204, response.content.decode()
    store = store_of(loaded)
    assert [o.output_name for o in store.outcomes] == ["sales with names", "by city"]
    assert "1 row(s) found no match" in store.outcomes[0].message
    loaded.post("/transform/step/undo/")
    assert len(store.steps) == 1 and "by city" not in store.result


def test_edit_the_last_step(loaded):
    add(loaded, CALC)
    form = loaded.get("/transform/step/form/?operation=add_calculated_column&edit=1")
    assert "[Sales] - [Cost]" in form.content.decode()
    add(loaded, {**CALC, "edit": "1", "p_expression": "[Sales] * 2"})
    store = store_of(loaded)
    assert len(store.steps) == 1
    assert store.result["sales"].frame["Profit"].iloc[0] == 2400


def test_form_redraw_lists_the_chosen_tables_columns(loaded):
    page = loaded.post(
        "/transform/step/form/", {**JOIN, "in_right": "sales", "p_left_on": []}
    ).content.decode()
    assert 'name="p_right_on" value="Invoice"' in page


def test_uploaded_table_used_by_a_step_cannot_be_removed(loaded):
    add(loaded, JOIN)
    response = loaded.post("/transform/table/remove/", {"name": "customers"}, follow=True)
    assert "Step 1 uses “customers”" in response.content.decode()
    assert "customers" in store_of(loaded).uploads


def test_formula_check_shows_examples_or_the_problem(loaded):
    good = loaded.post(
        "/transform/formula/check/", {"in_source": "sales", "p_expression": "[Sales] * 2"}
    )
    assert "Looks good" in good.content.decode()
    bad = loaded.post("/transform/formula/check/", {"in_source": "sales", "p_expression": "[Sales"})
    assert "closing bracket" in bad.content.decode()


def test_download_excel_has_each_table_and_the_steps(loaded):
    add(loaded, CALC)
    response = loaded.get("/transform/download/?format=xlsx&tables=sales&tables=customers")
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames[:2] == ["sales", "customers"]
    assert workbook["sales"]["G1"].value == "Profit"


def test_download_json(loaded):
    response = loaded.get("/transform/download/?format=json&tables=customers")
    data = json.loads(response.content)
    assert data["customers"][0] == {"Customer ID": "C1", "Name": "Asha Traders", "City": "Pune"}


def test_download_json_writes_plain_dates(loaded):
    data = json.loads(loaded.get("/transform/download/?format=json&tables=sales").content)
    assert data["sales"][0]["Date"] == "2026-04-01"


def test_download_with_nothing_ticked_says_so(loaded):
    response = loaded.get("/transform/download/?format=xlsx", follow=True)
    assert "Tick at least one table" in response.content.decode()


def test_recipe_round_trip(loaded, client):
    add(loaded, CALC)
    add(loaded, JOIN)
    recipe = loaded.post("/transform/recipe/save/", {"name": "Monthly"}).content
    assert b'"kind": "transform-data recipe"' in recipe

    loaded.post("/transform/start-over/")
    loaded.post(
        "/transform/upload/",
        {
            "files": [
                csv_file("sales.csv", "Invoice,Customer ID,Sales,Cost\nX,C2,10,4\n"),
                csv_file("customers.csv", "Customer ID,Name,City\nC2,Ravi,Chennai\n"),
            ]
        },
    )
    page = loaded.post(
        "/transform/recipe/load/",
        {"recipe": csv_file("Monthly.recipe.json", recipe.decode())},
        follow=True,
    ).content.decode()
    assert "Recipe “Monthly” applied: 2 step(s)" in page
    joined = store_of(loaded).result["sales with names"].frame
    assert joined[["Profit", "City"]].values.tolist() == [[6, "Chennai"]]


def test_recipe_with_a_missing_table_says_which(loaded):
    add(loaded, JOIN)
    recipe = loaded.post("/transform/recipe/save/", {"name": "J"}).content.decode()
    loaded.post("/transform/table/remove/", {"name": "customers"})  # refused: step uses it
    loaded.post("/transform/steps/clear/")
    loaded.post("/transform/table/remove/", {"name": "customers"})
    page = loaded.post(
        "/transform/recipe/load/", {"recipe": csv_file("J.json", recipe)}, follow=True
    ).content.decode()
    assert "expects tables called: customers" in page
    assert "step 1 stopped" in page


def test_not_a_recipe_is_refused(loaded):
    page = loaded.post(
        "/transform/recipe/load/", {"recipe": csv_file("x.json", "[1, 2]")}, follow=True
    ).content.decode()
    assert "not a Transform Data recipe" in page


def recipe_saved(request, recipe, name):
    recipe_saved.last = (recipe, name)
    return f"Saved as {name}"


def recipe_loaded(request, recipe_id):
    return recipe_saved.last[0]


@override_settings(
    TRANSFORM_DATA={
        "BASE_TEMPLATE": "base.html",
        "RECIPE_SAVE": "tests.test_views.recipe_saved",
        "RECIPE_LOAD": "tests.test_views.recipe_loaded",
    }
)
def test_host_hooks_store_and_open_recipes(loaded):
    add(loaded, CALC)
    page = loaded.post("/transform/recipe/save/", {"name": "Kept"}, follow=True).content.decode()
    assert "Saved as Kept" in page
    loaded.post("/transform/steps/clear/")
    confirm = loaded.get("/transform/recipe/open/?id=1").content.decode()
    assert "Open this recipe?" in confirm
    assert store_of(loaded).steps == []  # a GET alone changes nothing
    page = loaded.post("/transform/recipe/open/", {"id": "1"}, follow=True).content.decode()
    assert "applied: 1 step(s)" in page


def test_preview_shows_blanks_not_na(loaded):
    page = loaded.get("/transform/?table=sales").content.decode()
    assert "&lt;NA&gt;" not in page and "NaN" not in page


def test_preview_table_filters_through_datatable(loaded):
    response = loaded.get(
        "/transform/?table=customers&c2=Pune",
        headers={"HX-Request": "true", "HX-Target": "transform-preview"},
    )
    page = response.content.decode()
    assert "Asha Traders" in page and "Ravi Stores" not in page
    assert "<html" not in page  # only the table was redrawn


def test_start_over_clears_everything(loaded):
    loaded.post("/transform/start-over/")
    assert store_of(loaded) is None


def test_unknown_operation_is_a_bad_request(loaded):
    assert add(loaded, {"operation": "nope"}).status_code == 400


def test_after_a_failed_recipe_step_new_steps_say_what_to_fix(loaded):
    add(loaded, JOIN)
    recipe = loaded.post("/transform/recipe/save/", {"name": "J"}).content.decode()
    loaded.post("/transform/steps/clear/")
    loaded.post("/transform/table/remove/", {"name": "customers"})
    loaded.post("/transform/recipe/load/", {"recipe": csv_file("J.json", recipe)})
    page = add(loaded, CALC).content.decode()
    assert "Step 1 can&#x27;t run" in page


def test_download_name_keeps_non_english_letters(loaded):
    response = loaded.get("/transform/download/?format=json&tables=customers")
    assert response["Content-Disposition"] == 'attachment; filename="customers.json"'


def test_split_on_a_space(loaded):
    """A lone space is a real separator, not an empty box."""
    response = add(
        loaded,
        {
            "operation": "split_column",
            "in_source": "customers",
            "p_column": "Name",
            "p_separator": " ",
            "p_mode": "all pieces into new columns",
            "output_mode": "in_place",
        },
    )
    assert response.status_code == 204, response.content.decode()
    table = store_of(loaded).table("customers").frame
    assert table["Name_1"].tolist() == ["Asha", "Ravi", "Mehta"]
    assert table["Name_2"].tolist()[:2] == ["Traders", "Stores"]


HX = {"HTTP_HX_REQUEST": "true"}


def test_profile_shows_each_column_and_tips(loaded):
    page = loaded.get("/transform/table/profile/?table=sales", **HX).content.decode()
    assert "Profile of “sales”" in page
    assert "Customer ID" in page and "Region" in page
    assert "1 row(s) are exact copies" in page  # INV-3 is there twice
    assert "Number" in page  # Sales / Cost


def test_profile_table_redraws_alone_and_never_outside_the_popup(loaded):
    redraw = loaded.get(
        "/transform/table/profile/?table=sales&q=Reg",
        HTTP_HX_TARGET="transform-profile",
        **HX,
    ).content.decode()
    assert "Region" in redraw and "Profile of" not in redraw
    reload = loaded.get("/transform/table/profile/?table=sales")
    assert reload.status_code == 302 and "table=sales" in reload["Location"]


def test_profile_of_a_missing_table(loaded):
    page = loaded.get("/transform/table/profile/?table=nope", **HX).content.decode()
    assert "no longer there" in page
