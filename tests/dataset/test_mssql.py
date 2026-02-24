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
from sqlalchemy.exc import NoSuchTableError

from ds_provider_microsoft_py_lib.dataset.mssql import (
    MsSqlTable,
    MsSqlTableDatasetSettings,
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
    assert table.output is None


def test_delete_empty_input_returns_immediately(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame()  # type: ignore
    table.delete()
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
    linked_service.connection.connect = MagicMock(return_value=mock_conn_ctx)
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

    # Mock to_sql to raise an exception
    with patch.object(df, "to_sql", side_effect=RuntimeError("Write failed")), pytest.raises(CreateError):
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
