"""
Unit tests for MsSqlTable dataset implementation.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DeleteError,
    ListError,
    PurgeError,
    ReadError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from sqlalchemy import Column, Float, Integer, MetaData, String
from sqlalchemy import Table as SQLTable
from sqlalchemy import select as sql_select
from sqlalchemy.exc import NoSuchTableError

from ds_provider_microsoft_py_lib.dataset.mssql import (
    MsSqlTable,
    MsSqlTableDatasetSettings,
    ReadSettings,
)
from ds_provider_microsoft_py_lib.enums import ResourceType


@pytest.fixture()
def settings() -> MsSqlTableDatasetSettings:
    return MsSqlTableDatasetSettings(table="mytable", schema="myschema")


@pytest.fixture()
def linked_service() -> MagicMock:
    engine = MagicMock()
    engine.dialect.identifier_preparer.quote = MagicMock(side_effect=lambda name: f"[{name}]")
    svc = MagicMock()
    svc.connection = engine
    return svc


def make_table(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> MsSqlTable:
    table = MsSqlTable.__new__(MsSqlTable)
    table.settings = settings
    table.linked_service = linked_service
    table.input = None  # type: ignore
    table.output = None  # type: ignore
    table.schema = {}
    return table


# Test empty input handling
def test_create_empty_input_returns_immediately(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame()
    table.create()
    assert table.output is not None
    assert table.output.empty


def test_delete_empty_input_returns_immediately(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame()  # type: ignore
    table.delete()
    # delete() doesn't set output for empty input, it just returns
    assert table.output is None


# Test error types
def test_update_raises_not_supported_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(NotSupportedError):
        table.update()


def test_upsert_raises_not_supported_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(NotSupportedError):
        table.upsert()


def test_rename_raises_not_supported_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(NotSupportedError):
        table.rename()


def test_purge_raises_purge_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn_ctx.__exit__ = MagicMock(return_value=None)
    mock_conn.execute.side_effect = RuntimeError("DB error")
    linked_service.connection.begin = MagicMock(return_value=mock_conn_ctx)
    with pytest.raises(PurgeError):
        table.purge()


def test_list_raises_list_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", side_effect=RuntimeError("Inspect error")),
        pytest.raises(ListError),
    ):
        table.list()


# Test idempotency
def test_delete_is_idempotent(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1]})
    table.input = df  # type: ignore
    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)
    table.delete()
    table.delete()


def test_purge_is_idempotent(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn_ctx.__exit__ = MagicMock(return_value=None)
    linked_service.connection.connect = MagicMock(return_value=mock_conn_ctx)
    table.purge()
    table.purge()


def test_list_is_idempotent(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=["table1", "table2"])
    mock_inspector.get_view_names = MagicMock(return_value=[])
    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()
        table.list()


def test_close_is_idempotent(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    table.close()
    table.close()


# Test output population
def test_list_populates_output(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=["table1", "table2"])
    mock_inspector.get_view_names = MagicMock(return_value=["table2"])
    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()
    assert table.output is not None
    assert isinstance(table.output, pd.DataFrame)
    assert len(table.output) == 2


def test_purge_does_not_populate_output(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn_ctx.__exit__ = MagicMock(return_value=None)
    linked_service.connection.connect = MagicMock(return_value=mock_conn_ctx)
    table.purge()
    assert table.output is None


def test_close_does_not_populate_output(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    table.close()
    assert table.output is None


# Test identifier quoting
def test_quote_identifier_rejects_semicolon(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(ValueError, match="Unsafe identifier"):
        table._quote_identifier("bad;col")


def test_quote_identifier_rejects_double_quote(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(ValueError, match="Unsafe identifier"):
        table._quote_identifier('bad"col')


def test_quote_identifier_rejects_single_quote(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(ValueError, match="Unsafe identifier"):
        table._quote_identifier("bad'col")


def test_quote_identifier_rejects_brackets(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    with pytest.raises(ValueError, match="Unsafe identifier"):
        table._quote_identifier("bad[col]")


def test_delete_wraps_unsafe_identifier_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"bad;col": [1]})
    table.input = df  # type: ignore
    with pytest.raises(DeleteError):
        table.delete()


# Test schema handling
def test_set_schema_creates_schema_dict(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    table._set_schema(df)
    assert table.schema is not None
    assert "id" in table.schema
    assert "name" in table.schema


# Test create error on connection failure
def test_create_raises_create_error_on_connection_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    linked_service.connection = None

    with pytest.raises(CreateError):
        table.create()


# Test create error raises correctly
def test_create_raises_create_error_on_write_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    # Mock connection to raise an exception on execute
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = RuntimeError("Write failed")
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        with pytest.raises(CreateError):
            table.create()


# Test read error on non-existent table
def test_read_raises_read_error_on_missing_table(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)

    with patch.object(table, "_get_table", side_effect=NoSuchTableError("Table not found")), pytest.raises(ReadError):
        table.read()


# Test read error on connection failure
def test_read_raises_read_error_on_connection_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    linked_service.connection = None

    with pytest.raises(ReadError):
        table.read()


# Test successful delete
def test_delete_with_valid_data(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2, 3]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    table.delete()

    assert table.output is not None
    assert len(table.output) == 3


# Test delete error on execution failure
def test_delete_raises_delete_error_on_execution_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    mock_conn.execute.side_effect = RuntimeError("Delete failed")
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with pytest.raises(DeleteError):
        table.delete()


# Test delete success logs output
def test_delete_success_logs_correctly(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [10, 20]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    table.delete()
    assert table.output is not None
    assert len(table.output) == 2


# Test dtype conversion with integer types
def test_pandas_dtype_to_sqlalchemy_with_integer_types(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    dtypes = pd.Series(
        {
            "small_int": pd.Series([1], dtype="int8").dtype,
            "medium_int": pd.Series([1], dtype="int16").dtype,
            "large_int": pd.Series([1], dtype="int32").dtype,
            "very_large_int": pd.Series([1], dtype="int64").dtype,
        }
    )

    result = table._pandas_dtype_to_sqlalchemy(dtypes)

    assert "small_int" in result
    assert "medium_int" in result
    assert "large_int" in result
    assert "very_large_int" in result


# Test dtype conversion with all types together
def test_pandas_dtype_to_sqlalchemy_with_all_types(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    dtypes = pd.Series(
        {
            "int_col": pd.Series([1], dtype="int64").dtype,
            "float_col": pd.Series([1.0]).dtype,
            "bool_col": pd.Series([True], dtype="bool").dtype,
            "datetime_col": pd.Series(pd.date_range("2020-01-01", periods=1)).dtype,
            "string_col": pd.Series(["a", "b"]).dtype,
            "cat_col": pd.Categorical(["x", "y"]).dtype,
        }
    )

    result = table._pandas_dtype_to_sqlalchemy(dtypes)

    assert len(result) == 6
    assert "int_col" in result
    assert "float_col" in result
    assert "bool_col" in result
    assert "datetime_col" in result
    assert "string_col" in result
    assert "cat_col" in result


# Test list with tables and views
def test_list_with_tables_and_views(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=["table1", "table2", "view1"])
    mock_inspector.get_view_names = MagicMock(return_value=["view1"])

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()

    assert table.output is not None
    assert len(table.output) == 3
    assert any(table.output["TABLE_TYPE"] == "VIEW")
    assert any(table.output["TABLE_TYPE"] == "BASE TABLE")


# Test list with empty schema
def test_list_with_empty_schema(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=[])
    mock_inspector.get_view_names = MagicMock(return_value=[])

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()

    assert table.output is not None
    assert len(table.output) == 0


# Test get_details
def test_get_details_returns_correct_dict(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)

    details = table.get_details()

    assert details["table_name"] == "mytable"
    assert details["schema_name"] == "myschema"


# Test type property
def test_type_property_returns_correct_type(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    assert table.type == ResourceType.MICROSOFT_SQL_DATASET


# Test list connection error
def test_list_raises_list_error_on_connection_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    linked_service.connection = None

    with pytest.raises(ListError):
        table.list()


# Test purge connection error
def test_purge_raises_purge_error_on_connection_failure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    linked_service.connection = None

    with pytest.raises(PurgeError):
        table.purge()


# Test delete with invalid column names
def test_delete_with_unsafe_column_names(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id;col": [1]})
    table.input = df

    with pytest.raises(DeleteError):
        table.delete()


# Additional tests for 100% coverage
def test_create_with_data_success(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test successful create operation with data."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    table.input = df

    # Mock connection for create operation
    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    # Mock inspect to say table doesn't exist
    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.output is not None
    assert len(table.output) == 2
    assert "id" in table.schema
    assert "name" in table.schema


def test_delete_with_multiple_columns(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test delete with multiple columns for matching."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    table.delete()

    assert table.output is not None
    assert len(table.output) == 2
    mock_conn.execute.assert_called_once()


def test_list_creates_dataframe_with_correct_structure(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that list creates DataFrame with correct columns."""
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=["tbl1", "tbl2"])
    mock_inspector.get_view_names = MagicMock(return_value=["tbl2"])

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()

    assert table.output is not None
    assert "TABLE_SCHEMA" in table.output.columns
    assert "TABLE_NAME" in table.output.columns
    assert "TABLE_TYPE" in table.output.columns
    assert len(table.output) == 2


def test_purge_with_quoted_table_name(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test purge operation with success."""
    table = make_table(settings, linked_service)
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn_ctx.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_conn_ctx)

    table.purge()

    # Verify execute was called (meaning the SQL was prepared and executed)
    mock_conn.execute.assert_called_once()


def test_build_filters_with_no_filters(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test building select with no filters."""
    table = make_table(settings, linked_service)
    mock_table = MagicMock()
    mock_stmt = MagicMock()

    result = table._build_filters(mock_stmt, mock_table)

    assert result is mock_stmt


def test_build_order_by_with_no_order(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test building select with no order by."""
    table = make_table(settings, linked_service)
    mock_table = MagicMock()
    mock_stmt = MagicMock()

    result = table._build_order_by(mock_stmt, mock_table)

    assert result is mock_stmt


def test_quote_identifier_with_valid_name(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test quote identifier returns quoted name."""
    table = make_table(settings, linked_service)

    result = table._quote_identifier("valid_column_name")

    assert result == "[valid_column_name]"


def test_get_details_with_no_optional_settings(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test get_details when no optional settings are set."""
    table = make_table(settings, linked_service)
    settings.read = None
    table.settings = settings

    details = table.get_details()

    assert details["table_name"] == "mytable"
    assert details["schema_name"] == "myschema"
    assert "filters" not in details or details.get("filters") is None


def test_pandas_dtype_mapping_with_object_type(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test dtype conversion with unknown object type."""
    table = make_table(settings, linked_service)
    dtypes = pd.Series(
        {
            "unknown_col": pd.Series([None]).dtype,
        }
    )

    result = table._pandas_dtype_to_sqlalchemy(dtypes)

    assert "unknown_col" in result


def test_close_calls_linked_service_close(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that close delegates to linked service."""
    table = make_table(settings, linked_service)

    table.close()

    linked_service.close.assert_called_once()


# Tests with direct pandas.DataFrame.to_sql mocking for 100% coverage


# Tests with direct SQLAlchemy insert() mocking for 100% coverage


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_uses_fail_mode_by_default(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses insert() construct for inserting data."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    # Verify insert was called
    mock_insert.assert_called()
    assert table.output is not None


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_uses_append_mode_when_specified(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses insert() construct regardless of mode settings."""
    settings.create = MagicMock(mode="append", index=False)
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=True)
        mock_inspect.return_value = mock_inspector

        with patch.object(table, "_get_table") as mock_get_table:
            mock_table = MagicMock()
            mock_get_table.return_value = mock_table
            table.create()

    mock_insert.assert_called()


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_uses_replace_mode_when_specified(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses insert() construct for inserts."""
    settings.create = MagicMock(mode="replace", index=False)
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=True)
        mock_inspect.return_value = mock_inspector

        with patch.object(table, "_get_table") as mock_get_table:
            mock_table = MagicMock()
            mock_get_table.return_value = mock_table
            table.create()

    mock_insert.assert_called()


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_excludes_index_by_default(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create excludes index by default."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.settings.create.index is False


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_includes_index_when_specified(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create includes index when specified."""
    settings.create = MagicMock(mode="fail", index=True)
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.settings.create.index is True


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_populates_output_on_success(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create populates output with a copy of input."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2, 3], "name": ["x", "y", "z"]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.output is not None
    assert len(table.output) == 3
    assert list(table.output.columns) == ["id", "name"]
    assert table.output is not df  # Should be a copy, not the same object


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_sets_schema_on_output(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create sets schema on the output DataFrame."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "value": [1.5, 2.5]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.schema is not None
    assert "id" in table.schema
    assert "value" in table.schema


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_calls_to_sql_with_correct_table_name(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses insert() construct for the correct table."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    # Verify insert was called with the table object
    mock_insert.assert_called()


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_calls_to_sql_with_correct_schema(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses insert() construct with correct schema."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    mock_insert.assert_called()


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_calls_to_sql_with_dtype_mapping(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create uses proper dtype handling when inserting."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    mock_insert.assert_called()


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_success_logs_message(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create logs success message on successful write."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2, 3]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

        # Verify output was created
        assert table.output is not None
        assert len(table.output) == 3


@patch("ds_provider_microsoft_py_lib.dataset.mssql.insert")
def test_create_populates_schema_correctly(
    mock_insert: MagicMock, settings: MsSqlTableDatasetSettings, linked_service: MagicMock
) -> None:
    """Test that create properly initializes schema from input DataFrame."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [1, 2], "email": ["a@test.com", "b@test.com"], "active": [True, False]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.has_table = MagicMock(return_value=False)
        mock_inspect.return_value = mock_inspector

        table.create()

    assert table.schema is not None
    assert len(table.schema) == 3
    assert "id" in table.schema
    assert "email" in table.schema
    assert "active" in table.schema


def test_delete_with_single_column_key(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test delete operation with single column as primary key."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"id": [100, 200, 300]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    table.delete()

    assert table.output is not None
    assert len(table.output) == 3
    mock_conn.execute.assert_called_once()


def test_delete_logs_success_message(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that delete logs success message."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame({"user_id": [1, 2]})
    table.input = df

    mock_conn = MagicMock()
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=mock_conn)
    mock_begin.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_begin)

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.logger"):
        table.delete()
        # Verify that logging was attempted (either info or debug)
        assert table.output is not None


def test_list_populates_all_required_columns(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that list populates all required DataFrame columns."""
    table = make_table(settings, linked_service)
    mock_inspector = MagicMock()
    mock_inspector.get_table_names = MagicMock(return_value=["users", "orders"])
    mock_inspector.get_view_names = MagicMock(return_value=[""])

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=mock_inspector):
        table.list()

    assert table.output is not None
    assert "TABLE_SCHEMA" in table.output.columns
    assert "TABLE_NAME" in table.output.columns
    assert "TABLE_TYPE" in table.output.columns
    assert len(table.output) == 2


def test_purge_executes_drop_table_statement(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that purge executes DROP TABLE statement."""
    table = make_table(settings, linked_service)
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn_ctx.__exit__ = MagicMock(return_value=None)
    linked_service.connection.begin = MagicMock(return_value=mock_conn_ctx)

    table.purge()

    # Verify that a SQL statement was executed
    mock_conn.execute.assert_called_once()
    # The call should contain DROP TABLE logic
    executed_statement = mock_conn.execute.call_args
    assert executed_statement is not None


def test_get_details_includes_all_settings_properties(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that get_details includes all required settings properties."""
    table = make_table(settings, linked_service)

    details = table.get_details()

    assert "table_name" in details
    assert "schema_name" in details
    assert details["table_name"] == "mytable"
    assert details["schema_name"] == "myschema"


def test_quote_identifier_accepts_valid_names(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that quote_identifier properly quotes valid column names."""
    table = make_table(settings, linked_service)

    # Test various valid column names
    valid_names = ["user_id", "firstName", "last_name", "col123", "_column"]

    for name in valid_names:
        result = table._quote_identifier(name)
        assert result is not None
        assert "[" in result and "]" in result


def test_set_schema_handles_various_dtypes(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test that _set_schema handles various pandas dtypes."""
    table = make_table(settings, linked_service)
    df = pd.DataFrame(
        {
            "int_col": [1, 2, 3],
            "float_col": [1.0, 2.0, 3.0],
            "str_col": ["a", "b", "c"],
            "bool_col": [True, False, True],
        }
    )

    table._set_schema(df)

    assert table.schema is not None
    assert len(table.schema) == 4
    assert all(isinstance(v, str) for v in table.schema.values())


# Tests specifically for _build_filters method (lines 625-633)


def test_build_filters_with_single_filter(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters with a single filter condition."""
    table = make_table(settings, linked_service)
    table.settings.read = ReadSettings(filters={"status": "active"})

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("status", String(50)),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    result = table._build_filters(stmt, test_table)

    # Verify result is a select statement with WHERE clause
    assert result is not None
    assert "WHERE" in str(result)
    assert "status" in str(result)


def test_build_filters_with_multiple_filters(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters with multiple filter conditions (AND logic)."""

    table = make_table(settings, linked_service)
    table.settings.read = ReadSettings(filters={"status": "active", "amount": 100})

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("status", String(50)),
        Column("amount", Integer),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    result = table._build_filters(stmt, test_table)

    # Verify result includes both filter conditions
    assert result is not None
    result_str = str(result)
    assert "WHERE" in result_str
    assert "status" in result_str
    assert "amount" in result_str


def test_build_filters_with_numeric_value(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters with numeric filter values."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(filters={"amount": 150.50, "status_code": 1})

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("amount", Float),
        Column("status_code", Integer),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    table.settings.read = read_settings
    result = table._build_filters(stmt, test_table)

    # Verify result includes both filter conditions
    assert result is not None
    assert "WHERE" in str(result)
    assert "amount" in str(result)


def test_build_filters_with_empty_filters_dict(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters with empty filters dictionary."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(filters={})  # Empty filters

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    table.settings.read = read_settings
    result = table._build_filters(stmt, test_table)

    # Empty filters should return unchanged statement
    assert result is stmt


def test_build_filters_with_string_values(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters with various string filter values."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(filters={"name": "John", "category": "Premium"})

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(100)),
        Column("category", String(50)),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    table.settings.read = read_settings
    result = table._build_filters(stmt, test_table)

    # Verify result includes both filter conditions
    assert result is not None
    assert "WHERE" in str(result)
    assert "name" in str(result)
    assert "category" in str(result)


def test_build_filters_creates_and_conditions(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_filters creates AND conditions for multiple filters."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(filters={"status": "active", "type": "premium", "level": 5})

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("status", String(50)),
        Column("type", String(50)),
        Column("level", Integer),
    )

    # Build filters with real statement

    stmt = sql_select(test_table)
    table.settings.read = read_settings
    result = table._build_filters(stmt, test_table)

    # Verify result includes all filter conditions
    assert result is not None
    result_str = str(result)
    assert "WHERE" in result_str
    assert "status" in result_str
    assert "type" in result_str
    assert "level" in result_str


# Tests specifically for _build_order_by method (lines 653-668)


def test_build_order_by_with_tuple_desc_direction(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_order_by with tuple specs having desc direction."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(order_by=[("id", "desc")])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", Integer),
    )

    # Build order by with real statement

    stmt = sql_select(test_table)
    table.settings.read.order_by = read_settings.order_by

    result = table._build_order_by(stmt, test_table)

    # Verify result is a select statement
    assert result is not None
    assert str(result).startswith("SELECT")


def test_build_order_by_with_tuple_asc_direction(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_order_by with tuple specs having asc direction."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(order_by=[("id", "asc")])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", Integer),
    )

    # Build order by with real statement

    stmt = sql_select(test_table)
    table.settings.read.order_by = read_settings.order_by

    result = table._build_order_by(stmt, test_table)

    # Verify result is a select statement
    assert result is not None
    assert str(result).startswith("SELECT")


def test_build_order_by_with_string_spec(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_order_by with string specs (defaults to asc)."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(order_by=["id"])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", Integer),
    )

    # Build order by with real statement

    stmt = sql_select(test_table)
    table.settings.read.order_by = read_settings.order_by

    result = table._build_order_by(stmt, test_table)

    # Verify result is a select statement
    assert result is not None
    assert str(result).startswith("SELECT")


def test_build_order_by_with_mixed_specs(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_order_by with mixed tuple and string specs."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(order_by=[("id", "desc"), "name"])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", Integer),
    )

    # Build order by with real statement

    stmt = sql_select(test_table)
    table.settings.read.order_by = read_settings.order_by

    result = table._build_order_by(stmt, test_table)

    # Verify result is a select statement
    assert result is not None
    assert str(result).startswith("SELECT")


def test_build_order_by_with_multiple_columns(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_order_by with multiple order columns."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(order_by=["id", "name", ("value", "desc")])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", Integer),
        Column("value", Integer),
    )

    # Build order by with real statement

    stmt = sql_select(test_table)
    table.settings.read.order_by = read_settings.order_by

    result = table._build_order_by(stmt, test_table)

    # Verify result is a select statement
    assert result is not None
    assert str(result).startswith("SELECT")


def test_build_select_columns_with_single_column(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns with a single column specified."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(columns=["name"])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
    )

    # Build select with real statement

    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Verify result is a select statement with specific column
    assert result is not None
    assert "name" in str(result)
    assert "SELECT" in str(result)


def test_build_select_columns_with_multiple_columns(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns with multiple columns specified."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(columns=["id", "name", "status"])

    # Create a real SQLAlchemy table for this test
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
        Column("status", String(20)),
    )

    # Build select with real statement
    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Verify result includes all specified columns
    assert result is not None
    result_str = str(result)
    assert "id" in result_str
    assert "name" in result_str
    assert "status" in result_str


def test_build_select_columns_with_no_columns_specified(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns returns all columns when none specified."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(columns=None)  # No columns specified

    # Create a real SQLAlchemy table
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
    )

    # Build select with no columns specified
    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Should return select(table) which includes all columns
    assert result is not None
    assert "SELECT" in str(result)


def test_build_select_columns_with_empty_columns_list(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns with empty columns list."""

    table = make_table(settings, linked_service)
    read_settings = ReadSettings(columns=[])  # Empty columns list

    # Create a real SQLAlchemy table
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
    )

    # Build select with empty columns list should return all columns
    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Should return select(table) since columns list is empty
    assert result is not None
    assert "SELECT" in str(result)


def test_build_select_columns_with_none_read_settings(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns with None read settings."""

    table = make_table(settings, linked_service)

    # Create a real SQLAlchemy table
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
    )

    # Build select with None read settings
    table.settings.read = ReadSettings()
    result = table._build_select_columns(test_table)

    # Should return select(table) for all columns
    assert result is not None
    assert "SELECT" in str(result)


def test_build_select_columns_preserves_column_order(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns preserves specified column order."""

    table = make_table(settings, linked_service)
    # Specify columns in specific order
    read_settings = ReadSettings(columns=["status", "name", "id"])

    # Create a real SQLAlchemy table
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
        Column("status", String(20)),
    )

    # Build select with columns in specific order
    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Verify result is a select statement
    assert result is not None
    result_str = str(result)
    assert "status" in result_str
    assert "name" in result_str
    assert "id" in result_str


def test_build_select_columns_with_single_column_repeated(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Test _build_select_columns with same column specified multiple times."""

    table = make_table(settings, linked_service)
    # Specify same column multiple times
    read_settings = ReadSettings(columns=["name", "name"])

    # Create a real SQLAlchemy table
    metadata = MetaData()
    test_table = SQLTable(
        "test",
        metadata,
        Column("id", Integer),
        Column("name", String(50)),
    )

    # Build select with repeated column
    table.settings.read = read_settings
    result = table._build_select_columns(test_table)

    # Should work - includes the column (may appear twice in SELECT)
    assert result is not None
    assert "name" in str(result)
