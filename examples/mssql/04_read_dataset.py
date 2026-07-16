"""
**File:** ``04_read_dataset.py``
**Region:** ``examples/mssql/04_read_dataset.py``

Example 04: Read rows from the same Microsoft SQL Server database used by the other examples.
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Reuse the same connection details as the other MSSQL examples.
- Seed the same ``master`` database and ``dbo.my_table2`` table used by
  ``02_create_dataset.py`` when it is missing or empty.
- Apply filters, ordering, and a read limit through ``MsSqlTableDatasetSettings.read``.
"""

import uuid

import pandas as pd
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError

from ds_provider_microsoft_py_lib.dataset.mssql import MsSqlTable, MsSqlTableDatasetSettings, ReadSettings
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
        table="my_table2",
        schema="dbo",
        read=ReadSettings(
            auto_paginate=True,
            limit=2,
            columns=["id", "color", "score", "active"],
            filters={"active": True},
            order_by=[("score", "desc"), "id"],
        ),
    ),
    id=uuid.uuid4(),
    name="testmssqldataset-read",
    version="0.0.1",
    description="testmssqldataset-read",
)

dataset.linked_service.connect()

seed_data = pd.DataFrame(
    {
        "id": pd.Series(list(range(1, 13)), dtype="Int64"),
        "color": [
            "Red",
            "Blue",
            "Green",
            "Yellow",
            "Purple",
            "Orange",
            "Black",
            "White",
            "Cyan",
            "Magenta",
            "Teal",
            "Gray",
        ],
        "score": pd.Series([9.5, 7.2, 8.1, 6.4, 9.1, 5.8, 7.7, 6.9, 8.8, 5.2, 7.4, 6.1], dtype="float32"),
        "active": pd.Series([True, True, False, True, False, True, True, False, True, True, False, True], dtype="boolean"),
    }
)

try:
    dataset.read()
    output = dataset.output
    if output is None or output.empty:
        print("Table is empty. Seeding example rows first.")
        dataset.input = seed_data
        dataset.create()
        dataset.read()
        output = dataset.output
except ReadError as exc:
    print(f"Read failed because the table is missing or unavailable: {exc.message}")
    print("Seeding example rows first.")
    dataset.input = seed_data
    dataset.create()
    dataset.read()
    output = dataset.output

print("Read output:")
print(output)
