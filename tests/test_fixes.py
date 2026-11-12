"""The prototype bugs fixed while porting (see docs/plan.md, Phase 1)."""

import json

import pandas as pd
import pytest

from transform_data.engine.exceptions import InvalidStepParamsError
from transform_data.engine.ops_aggregate import apply_pivot
from transform_data.engine.ops_combine import apply_concat, apply_lookup, apply_merge
from transform_data.engine.ops_common import to_numeric
from transform_data.engine.pipeline import to_json


def test_rupee_amounts_read_as_numbers_everywhere():
    numbers, problems = to_numeric(pd.Series(["₹1,200", "(300)", "50-"]), "Amount")
    assert numbers.tolist() == [1200.0, -300.0, -50.0]
    assert problems == []


def test_join_counts_unmatched_rows_even_when_names_clash():
    left = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "b", "c"]})
    right = pd.DataFrame({"id": ["1"], "name": ["x"]})  # "name" is in both tables
    _, warnings = apply_merge({"left": left, "right": right}, {"left_on": ["id"]})
    assert "2 row(s) found no match" in " ".join(warnings)


def test_full_join_counts_both_sides():
    left = pd.DataFrame({"id": ["1", "2"]})
    right = pd.DataFrame({"id": ["2", "3"], "v": [1, 2]})
    _, warnings = apply_merge(
        {"left": left, "right": right},
        {"left_on": ["id"], "join_type": "keep all rows from both"},
    )
    assert "2 row(s) found no match" in " ".join(warnings)


def test_lookup_with_the_key_ticked_does_not_repeat_it():
    source = pd.DataFrame({"code": ["A", "B"]})
    other = pd.DataFrame({"code": ["A"], "price": [5]})
    result, warnings = apply_lookup(
        {"source": source, "lookup_table": other},
        {"source_key": "code", "bring_columns": ["code", "price"]},
    )
    assert list(result.columns) == ["code", "price"]
    assert "1 row(s) had no matching" in " ".join(warnings)


def test_append_never_overwrites_a_real_source_table_column():
    one = pd.DataFrame({"a": [1], "source table": ["mine"]})
    two = pd.DataFrame({"a": [2], "source table": ["also"]})
    result, _ = apply_concat(
        {"frames": [one, two]}, {"add_source_column": True, "_frame_names": ["one", "two"]}
    )
    assert result["source table"].tolist() == ["mine", "also"]
    assert result["source table (2)"].tolist() == ["one", "two"]


def test_pivot_never_makes_two_columns_with_one_name():
    frame = pd.DataFrame({"Region": ["N", "S"], "Kind": ["Region", "Other"], "Amount": [1, 2]})
    result, _ = apply_pivot(
        {"source": frame},
        {"row_columns": ["Region"], "column_column": "Kind", "value_column": "Amount"},
    )
    assert len(set(result.columns)) == len(result.columns)
    assert "Region (2)" in result.columns


def test_recipe_json_refuses_values_it_cannot_keep():
    step = {
        "operation": "x",
        "inputs": {},
        "params": {"when": pd.Timestamp("2026-01-01")},
        "output": {"mode": "new", "name": "t"},
    }
    with pytest.raises(InvalidStepParamsError):
        to_json([step])
    assert json.loads(to_json([{**step, "params": {}}]))["steps"][0]["params"] == {}
