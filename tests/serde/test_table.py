"""
**File**:`test_table.py`
**Region**: `tests/serde`

Unit tests for the MsSqlTableSerializer to ensure it correctly handles NA values by converting them to None.

Covers:
- NA values in DataFrame are converted to None in the cleaned DataFrame.
- NA values in the row tuples are converted to None.
- Non-NA values are preserved in both the cleaned DataFrame and the row tuples.
"""

import numpy as np
import pandas as pd

from ds_provider_microsoft_py_lib.serde.table import MsSqlTableSerializer


def test_mssql_table_serializer_handles_na_values():
    """
    Verify that MsSqlTableSerializer correctly handles np.nan, pd.NA, and pd.NaT
    by converting them to None in a pandas DataFrame.
    """
    # Create a DataFrame with various NA types
    data = {
        "col1": [1, 2, np.nan],
        "col2": ["a", "b", pd.NA],
        "col3": [pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02"), pd.NaT],
    }
    df = pd.DataFrame(data)

    # Instantiate the serializer
    serializer = MsSqlTableSerializer()

    # Serialize the DataFrame
    cleaned_df, rows = serializer(df)

    # Check that NA values in the cleaned DataFrame are replaced with None
    assert cleaned_df.iloc[2, 0] is None
    assert cleaned_df.iloc[2, 1] is None
    assert cleaned_df.iloc[2, 2] is None

    # Check that NA values in the row tuples are replaced with None
    assert rows[2][0] is None
    assert rows[2][1] is None
    assert rows[2][2] is None

    # Check that non-NA values are preserved
    assert cleaned_df.iloc[0, 0] == 1
    assert rows[0][0] == 1


def test_clean_column_datetime_with_tz():
    """
    Test that _clean_column correctly handles datetime columns with timezones.
    """
    serializer = MsSqlTableSerializer()
    s = pd.Series(pd.to_datetime(["2024-01-01 12:00:00+01:00", "2024-01-02 12:00:00-05:00"], utc=True))
    cleaned_s = serializer._clean_column(s)
    expected_s = pd.Series(pd.to_datetime(["2024-01-01 11:00:00", "2024-01-02 17:00:00"]))
    pd.testing.assert_series_equal(cleaned_s, expected_s)


def test_clean_column_timedelta():
    """
    Test that _clean_column correctly handles timedelta columns.
    """
    serializer = MsSqlTableSerializer()
    s = pd.Series([pd.Timedelta("1 days"), pd.Timedelta("2 hours")])
    cleaned_s = serializer._clean_column(s)
    expected_s = pd.Series([86400.0, 7200.0])
    pd.testing.assert_series_equal(cleaned_s, expected_s)


def test_clean_column_complex():
    """
    Test that _clean_column correctly handles complex number columns.
    """
    serializer = MsSqlTableSerializer()
    s = pd.Series([1 + 2j, 3 - 4j])
    cleaned_s = serializer._clean_column(s)
    expected_s = pd.Series(["(1+2j)", "(3-4j)"])
    pd.testing.assert_series_equal(cleaned_s, expected_s)


def test_clean_column_no_change():
    """
    Test that _clean_column doesn't change columns that don't need cleaning.
    """
    serializer = MsSqlTableSerializer()
    s = pd.Series([1, 2, 3])
    cleaned_s = serializer._clean_column(s)
    pd.testing.assert_series_equal(s, cleaned_s)
