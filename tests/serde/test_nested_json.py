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
import json

import numpy as np
import pandas as pd

from ds_provider_microsoft_py_lib.serde.table import MsSqlTableSerializer


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
