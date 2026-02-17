import uuid

import pandas as pd
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError

from ds_provider_microsoft_py_lib.dataset.mssql import MssqlTableDatasetSettings, MssqlTable
from ds_provider_microsoft_py_lib.linked_service.mssql import MssqlLinkedService, MsSqlLinkedServiceSettings

linked_service = MssqlLinkedService(
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
dataset = MssqlTable(
    linked_service=linked_service,
    settings=MssqlTableDatasetSettings(
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
