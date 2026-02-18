from typing import Any

import numpy as np
import pandas as pd
from ds_resource_plugin_py_lib.common.serde.deserialize import DataDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import DataSerializer


class MssqlTableSerializer(DataSerializer):
    """
    Serialize SQL Table data.
    The serializer is responsible for converting a pandas DataFrame into a cleaned
    DataFrame and a sequence of row tuples suitable for MSSQL insert operations
    (for example, via pyodbc.executemany).
    """

    def __call__(self, obj: pd.DataFrame, **_kwargs: Any) -> tuple[pd.DataFrame, list[tuple[Any, ...]]]:
        """
        Prepare a DataFrame for MSSQL inserts.

        Returns a cleaned DataFrame (NA -> None) and materialized row tuples
        suitable for pyodbc executemany.
        """

        df_clean = obj.replace({np.nan: None, pd.NA: None, pd.NaT: None})
        rows: list[tuple[Any, ...]] = [tuple(row) for row in df_clean.values]
        return df_clean, rows


class MssqlTableDeserializer(DataDeserializer):
    """
    No special deserialization needed for MSSQL tables, as pandas can read SQL query results directly into DataFrames.
    """

    pass
