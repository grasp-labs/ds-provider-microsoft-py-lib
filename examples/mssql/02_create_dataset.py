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
import uuid

import pandas as pd
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError

from ds_provider_microsoft_py_lib.dataset.mssql import MsSqlTableDatasetSettings, MsSqlTable
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
        table_name="my_table2",
        schema_name="dbo",
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

except ReadError as exc:
    assert exc.status_code == 404
    print("The table does not exist yet. ")
    row = pd.DataFrame({})

finally:
    print("Initial read:")
    print(row)

dataset.input = pd.DataFrame({
    "id": [1, 2, 3, 4, 5, 6],
    "color": ["Grays", "Red", "Blue", "Green", "Yellow", "Purple"],
})
dataset.create()

dataset.read()
output = dataset.output

print("Dataset created. The output of the dataset after creation is:")
print(output)

dataset.input = pd.DataFrame({
    "id": [4, 5, 6],
    "color": ["Green", "Yellow", "Purple"],
})
dataset.delete()
print("delete() method called. The output of the dataset after deletion is:")
dataset.read()
output = dataset.output

print(output)

dataset.input = pd.DataFrame({
    "color": ["Red"],
})
dataset.delete()
print("delete() method called. All rows matching the input should be removed. "
      "The output of the dataset after deletion is:")

dataset.read()
output = dataset.output
print(output)

dataset.settings.delete.delete_table = True
print("delete() method called. The output of the dataset after deletion is:")
dataset.delete()

try:
    dataset.read()
    print("Something went wrong, the table should have been deleted.")
except ReadError as exc:
    print(f"The table has been deleted.: {exc}")
