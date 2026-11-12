"""Stand-ins for the Streamlit app's file loader, used to read back a built workbook."""

import io

import openpyxl
import pandas as pd


def list_sheet_names(payload: bytes, file_name: str) -> list[str]:
    return openpyxl.load_workbook(io.BytesIO(payload), read_only=True).sheetnames


def read_table(payload: bytes, file_name: str, sheet_name: str) -> pd.DataFrame:
    """Every cell as text, like the app's loader."""
    return pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, dtype=str)
