"""
**File:** ``__init__.py``
**Region:** ``ds-provider-microsoft-py-lib/dataset``

Dataset module for Microsoft provider.

Example:
>>> dataset = MsSqlTable(
...    linked_service=MsSqlLinkedService(...),
...    settings=MsSqlTableDatasetSettings(
...        table="your_table_name",
...        schema="your_schema_name",
...        delete=DeleteSettings(delete_table=False)
...    )
... )
>>> dataset.read()
"""

from .mssql import MsSqlTable, MsSqlTableDatasetSettings

__all__ = [
    "MsSqlTable",
    "MsSqlTableDatasetSettings",
]
