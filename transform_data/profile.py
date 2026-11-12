"""A quick health check of one table: what each column holds, and what may need fixing.

profile = table_profile(frame)
profile.rows        # one dict per column: type, filled, blank, distinct, smallest, largest
profile.tips        # plain advice, e.g. "Sales looks like numbers but is stored as text"
"""

from dataclasses import dataclass, field

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from .engine.cleaner.profiling import (
    CATEGORICAL,
    DATE,
    ID,
    NUMERIC,
    TEXT,
    blank_mask,
    effective_column_type,
)

# Guessing a type reads every value (dates are slow), so look at the first rows only.
TYPE_SAMPLE_ROWS = 10_000
EXAMPLES = 3

TYPE_LABELS = {
    NUMERIC: "Number",
    DATE: "Date",
    TEXT: "Text",
    CATEGORICAL: "Category",
    ID: "ID / code",
}


@dataclass
class TableProfile:
    row_count: int
    column_count: int
    blank_cells: int
    duplicate_rows: int
    rows: list[dict] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


def table_profile(frame: pd.DataFrame) -> TableProfile:
    row_count = len(frame)
    rows, tips = [], []
    blank_cells = 0
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        blanks = blank_mask(series)
        blank = int(blanks.sum())
        blank_cells += blank
        filled = series[~blanks]
        guessed = effective_column_type(series.head(TYPE_SAMPLE_ROWS))
        stored_as_text = guessed in (NUMERIC, DATE) and not (
            is_numeric_dtype(series) or is_datetime64_any_dtype(series)
        )
        smallest, largest = _range(filled)
        rows.append(
            {
                "column": str(name),
                "type": TYPE_LABELS.get(guessed, "Text"),
                "stored_as_text": stored_as_text,
                "filled": row_count - blank,
                "blank": blank,
                "blank_pct": round(blank / row_count * 100, 1) if row_count else 0.0,
                "distinct": int(filled.nunique()),
                "smallest": smallest,
                "largest": largest,
                "examples": ", ".join(_examples(filled)),
            }
        )
        if row_count and blank == row_count:
            tips.append(f"“{name}” is empty in every row. Use “Remove columns” to drop it.")
        elif stored_as_text:
            kind = "numbers" if guessed == NUMERIC else "dates"
            tips.append(
                f"“{name}” looks like {kind} but is stored as text. Use “Change column type” "
                f"so you can add, sort or group it properly."
            )
    duplicate_rows = int(frame.duplicated().sum()) if row_count else 0
    if duplicate_rows:
        tips.append(
            f"{duplicate_rows:,} row(s) are exact copies of another row. "
            "Use “Remove duplicates” if they shouldn't be there."
        )
    return TableProfile(
        row_count=row_count,
        column_count=len(frame.columns),
        blank_cells=blank_cells,
        duplicate_rows=duplicate_rows,
        rows=rows,
        tips=tips,
    )


def _examples(filled: pd.Series) -> list[str]:
    """The first few different values, dates written dd-mm-yyyy like the rest of the page."""
    first = filled.drop_duplicates().head(EXAMPLES)
    if is_datetime64_any_dtype(first):
        timed = (first != first.dt.normalize()).any()
        return first.dt.strftime("%d-%m-%Y %H:%M" if timed else "%d-%m-%Y").tolist()
    return first.astype("string").tolist()


def _range(filled: pd.Series):
    """(smallest, largest) for number and date columns; (None, None) for text.
    Raw pandas values: the page turns them into plain ones."""
    if filled.empty or not (is_numeric_dtype(filled) or is_datetime64_any_dtype(filled)):
        return None, None
    if filled.dtype.kind == "b":
        return None, None
    return filled.min(), filled.max()
