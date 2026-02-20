"""
**File**: test_type_coercion.py
**Region**: tests/dataset

Tests for value coercion and explicit type mapping in MsSqlTable.

These tests verify that the pandas DataFrame serialization does not change thing when writing to SQL Server

Covers:
- pd.NaT, pd.NA, NaN are converted to None (SQL NULL)
- Numpy and pyarrow scalars are coerced to native Python types
- Nested dicts/lists are serialized to JSON
- Large integers are preserved as int64, not downcast to float
- Booleans stay as bool, not converted to int
- Timestamp values are converted to datetime.datetime
"""

import datetime as dt
import json
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import BigInteger, Boolean, DateTime, Float, String

from ds_provider_microsoft_py_lib.dataset.mssql import (
    DeleteSettings,
    MsSqlTable,
    MsSqlTableDatasetSettings,
    _coerce_value,
)
from ds_provider_microsoft_py_lib.serde.table import MsSqlTableSerializer


class TestCoerceValue:
    """Test the _coerce_value() function."""

    def test_coerce_value_pd_nat_to_none(self):
        """pd.NaT must become None (SQL NULL)."""
        result = _coerce_value(pd.NaT)
        assert result is None

    def test_coerce_value_pd_na_to_none(self):
        """pd.NA must become None (SQL NULL)."""
        result = _coerce_value(pd.NA)
        assert result is None

    def test_coerce_value_nan_to_none(self):
        """NaN must become None (SQL NULL)."""
        result = _coerce_value(float("nan"))
        assert result is None

    def test_coerce_value_np_nan_to_none(self):
        """np.nan must become None (SQL NULL)."""
        result = _coerce_value(np.nan)
        assert result is None

    def test_coerce_value_numpy_int64(self):
        """np.int64 must be converted to native Python int."""
        val = np.int64(42)
        result = _coerce_value(val)
        assert isinstance(result, int)
        assert result == 42
        assert not isinstance(result, np.integer)

    def test_coerce_value_numpy_float64(self):
        """np.float64 must be converted to native Python float."""
        val = np.float64(3.14)
        result = _coerce_value(val)
        assert isinstance(result, float)
        assert result == 3.14
        assert not isinstance(result, np.floating)

    def test_coerce_value_numpy_bool(self):
        """np.bool_ must be converted to native Python bool."""
        val = np.bool_(True)
        result = _coerce_value(val)
        assert isinstance(result, bool)
        assert result is True

    def test_coerce_value_pandas_timestamp(self):
        """pd.Timestamp must be converted to datetime.datetime."""

        val = pd.Timestamp("2024-01-15 10:30:45")
        result = _coerce_value(val)
        assert isinstance(result, dt.datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_coerce_value_dict_to_json(self):
        """dict must be serialized to JSON string."""
        val = {"key": "value", "count": 42}
        result = _coerce_value(val)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == val

    def test_coerce_value_list_to_json(self):
        """list must be serialized to JSON string."""
        val = [1, 2, 3, "four"]
        result = _coerce_value(val)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == val

    def test_coerce_value_none_stays_none(self):
        """None must stay None."""
        result = _coerce_value(None)
        assert result is None

    def test_coerce_value_native_int(self):
        """Native Python int should stay int."""
        result = _coerce_value(42)
        assert isinstance(result, int)
        assert result == 42

    def test_coerce_value_native_float(self):
        """Native Python float should stay float."""
        result = _coerce_value(3.14)
        assert isinstance(result, float)
        assert result == 3.14

    def test_coerce_value_native_str(self):
        """Native Python str should stay str."""
        result = _coerce_value("hello")
        assert isinstance(result, str)
        assert result == "hello"

    def test_coerce_value_large_int64(self):
        """Large int64 values must be preserved exactly (test for truncation bug)."""
        large_int = 2**60  # Large enough to exceed 32-bit
        val = np.int64(large_int)
        result = _coerce_value(val)
        assert isinstance(result, int)
        assert result == large_int
        assert result > 2**31  # Verify it's beyond 32-bit range


class TestCoerceValuePyarrowEdgeCases:
    """Test pyarrow scalar edge cases."""

    def test_coerce_value_pyarrow_scalar(self):
        """Test coercion of pyarrow scalars with .item() method."""

        # Create a mock pyarrow scalar
        class MockArrowScalar:
            def item(self):
                return 42

        result = _coerce_value(MockArrowScalar())
        assert result == 42

    def test_coerce_value_pyarrow_with_exception(self):
        """Test pyarrow scalar with .item() that raises exception."""

        class MockBrokenArrowScalar:
            def item(self):
                raise TypeError("Cannot convert")

        result = _coerce_value(MockBrokenArrowScalar())
        # Should return object as-is when .item() fails
        assert isinstance(result, MockBrokenArrowScalar)


class TestExplicitTypeMapping:
    """Test explicit SQL type mapping in _infer_sql_types()."""

    @pytest.fixture()
    def settings(self):
        return MsSqlTableDatasetSettings(table_name="mytable", schema_name="myschema", delete=DeleteSettings())

    @pytest.fixture()
    def linked_service(self):
        engine = MagicMock()
        engine.dialect.identifier_preparer.quote = MagicMock(side_effect=lambda name: f"[{name}]")
        svc = MagicMock()
        svc.engine = engine
        return svc

    def make_table(self, settings, linked_service):
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

    def test_infer_sql_types_int64(self, settings, linked_service):
        """int64 columns should map to BIGINT."""

        table = self.make_table(settings, linked_service)
        df = pd.DataFrame({"id": pd.array([1, 2, 3], dtype=pd.Int64Dtype())})
        types = table._infer_sql_types(df)
        assert "id" in types
        assert isinstance(types["id"], BigInteger)

    def test_infer_sql_types_string(self, settings, linked_service):
        """string columns should map to String (NVARCHAR)."""

        table = self.make_table(settings, linked_service)
        df = pd.DataFrame({"name": pd.array(["Alice", "Bob"], dtype=pd.StringDtype())})
        types = table._infer_sql_types(df)
        assert "name" in types
        assert isinstance(types["name"], String)

    def test_infer_sql_types_float64(self, settings, linked_service):
        """float64 columns should map to Float."""

        table = self.make_table(settings, linked_service)
        df = pd.DataFrame({"value": [1.1, 2.2]})
        types = table._infer_sql_types(df)
        assert "value" in types
        assert isinstance(types["value"], Float)

    def test_infer_sql_types_bool(self, settings, linked_service):
        """boolean columns should map to Boolean (BIT)."""

        table = self.make_table(settings, linked_service)
        df = pd.DataFrame({"active": pd.array([True, False], dtype=pd.BooleanDtype())})
        types = table._infer_sql_types(df)
        assert "active" in types
        assert isinstance(types["active"], Boolean)

    def test_infer_sql_types_datetime64(self, settings, linked_service):
        """datetime64 columns should map to DateTime."""

        table = self.make_table(settings, linked_service)
        df = pd.DataFrame({"created_at": pd.to_datetime(["2024-01-15", "2024-01-16"])})
        types = table._infer_sql_types(df)
        assert "created_at" in types
        assert isinstance(types["created_at"], DateTime)


class TestValueCoercionInBulkInsert:
    """Test that _attempt_fast_bulk_insert applies _coerce_value() to all rows."""

    @pytest.fixture()
    def settings(self):
        return MsSqlTableDatasetSettings(table_name="mytable", schema_name="myschema", delete=DeleteSettings())

    @pytest.fixture()
    def linked_service(self):
        engine = MagicMock()
        engine.dialect.identifier_preparer.quote = MagicMock(side_effect=lambda name: f"[{name}]")
        svc = MagicMock()
        svc.engine = engine
        return svc

    def make_table(self, settings, linked_service):
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

    def test_bulk_insert_coerces_nat_to_none(self, settings, linked_service):
        """NaT values in rows must be coerced to None before insertion."""
        table = self.make_table(settings, linked_service)

        # Create rows with NaT
        rows = [
            (1, pd.Timestamp("2024-01-15")),
            (2, pd.NaT),  # NaT in second row
        ]

        df_clean = pd.DataFrame({"id": [1, 2], "timestamp": [pd.Timestamp("2024-01-15"), pd.NaT]})

        raw_conn = MagicMock()
        cursor = MagicMock()
        raw_conn.cursor.return_value = cursor
        linked_service.engine.raw_connection.return_value = raw_conn

        table._attempt_fast_bulk_insert("[myschema].[mytable]", df_clean, rows)

        # Check that executemany was called
        cursor.executemany.assert_called_once()
        _, coerced_rows = cursor.executemany.call_args[0]

        # Verify coercion happened: second row should have None instead of pd.NaT
        assert coerced_rows[0][0] == 1
        assert coerced_rows[0][1] == pd.Timestamp("2024-01-15 00:00:00")
        assert coerced_rows[1][0] == 2
        assert coerced_rows[1][1] is None  # NaT coerced to None

    def test_bulk_insert_coerces_numpy_types(self, settings, linked_service):
        """Numpy scalar types must be coerced to native Python types."""
        table = self.make_table(settings, linked_service)

        # Create rows with numpy types
        rows = [
            (np.int64(42), np.float64(3.14), np.bool_(True)),
            (np.int64(99), np.float64(2.71), np.bool_(False)),
        ]

        df_clean = pd.DataFrame(
            {
                "id": np.array([42, 99], dtype=np.int64),
                "value": np.array([3.14, 2.71], dtype=np.float64),
                "active": np.array([True, False], dtype=np.bool_),
            }
        )

        raw_conn = MagicMock()
        cursor = MagicMock()
        raw_conn.cursor.return_value = cursor
        linked_service.engine.raw_connection.return_value = raw_conn

        table._attempt_fast_bulk_insert("[myschema].[mytable]", df_clean, rows)

        # Check coercion
        cursor.executemany.assert_called_once()
        _, coerced_rows = cursor.executemany.call_args[0]

        # Verify types are native Python, not numpy
        assert isinstance(coerced_rows[0][0], int) and not isinstance(coerced_rows[0][0], np.integer)
        assert isinstance(coerced_rows[0][1], float) and not isinstance(coerced_rows[0][1], np.floating)
        assert isinstance(coerced_rows[0][2], bool) and not isinstance(coerced_rows[0][2], np.bool_)

    def test_bulk_insert_preserves_large_integers(self, settings, linked_service):
        """Large int64 values must not be truncated or downcast to float."""
        table = self.make_table(settings, linked_service)

        large_id = 2**62  # Exceeds 32-bit but fits in 64-bit
        rows = [(np.int64(large_id),)]
        df_clean = pd.DataFrame({"id": [large_id]})

        raw_conn = MagicMock()
        cursor = MagicMock()
        raw_conn.cursor.return_value = cursor
        linked_service.engine.raw_connection.return_value = raw_conn

        table._attempt_fast_bulk_insert("[myschema].[mytable]", df_clean, rows)

        _, coerced_rows = cursor.executemany.call_args[0]

        # Verify value is preserved exactly
        assert coerced_rows[0][0] == large_id
        assert isinstance(coerced_rows[0][0], int)
        assert not isinstance(coerced_rows[0][0], float)
