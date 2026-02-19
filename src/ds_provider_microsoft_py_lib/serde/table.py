"""
**File**: `table.py`
**Region**: `ds-provider-microsoft-py-lib/serde/table`

Serialization and deserialization for Microsoft SQL Server tables.

Example:
>>> data_frame = pd.DataFrame(...)
>>> serializer = MsSqlTableSerializer()
>>> cleaned_df, rows = serializer(data_frame)
"""

from typing import Any

import numpy as np
import pandas as pd
from ds_resource_plugin_py_lib.common.serde.deserialize import DataDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import DataSerializer


class MsSqlTableSerializer(DataSerializer):
    """
    Serialize SQL Table data.
    The serializer is responsible for converting a pandas DataFrame into a cleaned
    DataFrame and a sequence of row tuples suitable for MSSQL insert operations
    (for example, via pyodbc.executemany).
    """

    @staticmethod
    def _clean_column(col_data: pd.Series) -> pd.Series:
        """
        Cleans a pandas Series by handling special data types for MSSQL compatibility.
        """
        if pd.api.types.is_datetime64_any_dtype(col_data) and col_data.dt.tz is not None:
            return col_data.dt.tz_convert("UTC").dt.tz_localize(None)  # type: ignore[no-any-return]
        if pd.api.types.is_timedelta64_dtype(col_data):
            return col_data.apply(lambda x: x.total_seconds() if pd.notna(x) else None)  # type: ignore[no-any-return]
        if pd.api.types.is_complex_dtype(col_data):
            return col_data.astype(str)
        return col_data

    def __call__(self, obj: pd.DataFrame, **_kwargs: Any) -> tuple[pd.DataFrame, list[tuple[Any, ...]]]:
        """
        Prepare a DataFrame for MSSQL inserts.

        Returns a cleaned DataFrame (NA -> None) and materialized row tuples
        suitable for pyodbc executemany.
        """

        df_clean = obj.replace({np.nan: None, pd.NA: None, pd.NaT: None})
        for col in df_clean.columns:
            df_clean[col] = self._clean_column(df_clean[col])
        rows: list[tuple[Any, ...]] = [tuple(row) for row in df_clean.values]
        return df_clean, rows


class MsSqlTableDeserializer(DataDeserializer):
    """
    No special deserialization needed for MSSQL tables, as pandas can read SQL query results directly into DataFrames.
    """

    pass
