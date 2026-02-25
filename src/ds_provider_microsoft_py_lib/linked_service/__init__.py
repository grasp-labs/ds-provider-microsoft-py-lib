"""
**File:** ``__init__.py``
**Region:** ``ds-provider-microsoft-py-lib/linked_service``

Linked service module for Microsoft provider.

Example:
>>> linked_service = MsSqlLinkedService(
...     settings=MsSqlLinkedServiceSettings(
...         server="account name",
...         database="database",
...         username="username",
...         password="password",
...     ),
...     id=uuid.uuid4(),
...     name="testmssqlpackage",
...     version="0.0.1",
...     description="testmssqlpackage"
... )
>>> linked_service.connect()
"""

from .mssql import MsSqlLinkedService, MsSqlLinkedServiceSettings

__all__ = [
    "MsSqlLinkedService",
    "MsSqlLinkedServiceSettings",
]
