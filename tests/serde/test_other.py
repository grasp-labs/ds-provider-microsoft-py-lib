"""
**File**:`test_other.py`
**Region**: `tests/serde`

Unit tests for the MsSqlTableSerializer to ensure it correctly handles various data types.
"""

import numpy as np
import pandas as pd

from ds_provider_microsoft_py_lib.serde.table import MsSqlTableSerializer


def test_mssql_table_serializer_handles_different_types():
    """
    Verify that MsSqlTableSerializer correctly handles various data types.
    """
    data = {
        "int_col": [1, 2, 3],
        "float_col": [1.1, 2.2, 3.3],
        "str_col": ["a", "b", "c"],
        "bool_col": [True, False, True],
        "datetime_col": [pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02"), pd.NaT],
    }
    df = pd.DataFrame(data)

    serializer = MsSqlTableSerializer()
    cleaned_df, rows = serializer(df)

    expected_rows = [
        (1, 1.1, "a", True, pd.Timestamp("2023-01-01")),
        (2, 2.2, "b", False, pd.Timestamp("2023-01-02")),
        (3, 3.3, "c", True, None),
    ]

    assert cleaned_df["datetime_col"].iloc[2] is None
    assert rows == expected_rows


def test_mssql_table_serializer_empty_dataframe():
    """
    Verify that MsSqlTableSerializer correctly handles an empty DataFrame.
    """
    df = pd.DataFrame({"col1": []})

    serializer = MsSqlTableSerializer()
    cleaned_df, rows = serializer(df)

    assert cleaned_df.empty
    assert rows == []


def test_mssql_table_serializer_all_na_dataframe():
    """
    Verify that MsSqlTableSerializer correctly handles a DataFrame with all NA values.
    """
    data = {
        "col1": [np.nan, pd.NA],
        "col2": [pd.NaT, np.nan],
    }
    df = pd.DataFrame(data)

    serializer = MsSqlTableSerializer()
    cleaned_df, rows = serializer(df)

    assert cleaned_df.iloc[0, 0] is None
    assert cleaned_df.iloc[0, 1] is None
    assert cleaned_df.iloc[1, 0] is None
    assert cleaned_df.iloc[1, 1] is None

    assert rows == [(None, None), (None, None)]
