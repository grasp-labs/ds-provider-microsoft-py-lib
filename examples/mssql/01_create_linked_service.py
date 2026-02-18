"""
**File:** ``01_create_linked_service.py``
**Region:** ``examples/01_create_linked_service.py``

Example 01: Connect to Microsoft SQL Server using AzureLinkedService
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create an instance of MsSqlLinkedServiceSettings with the necessary connection parameters for a Microsoft SQL Server instance.
- Create an instance of MsSqlLinkedService using the settings and additional metadata such as id, name, version, and description.
- Test the connection to the Microsoft SQL Server instance using the test_connection method of the MssqlLinkedService instance and print the result.
"""
import uuid

from ds_provider_microsoft_py_lib.linked_service.mssql import MsSqlLinkedService, MsSqlLinkedServiceSettings

settings = MsSqlLinkedServiceSettings(
    server="localhost",
    database="master",
    username="sa",
    password="dockerStrongPwd123",
    trust_server_certificate=True,
)
linked_service = MsSqlLinkedService(settings=settings, id=uuid.uuid4(), name="testmssqlpackage", version="0.0.1",
                                    description="testmssqlpackage")

result = linked_service.test_connection()
print(result)
