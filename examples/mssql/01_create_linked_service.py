import uuid

from ds_provider_microsoft_py_lib.linked_service.mssql import MssqlLinkedService, MsSqlLinkedServiceSettings

settings = MsSqlLinkedServiceSettings(
    server="localhost",
    database="master",
    username="sa",
    password="dockerStrongPwd123",
    trust_server_certificate=True,
)
linked_service = MssqlLinkedService(settings=settings, id=uuid.uuid4(), name="testmssqlpackage", version="0.0.1",
                                    description="testmssqlpackage")

result = linked_service.test_connection()
print(result)
