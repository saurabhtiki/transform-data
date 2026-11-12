import pandas as pd

from transform_data.profile import table_profile


def test_types_blanks_range_and_tips():
    frame = pd.DataFrame(
        {
            "amount": ["1,200", "300", "300"],
            "qty": [1, 5, 5],
            "when": pd.to_datetime(["2026-01-02", "2026-03-04", "2026-03-04"]),
            "empty": ["  ", None, None],
        }
    )
    profile = table_profile(frame)
    rows = {row["column"]: row for row in profile.rows}
    assert rows["amount"]["stored_as_text"] and rows["amount"]["type"] == "Number"
    assert (rows["qty"]["smallest"], rows["qty"]["largest"]) == (1, 5)
    assert rows["when"]["type"] == "Date" and not rows["when"]["stored_as_text"]
    assert rows["when"]["examples"] == "02-01-2026, 04-03-2026"
    assert rows["empty"]["blank"] == 3 and rows["empty"]["blank_pct"] == 100.0
    assert rows["amount"]["distinct"] == 2 and rows["amount"]["examples"] == "1,200, 300"
    assert profile.duplicate_rows == 1 and profile.blank_cells == 3
    tips = " ".join(profile.tips)
    assert "“amount” looks like numbers" in tips
    assert "“empty” is empty in every row" in tips
    assert "1 row(s) are exact copies" in tips


def test_an_empty_table():
    profile = table_profile(pd.DataFrame({"a": []}))
    assert profile.row_count == 0 and profile.rows[0]["blank_pct"] == 0.0
