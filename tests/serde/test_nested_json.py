"""
**File**: `test_nested_json.py`
**Region**: `tests/serde`

Unit tests for nested JSON serialization with datetime objects.

Tests the MsSqlTableSerializer's ability to:
- Serialize nested dictionaries to JSON strings
- Handle datetime objects within nested structures
- Convert datetime to ISO format strings in JSON
- Handle NULL values in nested structures
"""

import datetime
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from ds_provider_microsoft_py_lib.serde.table import (
    MsSqlTableSerializer,
    _coerce_value,
    _json_encoder,
)


class TestNestedJsonSerialization:
    """Test nested JSON serialization with datetime handling."""

    def test_serialize_nested_dict_with_datetime(self) -> None:
        """Verify nested dict with datetime is serialized to JSON string."""
        serializer = MsSqlTableSerializer()

        test_datetime = datetime.datetime(2024, 1, 15, 10, 30, 45)
        data = {"id": [1], "metadata": [{"timestamp": test_datetime, "user": "alice", "value": 42}]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        # Verify the metadata is serialized to JSON string
        assert isinstance(rows[0][1], str)

        # Verify JSON is valid and contains ISO format timestamp
        parsed = json.loads(rows[0][1])
        assert "timestamp" in parsed
        assert parsed["timestamp"] == "2024-01-15T10:30:45"
        assert parsed["user"] == "alice"
        assert parsed["value"] == 42

    def test_serialize_nested_dict_with_multiple_datetimes(self) -> None:
        """Verify nested dict with multiple datetime objects."""
        serializer = MsSqlTableSerializer()

        dt1 = datetime.datetime(2024, 1, 15, 10, 0, 0)
        dt2 = datetime.datetime(2024, 1, 15, 11, 0, 0)

        data = {"id": [1], "event": [{"start": dt1, "end": dt2, "duration": (dt2 - dt1).total_seconds()}]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])
        assert parsed["start"] == "2024-01-15T10:00:00"
        assert parsed["end"] == "2024-01-15T11:00:00"
        assert parsed["duration"] == 3600.0

    def test_serialize_nested_dict_with_date(self) -> None:
        """Verify nested dict with date object is serialized."""
        serializer = MsSqlTableSerializer()

        test_date = datetime.date(2024, 1, 15)
        data = {"id": [1], "metadata": [{"date": test_date}]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])
        assert parsed["date"] == "2024-01-15"

    def test_serialize_nested_dict_with_timedelta(self) -> None:
        """Verify nested dict with timedelta is serialized as seconds."""
        serializer = MsSqlTableSerializer()

        td = datetime.timedelta(days=1, hours=2, minutes=30)
        data = {"id": [1], "metadata": [{"duration": td}]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])
        # 1 day + 2 hours + 30 minutes = 86400 + 7200 + 1800 = 95400 seconds
        assert parsed["duration"] == 95400.0

    def test_serialize_nested_dict_with_numpy_types(self) -> None:
        """Verify nested dict with numpy types is serialized correctly."""
        serializer = MsSqlTableSerializer()

        data = {"id": [1], "metadata": [{"int_val": np.int64(42), "float_val": np.float64(3.14), "bool_val": np.bool_(True)}]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])
        assert parsed["int_val"] == 42
        assert parsed["float_val"] == 3.14
        assert parsed["bool_val"] is True

    def test_serialize_nested_dict_with_null_value(self) -> None:
        """Verify NULL nested dict becomes Python None."""
        serializer = MsSqlTableSerializer()

        data = {"id": [1, 2], "metadata": [{"timestamp": datetime.datetime(2024, 1, 15, 10, 0, 0)}, None]}
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        assert rows[0][1] is not None
        assert rows[1][1] is None

    def test_serialize_complex_nested_structure(self) -> None:
        """Verify complex nested structure with mixed types."""
        serializer = MsSqlTableSerializer()

        data = {
            "id": [1],
            "event": [
                {
                    "timestamp": datetime.datetime(2024, 1, 15, 10, 30, 45),
                    "user": "alice@example.com",
                    "ip": "192.168.1.100",
                    "duration_seconds": 125.5,
                    "data_size_mb": 512,
                    "status": "completed",
                    "metadata": {"retry_count": 0, "version": 2},
                }
            ],
        }
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])

        assert parsed["timestamp"] == "2024-01-15T10:30:45"
        assert parsed["user"] == "alice@example.com"
        assert parsed["ip"] == "192.168.1.100"
        assert parsed["duration_seconds"] == 125.5
        assert parsed["data_size_mb"] == 512
        assert parsed["status"] == "completed"
        assert parsed["metadata"]["retry_count"] == 0
        assert parsed["metadata"]["version"] == 2

    def test_mixed_na_and_nested_dict_columns(self) -> None:
        """Verify serialization with both NA values and nested dicts."""
        serializer = MsSqlTableSerializer()

        data = {
            "id": [1, 2, 3],
            "value": [10.5, np.nan, 20.3],
            "metadata": [
                {"timestamp": datetime.datetime(2024, 1, 15, 10, 0, 0)},
                None,
                {"timestamp": datetime.datetime(2024, 1, 15, 11, 0, 0)},
            ],
        }
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        # Row 0: All values present
        assert rows[0][0] == 1
        assert rows[0][1] == 10.5
        assert rows[0][2] is not None

        # Row 1: NaN becomes None, metadata is None
        assert rows[1][0] == 2
        assert rows[1][1] is None
        assert rows[1][2] is None

        # Row 2: All values present
        assert rows[2][0] == 3
        assert rows[2][1] == 20.3
        assert rows[2][2] is not None

    def test_serialize_nested_dict_with_pd_na(self) -> None:
        """Verify pd.NA in nested dict is converted to JSON null."""
        serializer = MsSqlTableSerializer()

        data = {
            "id": [1, 2],
            "metadata": [
                {"name": "sensor1", "is_empty": pd.NA},
                {"name": "sensor2", "timestamp": datetime.datetime(2024, 1, 15, 10, 30, 45), "status": pd.NA},
            ],
        }
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        # First row: pd.NA becomes JSON null
        parsed1 = json.loads(rows[0][1])
        assert parsed1["name"] == "sensor1"
        assert parsed1["is_empty"] is None

        # Second row: datetime and pd.NA
        parsed2 = json.loads(rows[1][1])
        assert parsed2["name"] == "sensor2"
        assert parsed2["timestamp"] == "2024-01-15T10:30:45"
        assert parsed2["status"] is None

    def test_coerce_value_with_pd_timestamp(self) -> None:
        """Verify pd.Timestamp is converted to datetime.datetime."""
        ts = pd.Timestamp("2024-01-15 10:30:45")
        result = _coerce_value(ts)

        assert isinstance(result, dt.datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 45

    def test_coerce_value_with_numpy_scalars(self) -> None:
        """Verify NumPy scalars are converted via .item() method."""
        # Test np.int64 with .item()
        int_val = _coerce_value(np.int64(42))
        assert isinstance(int_val, int)
        assert int_val == 42

        # Test np.float64 with .item()
        float_val = _coerce_value(np.float64(3.14))
        assert isinstance(float_val, float)
        assert float_val == 3.14

        # Test np.bool_ with .item()
        bool_val = _coerce_value(np.bool_(True))
        assert isinstance(bool_val, (bool, np.bool_))
        assert bool_val

    def test_coerce_value_exception_handling(self) -> None:
        """Verify exception handling in _coerce_value when pd.isna() fails."""

        # Test with object that has no .item() method
        class CustomObject:
            def __repr__(self) -> str:
                return "CustomObject"

        obj = CustomObject()
        result = _coerce_value(obj)
        assert result is obj  # Should return unchanged

    def test_json_encoder_with_pd_na_exception_handling(self) -> None:
        """Verify pd.NA exception handling in _json_encoder."""
        # pd.NA should be converted to None
        result = _json_encoder(pd.NA)
        assert result is None

    def test_json_encoder_with_various_na_types(self) -> None:
        """Verify _json_encoder handles different NA types with pd.isna()."""

        # Test pd.NA - should convert to None
        result_na = _json_encoder(pd.NA)
        assert result_na is None

        # Test np.nan - should also convert to None via pd.isna()
        result_nan = _json_encoder(np.nan)
        assert result_nan is None

    def test_nested_dict_with_pd_na_and_nan_in_json(self) -> None:
        """Verify nested dict serialization with pd.NA and np.nan."""
        serializer = MsSqlTableSerializer()

        data = {
            "id": [1],
            "metadata": [
                {
                    "value1": pd.NA,
                    "value3": "valid",
                    "value4": 42,
                    "timestamp": datetime.datetime(2024, 1, 15, 10, 30, 45),
                }
            ],
        }
        df = pd.DataFrame(data)

        _, rows = serializer(df)

        parsed = json.loads(rows[0][1])
        assert parsed["value1"] is None
        assert parsed["value3"] == "valid"
        assert parsed["value4"] == 42
        assert parsed["timestamp"] == "2024-01-15T10:30:45"

    def test_coerce_value_pd_isna_exception(self) -> None:
        """Verify exception handling when pd.isna() raises an exception."""

        # Create an object that will cause pd.isna() to raise TypeError/ValueError
        class ObjectThatThrowsOnIsna:
            def __init__(self):
                pass

            def __array__(self):
                raise TypeError("Cannot convert to array")

        # pd.isna will try to check this and raise, but we catch it
        obj = ObjectThatThrowsOnIsna()
        result = _coerce_value(obj)
        # Should return the object unchanged since exception is caught
        assert result is obj

    def test_coerce_value_item_method_raises(self) -> None:
        """Verify exception handling when .item() method raises."""

        # Create a mock object with .item() that raises ValueError
        class MockObjectWithBadItem:
            def item(self):
                raise ValueError("Cannot convert to scalar")

        obj = MockObjectWithBadItem()
        result = _coerce_value(obj)
        # Should return unchanged since exception is caught
        assert result is obj

    def test_json_encoder_exception_on_isna(self) -> None:
        """Verify exception handling when pd.isna() raises in _json_encoder."""

        # Create an object that will cause pd.isna() to raise
        class ObjectThatThrowsOnIsna:
            def __array__(self):
                raise ValueError("Cannot convert to array")

        obj = ObjectThatThrowsOnIsna()
        # This should raise TypeError because object is not JSON serializable
        # (after exception in pd.isna() is caught)
        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_encoder(obj)
