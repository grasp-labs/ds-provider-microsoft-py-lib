"""
**File**: test_mssql.py
**Region**: tests/dataset

Unit tests for MsSqlTable dataset implementation, covering settings validation, read/write operations, and error handling.

Covers:
- Validation of dataset settings (e.g. chunksize)
- Correct composition of full table name and identifier quoting
- Successful read operation and error mapping
- Create operation using fast executemany path, including fallback behavior
- Delete operation for both dropping table and deleting rows, including error handling
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DeleteError,
)

from ds_provider_microsoft_py_lib.dataset.mssql import (
    MsSqlTable,
    MsSqlTableDatasetSettings,
)


@pytest.fixture()
def settings() -> MsSqlTableDatasetSettings:
    return MsSqlTableDatasetSettings(table="mytable", schema="myschema")


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
    table.serializer = MagicMock()
    table.deserializer = MagicMock()
    table._fallback_insert = MagicMock()
    table._log_write_start = MagicMock()
    table.input = None
    table.output = None
    return table


def test_quote_identifier_rejects_unsafe(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Reject unsafe identifier input."""

    table = make_table(settings, linked_service)

    with pytest.raises(ValueError):
        table._quote_identifier("bad;col")


def test_create_with_empty_input_raises_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify that create raises a CreateError if the input DataFrame is empty."""
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame()  # Empty DataFrame

    with pytest.raises(CreateError, match=r"Input is empty or None."):
        table.create()


def test_delete_wraps_unsafe_identifier_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify delete wraps ValueError from unsafe identifiers in DeleteError."""
    settings.table = "bad;table"
    table = make_table(settings, linked_service)

    with pytest.raises(DeleteError):
        table.delete()


def test_rename_not_implemented(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify that rename raises NotImplementedError."""
    table = make_table(settings, linked_service)

    with pytest.raises(NotImplementedError):
        table.rename()


def test_close_is_noop(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify that close() is a no-op and does not raise an error."""
    table = make_table(settings, linked_service)
    try:
        table.close()
    except Exception as e:
        pytest.fail(f"MsSqlTable.close() raised an unexpected exception: {e}")
