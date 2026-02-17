"""
**File:** ``mssql.py``
**Region:** ``ds_provider_microsoft_py_lib/linked_service/mssql``

Micsosoft SQL Linked Service

This module implements a linked service for Miscrosoft SQL, allowing users to connect to and interact with
SQL Server instance.

Example:
>>>linked_service = MssqlLinkedService(
...        settings=MsSqlLinkedServiceSettings(
...            server="account name",
...            database="account key",
...            username="account key",
...            password="account key",
...        ),
...        id=uuid.uuid4(),
...        name="testmssqlpackage",
...        version="0.0.1",
...        description="testmssqlpackage"
...    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar
from urllib.parse import quote_plus

from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from sqlalchemy import create_engine, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

from ..enums import ResourceType

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class MssqlLinkedServiceSettings(LinkedServiceSettings):
    """
    The object containing the Microsoft SQL Server linked service settings.
    """

    server: str
    database: str
    username: str
    password: str = field(metadata={"mask": True})
    port: int = 1433
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: bool = True
    trust_server_certificate: bool = False
    connection_timeout: int = 30


MssqlLinkedServiceSettingsType = TypeVar(
    "MssqlLinkedServiceSettingsType",
    bound=MssqlLinkedServiceSettings,
)


@dataclass(kw_only=True)
class MssqlLinkedService(LinkedService[MssqlLinkedServiceSettingsType], Generic[MssqlLinkedServiceSettingsType]):
    """
    Linked service for connecting to AzureLinkedService.
    """

    settings: MssqlLinkedServiceSettingsType
    _engine: Engine | None = field(init=True, repr=False, default=None)

    def check_settings_is_set(self) -> None:
        """
        Check if settings are set correctly.

        Returns:
            None
        Raises:
            AttributeError: If settings are not set correctly.
        """
        if not isinstance(self.settings, MssqlLinkedServiceSettings):
            raise AttributeError("settings not set.")

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the linked service.

        Returns:
             ResourceType
        """
        return ResourceType.MICROSOFT_SQL_LINKED_SERVICE

    @property
    def engine(self) -> Engine:
        """
        Get the Engine instance.

        Returns:
            Engine
        Raises:
            ConnectionError: If engine is not yet created.
        """
        if not self._engine:
            raise ConnectionError("Engine is not yet created. Call connect() first.")
        return self._engine

    def _get_connection_string(self) -> str:
        """
        Build the ODBC connection string.

        Returns:
            str: The ODBC connection string.
        """
        conn_str = (
            f"DRIVER={{{self.settings.driver}}};"
            f"SERVER={self.settings.server},{self.settings.port};"
            f"DATABASE={self.settings.database};"
            f"UID={self.settings.username};"
            f"PWD={self.settings.password};"
            f"Encrypt={'yes' if self.settings.encrypt else 'no'};"
            f"TrustServerCertificate={'yes' if self.settings.trust_server_certificate else 'no'};"
            f"Connection Timeout={self.settings.connection_timeout};"
        )
        return conn_str

    def _create_engine(self) -> Engine:
        """
        Connect to SQL Server and return SQLAlchemy Engine.

        Returns:
            Engine
        """
        logger.debug("Connecting to SQL Server...")

        conn_str = self._get_connection_string()
        url = f"mssql+pyodbc:///?odbc_connect={quote_plus(conn_str)}"

        return create_engine(url, echo=False)

    def connect(self) -> None:
        """

        Connect to Microsoft SQL Server using pyodbc directly.

        Returns:
            None
        """
        self.check_settings_is_set()
        self._engine: Engine = self._create_engine()
        logger.debug("Connected to Microsoft SQL Server.")

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection to Microsoft SQL Server.

        Returns:
            tuple[bool, str]
        """
        try:
            if not self._engine:
                self.connect()
            engine = self._engine
            if engine is None:
                raise ConnectionError("Engine is not yet created. Call connect() first.")
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
            return True, "Connection successfully tested"
        except Exception as exc:
            logger.error(f"Failed to test connection: {exc}", exc_info=True)
            return False, str(exc)

    def close(self) -> None:
        """
        No need to close the linked service. Just to comply with the interface.

        Returns:
            None
        """
        if self._engine:
            self._engine.dispose()  # todo: verify if this is the correct way to close the engine
            logger.debug("Connection to SQL Server closed.")
