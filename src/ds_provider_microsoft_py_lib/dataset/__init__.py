"""
**File:** ``__init__.py``
**Region:** ``ds-provider-microsoft-py-lib/dataset``

Dataset module for Microsoft provider.

Example:
>>> dataset = MssqlTable(
...    linked_service=MsSqlLinkedService(...),
...    settings=MssqlTableDatasetSettings(
...        table_name="your_table_name",
...        schema_name="your_schema_name",
...        delete=DeleteSettings(delete_table=False)
...    )
... )
>>> dataset.read()
"""

from .mssql import MssqlTable, MssqlTableDatasetSettings

__all__ = [
    "MssqlTable",
    "MssqlTableDatasetSettings",
]
