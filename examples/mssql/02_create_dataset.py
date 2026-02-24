"""
**File:** ``02_create_dataset.py``
**Region:** ``examples/02_create_dataset.py``

Example 02: Create and manage a dataset using MsSqlTable
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create an instance of `MsSqlTableDatasetSettings` with the necessary parameters for a Microsoft SQL Server table.
- Create an instance of `MsSqlTable` using the settings, a linked service, and additional metadata such as id, name,
version, and description.
- Connect to the linked service and attempt to read from the dataset,
handling the case where the table does not exist yet.
- Create the dataset by providing input data and calling the `create()` method, then read and print the output.
- Delete specific rows from the dataset using the `delete()` method with input data,
and print the output after deletion.
- Delete the entire table by setting `delete_table` to True in the dataset settings and calling the `delete()` method,
then attempt to read from the dataset to confirm deletion.
"""

import datetime
import uuid

import pandas as pd
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError

from ds_provider_microsoft_py_lib.dataset.mssql import MsSqlTableDatasetSettings, MsSqlTable, CreateSettings
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
        create=CreateSettings(
                        mode="replace",
                        index=False,
                    )
    ),
    id=uuid.uuid4(),
    name="testmssqldataset",
    version="0.0.1",
    description="testmssqldataset",
)
dataset.linked_service.connect()
try:
    dataset.read()
    row = dataset.output
    print(row)

except ReadError as exc:
    assert exc.status_code == 404
    print("The table does not exist yet. ")
    row = pd.DataFrame({})

finally:
    print("Initial read:")
    print(row)

dataset.list()
print("List of tables in the database:")
print(dataset.output)

dataset.input = pd.DataFrame(
    {
        "id": pd.Series([1, 2, 3, 4, 5, 6], dtype="Int64"),
        "color": pd.Series(["Grays", "Red", "Blue", "Green", "Yellow", "Purple"], dtype="category"),
        "dcoll": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]).tz_localize(
            "UTC"
        ),
        "dtimes": [datetime.datetime.now() for _ in range(6)],
        "active": pd.Series([True, False, True, True, False, True], dtype="boolean"),
        "score": pd.Series([10.5, 8.2, 7.0, 9.1, 6.4, 5.5], dtype="float32"),
        "delta": pd.to_timedelta(["1 days", "2 days", "3 days", "4 days", "5 days", "6 days"]),
    }
)
dataset.create()

dataset.read()
output = dataset.output

print("Dataset created. The output of the dataset after creation is:")
print(output)

dataset.input = pd.DataFrame(
    {
        "id": [4, 5, 6],
        "color": ["Green", "Yellow", "Purple"],
    }
)
dataset.delete()
print("delete() method called. The output of the dataset after deletion is:")
dataset.read()
output = dataset.output

print(output)

dataset.input = pd.DataFrame(
    {
        "color": ["Red"],
    }
)
dataset.delete()
print("delete() method called. All rows matching the input should be removed. The output of the dataset after deletion is:")

dataset.read()
output = dataset.output
print(output)

print("delete() method called. The output of the dataset after deletion is:")
dataset.purge()

try:
    dataset.read()
    print("Something went wrong, the table should have been deleted.")
except ReadError as exc:
    print(f"The table has been deleted.: {exc}")
