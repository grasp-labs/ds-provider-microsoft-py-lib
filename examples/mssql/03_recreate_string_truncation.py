"""
**File:** ``03_recreate_string_truncation.py``
**Region:** ``examples/03_recreate_string_truncation.py``

Example 03: Recreate MSSQL string truncation during table creation
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create a fresh Microsoft SQL Server table through `MsSqlTable.create()`.
- Trigger the current string-column inference behavior where text columns are created as `String(length=255)`.
- Reproduce a pyodbc string truncation error by inserting a value longer than 255 characters.
"""

import uuid

import pandas as pd
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError

from ds_provider_microsoft_py_lib.dataset.mssql import CreateSettings, MsSqlTable, MsSqlTableDatasetSettings, PurgeSettings
from ds_provider_microsoft_py_lib.linked_service.mssql import MsSqlLinkedService, MsSqlLinkedServiceSettings

linked_service = MsSqlLinkedService(
    settings=MsSqlLinkedServiceSettings(
        server="localhost",
        database="master",
        username="sa",
        password="dockerStrongPwd123",
        trust_server_certificate=True,
    ),
    id=uuid.uuid4(),
    name="testmssqlpackage",
    version="0.0.1",
    description="testmssqlpackage",
)

dataset = MsSqlTable(
    linked_service=linked_service,
    settings=MsSqlTableDatasetSettings(
        table="mssql_string_truncation_repro",
        schema="dbo",
        create=CreateSettings(
            index=False,
            primary_key=True,
            primary_key_columns=["id"],
        ),
        purge=PurgeSettings(drop_table=True),
    ),
    id=uuid.uuid4(),
    name="testmssqlstringtruncation",
    version="0.0.1",
    description="testmssqlstringtruncation",
)

dataset.linked_service.connect()

print("Dropping the table first to force schema inference on create().")
dataset.purge()

long_text = "x" * 610
dataset.input = pd.DataFrame(
    {
        "id": pd.Series([1], dtype="Int64"),
        "description": pd.Series([long_text], dtype="string"),
    }
)

print(f"Attempting to write description length: {len(long_text)}")

try:
    dataset.create()
    print("Create succeeded.")
except CreateError as exc:
    print("Create failed as expected.")
    print(exc.message)
