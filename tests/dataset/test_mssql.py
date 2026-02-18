"""
**File**: test_mssql.py
**Region**: tests/dataset

Unit tests for MsSqlTable dataset implementation, covering settings validation, read/write operations, and error handling.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DatasetException,
    DeleteError,
    ReadError,
)

from ds_provider_microsoft_py_lib.dataset.mssql import (
    DeleteSettings,
    MsSqlTable,
    MsSqlTableDatasetSettings,
)
from ds_provider_microsoft_py_lib.enums import ResourceType


@pytest.fixture()
def settings() -> MsSqlTableDatasetSettings:
    return MsSqlTableDatasetSettings(table_name="mytable", schema_name="myschema", chunksize=2, delete=DeleteSettings())


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


def test_settings_post_init_invalid_chunksize() -> None:
    """Verify __post_init__ raises an error for invalid chunksize."""
    with pytest.raises(DatasetException) as exc:
        MsSqlTableDatasetSettings(table_name="t", chunksize=0)
    assert exc.value.status_code == 422

    with pytest.raises(DatasetException) as exc:
        MsSqlTableDatasetSettings(table_name="t", chunksize=-1)
    assert exc.value.status_code == 422


def test_type_and_full_table_name(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify resource type and full table name composition."""

    table = make_table(settings, linked_service)

    assert table.type == ResourceType.MICROSOFT_SQL_DATASET
    assert table._get_full_table_name() == "myschema.mytable"


def test_quote_identifier_uses_preparer(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Ensure identifier quoting uses the dialect preparer."""

    table = make_table(settings, linked_service)
    quoted = table._quote_identifier("col")

    linked_service.engine.dialect.identifier_preparer.quote.assert_called_once_with("col")
    assert quoted == "[col]"


def test_quote_identifier_rejects_unsafe(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Reject unsafe identifier input."""

    table = make_table(settings, linked_service)

    with pytest.raises(ValueError):
        table._quote_identifier("bad;col")


def test_qualified_table_composes_schema_and_table(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Compose qualified table name from schema and table."""

    table = make_table(settings, linked_service)
    with patch.object(table, "_quote_identifier", side_effect=["[schema]", "[table]"]):
        assert table._qualified_table() == "[schema].[table]"


def test_read_success(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Read returns a dataframe and sets output."""

    table = make_table(settings, linked_service)
    df = pd.DataFrame({"a": [1]})

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.pd.read_sql_table", return_value=df) as read_sql_table:
        table.read()

    read_sql_table.assert_called_once_with(
        table_name=settings.table_name,
        con=linked_service.engine,
        schema=settings.schema_name,
    )
    assert isinstance(table.output, pd.DataFrame)
    assert list(table.output["a"]) == [1]


def test_read_value_error_maps_to_read_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Map ValueError from read to ReadError with 404 status."""
    table = make_table(settings, linked_service)

    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.pd.read_sql_table", side_effect=ValueError("missing")),
        pytest.raises(ReadError) as exc,
    ):
        table.read()

    assert exc.value.status_code == 404


def test_read_other_errors_wrapped(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Wrap unexpected read errors in ReadError."""

    table = make_table(settings, linked_service)
    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.pd.read_sql_table", side_effect=RuntimeError("boom")),
        pytest.raises(ReadError),
    ):
        table.read()


def test_create_uses_fast_executemany_and_skips_fallback(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Use fast executemany path when available."""

    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"col": [1, 2]})

    df_clean = MagicMock()
    df_clean.columns = ["col"]
    head_df = MagicMock()
    df_clean.head.return_value = head_df
    table.serializer.return_value = (df_clean, [(1,), (2,)])

    inspector = MagicMock()
    inspector.has_table.return_value = False
    raw_conn = MagicMock()
    cursor = MagicMock()
    raw_conn.cursor.return_value = cursor
    linked_service.engine.raw_connection.return_value = raw_conn

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector):
        table.create(batch_size=99)  # batch_size should be ignored

    inspector.has_table.assert_called_once_with(settings.table_name, schema=settings.schema_name)
    head_df.to_sql.assert_called_once()
    cursor.executemany.assert_called_once()
    raw_conn.commit.assert_called_once()
    raw_conn.close.assert_called_once()
    table._fallback_insert.assert_not_called()


def test_create_with_zero_chunksize(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify create works with chunksize=0, using a single batch."""
    settings.chunksize = 0
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"col": [1, 2]})
    rows = [(1,), (2,)]
    df_clean = MagicMock()
    df_clean.columns = ["col"]
    table.serializer.return_value = (df_clean, rows)

    inspector = MagicMock()
    inspector.has_table.return_value = True
    raw_conn = MagicMock()
    cursor = MagicMock()
    raw_conn.cursor.return_value = cursor
    linked_service.engine.raw_connection.return_value = raw_conn

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector):
        table.create()

    # With chunksize=0, batch_size should default to len(rows)
    cursor.executemany.assert_called_once()
    _, batch_arg = cursor.executemany.call_args.args
    assert len(batch_arg) == len(rows)


def test_create_with_empty_input_raises_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify that create raises a CreateError if the input DataFrame is empty."""
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame()  # Empty DataFrame

    with pytest.raises(CreateError, match=r"Input DataFrame must be a non-empty pandas.DataFrame"):
        table.create()


def test_create_wraps_general_errors(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify that general exceptions during create are wrapped in CreateError."""
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"col": [1]})
    table.serializer.return_value = (pd.DataFrame({"col": [1]}), [(1,)])

    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", side_effect=RuntimeError("boom")),
        pytest.raises(CreateError),
    ):
        table.create()


def test_create_wraps_unsafe_identifier_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify create wraps ValueError from unsafe identifiers in CreateError."""
    settings.table_name = "bad;table"
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"col": [1]})
    table.serializer.return_value = (pd.DataFrame({"col": [1]}), [(1,)])

    inspector = MagicMock()
    inspector.has_table.return_value = True
    linked_service.engine.raw_connection.return_value = MagicMock()

    with (
        patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector),
        pytest.raises(CreateError),
    ):
        table.create()


def test_create_falls_back_when_fast_path_fails(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Fallback to slow insert path when fast path fails."""

    table = make_table(settings, linked_service)
    table.input = pd.DataFrame({"col": [1]})

    df_clean = MagicMock()
    df_clean.columns = ["col"]
    table.serializer.return_value = (df_clean, [(1,)])

    inspector = MagicMock()
    inspector.has_table.return_value = True
    linked_service.engine.raw_connection.side_effect = RuntimeError("no raw conn")

    with patch("ds_provider_microsoft_py_lib.dataset.mssql.inspect", return_value=inspector):
        table.create()

    table._fallback_insert.assert_called_once_with(df_clean, settings.chunksize)


def test_update_delegates_to_create(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Delegate update calls to create."""
    table = make_table(settings, linked_service)

    with patch.object(table, "create") as create_mock:
        table.update(example=1)

    create_mock.assert_called_once_with(example=1)


def test_delete_table_path_executes_drop(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Execute DROP TABLE when delete_table is True."""
    settings.delete.delete_table = True
    table = make_table(settings, linked_service)

    with patch.object(table, "_qualified_table", return_value="quoted_table"):
        conn = MagicMock()
        conn_cm = MagicMock(__enter__=MagicMock(return_value=conn), __exit__=MagicMock(return_value=None))
        linked_service.engine.connect.return_value = conn_cm

        with patch("ds_provider_microsoft_py_lib.dataset.mssql.text", side_effect=lambda q: f"text:{q}") as text_mock:
            table.delete()

    text_mock.assert_called_once_with("DROP TABLE IF EXISTS quoted_table")
    conn.execute.assert_called_once_with("text:DROP TABLE IF EXISTS quoted_table")
    conn.commit.assert_called_once()


def test_delete_table_path_wraps_errors(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Wrap errors from DROP TABLE in DeleteError."""
    settings.delete.delete_table = True
    table = make_table(settings, linked_service)

    with patch.object(table, "_qualified_table", return_value="quoted_table"):
        linked_service.engine.connect.side_effect = RuntimeError("boom")
        with pytest.raises(DeleteError):
            table.delete()


def test_delete_wraps_unsafe_identifier_error(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Verify delete wraps ValueError from unsafe identifiers in DeleteError."""
    settings.table_name = "bad;table"
    table = make_table(settings, linked_service)

    with pytest.raises(DeleteError):
        table.delete()


def test_delete_requires_input_when_not_dropping_table(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Require input dataframe for delete when delete_table is False."""
    settings.delete.delete_table = False
    table = make_table(settings, linked_service)
    table.input = None

    with pytest.raises(DeleteError):
        table.delete()

    table.input = pd.DataFrame()
    with pytest.raises(DeleteError):
        table.delete()


def test_delete_rows_builds_where_clause_and_executes(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Build WHERE clause from input dataframe and execute DELETE."""
    settings.delete.delete_table = False
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame(
        [
            {"id": 1, "name": "a"},
            {"id": 2, "name": "b"},
        ]
    )

    with (
        patch.object(table, "_qualified_table", return_value="quoted"),
        patch.object(table, "_quote_identifier", side_effect=lambda col: f"<{col}>"),
    ):
        begin_cm = MagicMock()
        conn = MagicMock()
        begin_cm.__enter__.return_value = conn
        linked_service.engine.begin.return_value = begin_cm

        with patch("ds_provider_microsoft_py_lib.dataset.mssql.text", side_effect=lambda q: q):
            table.delete()

    linked_service.engine.begin.assert_called_once()
    conn.execute.assert_called_once()
    delete_sql, payloads = conn.execute.call_args.args
    # Check that the DELETE uses the correct columns and bind parameters, without
    # relying on the exact internal parameter names used by MsXqlTable.delete().
    assert "<id>" in delete_sql
    assert "<name>" in delete_sql
    # Expect parameter placeholders (e.g. :p0, :p1) instead of inlined values.
    assert ":" in delete_sql

    # Payloads should be a list of two parameter dicts corresponding to the two rows.
    assert isinstance(payloads, list)
    assert len(payloads) == 2
    first_row_params, second_row_params = payloads

    # Each payload dict should have two parameters whose values match the input rows,
    # irrespective of the specific parameter names (e.g. p0, p1).
    assert set(first_row_params.values()) == {1, "a"}
    assert set(second_row_params.values()) == {2, "b"}


def test_delete_rows_wraps_errors(settings: MsSqlTableDatasetSettings, linked_service: MagicMock) -> None:
    """Wrap errors from row deletion in DeleteError."""
    settings.delete.delete_table = False
    table = make_table(settings, linked_service)
    table.input = pd.DataFrame([{"id": 1}])

    with patch.object(table, "_qualified_table", return_value="quoted"):
        linked_service.engine.begin.side_effect = RuntimeError("boom")
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
