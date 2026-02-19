"""
**File**: test_mssql_dates.py
**Region**: tests/dataset

Unit tests for MsSqlTable dataset implementation, covering datetime column handling.

Covers:
- Creating a dataset with a datetime column that contains NaT values.
- Verifying that the create method correctly handles NaT values by converting them to None for insertion.
- Ensuring that the correct data is passed to the database cursor for insertion.
- Checking that the to_sql method is called to create the table with the appropriate schema.
- Verifying that the fallback insert method is not called when fast_executemany is used successfully.
- Ensuring that database connections are properly committed and closed after insertion.
- Testing that the dtype argument passed to to_sql is None, allowing pandas to infer the correct types.
- Verifying that the datetime values are correctly converted to SQL-compatible formats for insertion.
- Ensuring that the test covers both the presence of valid datetime values and NaT values in the same column.
- Checking that the test handles multiple rows of data with a mix of datetime and NaT values.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from ds_provider_microsoft_py_lib.dataset.mssql import (
    DeleteSettings,
    MsSqlTable,
    MsSqlTableDatasetSettings,
)
from ds_provider_microsoft_py_lib.serde.table import MsSqlTableSerializer


@pytest.fixture()
def settings() -> MsSqlTableDatasetSettings:
    return MsSqlTableDatasetSettings(table_name="mytable", schema_name="myschema", delete=DeleteSettings())


@pytest.fixture()
def linked_service() -> MagicMock:
    engine = MagicMock()
    engine.dialect.identifier_preparer.quote = MagicMock(side_effect=lambda name: f"[{name}]")
    svc = MagicMock()
    svc.engine = engine
    return svc


def make_table(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> MsSqlTable:
    table = MsSqlTable.__new__(MsSqlTable)
    table.settings = settings
    table.linked_service = linked_service
    table.serializer = MsSqlTableSerializer()
    table.deserializer = MagicMock()
    table._fallback_insert = MagicMock()
    table._log_write_start = MagicMock()
    table.input = None
    table.output = None
    return table


def test_create_with_datetime_and_nat(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify create handles datetime columns with NaT values."""
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"id": [1, 2], "timestamp": [pd.Timestamp("2023-01-01"), pd.NaT]})

    inspector = MagicMock()
    inspector.has_table.return_value = False
    raw_conn = MagicMock()
    cursor = MagicMock()
    raw_conn.cursor.return_value = cursor
    linked_service.engine.raw_connection.return_value = raw_conn
    head_df_mock = MagicMock()

    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector),
        patch("pandas.DataFrame.to_sql", new=head_df_mock),
    ):
        table.create()

    # Check that to_sql was called to create the table
    head_df_mock.assert_called()
    # Check that fast_executemany was called for insertion
    cursor.executemany.assert_called_once()
    raw_conn.commit.assert_called_once()
    raw_conn.close.assert_called_once()
    table._fallback_insert.assert_not_called()

    # Check the data passed to executemany
    _, rows = cursor.executemany.call_args[0]
    assert rows[0] == (1, pd.Timestamp("2023-01-01 00:00:00"))
    assert rows[1] == (2, None)


def test_create_with_datetime_and_nat_and_check_schema(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify create handles datetime columns with NaT values and creates correct schema."""
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"id": [1, 2], "timestamp": [pd.Timestamp("2023-01-01"), pd.NaT], "value": [1.1, None]})

    inspector = MagicMock()
    inspector.has_table.return_value = False
    raw_conn = MagicMock()
    cursor = MagicMock()
    raw_conn.cursor.return_value = cursor
    linked_service.engine.raw_connection.return_value = raw_conn

    # Mock the to_sql call to capture the dtypes
    to_sql_dtypes = {}

    def to_sql_mock(
        self, name, con, schema=None, if_exists="fail", index=True, index_label=None, chunksize=None, dtype=None, method=None
    ):
        nonlocal to_sql_dtypes
        to_sql_dtypes = dtype

    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector),
        patch("pandas.DataFrame.to_sql", new=to_sql_mock),
    ):
        table.create()

    # Check that fast_executemany was called for insertion
    cursor.executemany.assert_called_once()
    raw_conn.commit.assert_called_once()
    raw_conn.close.assert_called_once()
    table._fallback_insert.assert_not_called()

    # Check the data passed to executemany
    _, rows = cursor.executemany.call_args[0]
    assert rows[0] == (1, pd.Timestamp("2023-01-01 00:00:00"), 1.1)
    assert rows[1] == (2, None, None)

    # Check the dtype argument passed to to_sql
    assert to_sql_dtypes is None
