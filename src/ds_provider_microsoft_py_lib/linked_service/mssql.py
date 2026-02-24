"""
**File:** ``mssql.py``
**Region:** ``ds_provider_microsoft_py_lib/linked_service/mssql``

Microsoft SQL Linked Service

This module implements a linked service for Microsoft SQL, allowing users to connect to and interact with
SQL Server instance.

Example:
>>>linked_service = MsSqlLinkedService(
...        settings=MsSqlLinkedServiceSettings(
...            server="account name",
...            database="database",
...            username="username",
...            password="password",
...        ),
...        id=uuid.uuid4(),
...        name="testmssqlpackage",
...        version="0.0.1",
...        description="testmssqlpackage"
...    )
>>> linked_service.connect()
"""

from dataclasses import dataclass, field
from typing import Generic, TypeVar
from urllib.parse import quote_plus

from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import (
    AuthenticationError,
    ConnectionError,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError, OperationalError

from ..enums import ResourceType

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class MsSqlLinkedServiceSettings(LinkedServiceSettings):
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


MsSqlLinkedServiceSettingsType = TypeVar(
    "MsSqlLinkedServiceSettingsType",
    bound=MsSqlLinkedServiceSettings,
)


@dataclass(kw_only=True)
class MsSqlLinkedService(LinkedService[MsSqlLinkedServiceSettingsType], Generic[MsSqlLinkedServiceSettingsType]):
    """
    Linked service for connecting to Microsoft SQL Server.

    This linked service manages connections to SQL Server databases.
    It handles authentication, connection lifecycle, and error handling
    according to the linked service contract.

    Example:
        >>> settings = MsSqlLinkedServiceSettings(
        ...     server="localhost",
        ...     database="mydb",
        ...     username="user",
        ...     password="pass"
        ... )
        >>> service = MsSqlLinkedService(
        ...     settings=settings,
        ...     id=uuid.uuid4(),
        ...     name="my_mssql",
        ...     version="0.0.1"
        ... )
        >>> service.connect()
        >>> with service as svc:
        ...     data = svc.connection.execute(...)
    """

    settings: MsSqlLinkedServiceSettingsType
    _connection: Engine | None = field(default=None, init=False, repr=False, metadata={"serialize": False})

    def check_settings_is_set(self) -> None:
        """
        Check if settings are set correctly.

        Returns:
            None
        Raises:
            AttributeError: If settings are not set correctly.
        """
        if not isinstance(self.settings, MsSqlLinkedServiceSettings):
            raise AttributeError("settings not set.")

    @property
    def connection(self) -> Engine:
        """
        Get the backend connection (SQLAlchemy Engine).

        Returns:
            Engine: The SQLAlchemy Engine instance.

        Raises:
            ConnectionError: If connect() has not been called.
        """
        if self._connection is None:
            raise ConnectionError(
                message="Connection not established. Call connect() first.",
                details={"server": self.settings.server, "database": self.settings.database},
            )
        return self._connection

    @connection.setter
    def connection(self, value: Engine | None) -> None:
        """
        Set the backend connection (for testing purposes).

        Args:
            value: The Engine instance or None.
        """
        self._connection = value

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the linked service.

        Returns:
             ResourceType
        """
        return ResourceType.MICROSOFT_SQL_LINKED_SERVICE

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
            Engine: The SQLAlchemy Engine instance.

        Raises:
            ConnectionError: If the engine cannot be created.
            AuthenticationError: If credentials are invalid.
        """
        logger.debug("Creating SQLAlchemy engine for SQL Server...")

        try:
            conn_str = self._get_connection_string()
            url = f"mssql+pyodbc:///?odbc_connect={quote_plus(conn_str)}"
            engine = create_engine(url, echo=False)
            logger.debug("SQLAlchemy engine created successfully.")
            return engine
        except ArgumentError as exc:
            # This typically indicates connection string or configuration issues
            logger.error(f"Invalid connection string or configuration: {exc}", exc_info=True)
            raise ConnectionError(
                message=f"Failed to create database engine: {exc!s}",
                details={
                    "server": self.settings.server,
                    "port": self.settings.port,
                    "database": self.settings.database,
                },
            ) from exc
        except Exception as exc:
            logger.error(f"Unexpected error creating engine: {exc}", exc_info=True)
            raise ConnectionError(
                message=f"Failed to create database engine: {exc!s}",
                details={
                    "server": self.settings.server,
                    "port": self.settings.port,
                    "database": self.settings.database,
                },
            ) from exc

    def connect(self) -> None:
        """
        Establish a connection to Microsoft SQL Server.

        The result is stored internally and accessible via the `connection` property.

        Returns:
            None

        Raises:
            ConnectionError: If the connection cannot be established.
            AuthenticationError: If credentials are invalid.

        Rules:
            - Idempotent: Calling connect() on an already-connected service reuses the connection.
            - Must authenticate using credentials from self.settings.
            - Must fail loudly if connection cannot be established.
        """
        # Idempotent: reuse existing connection
        if self._connection is not None:
            logger.debug("Connection already established, reusing.")
            return

        self.check_settings_is_set()

        try:
            # Create the engine
            engine = self._create_engine()

            # Test the connection before storing it
            logger.debug("Testing connection to SQL Server...")
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self._connection = engine
            logger.info(
                f"Successfully connected to SQL Server: {self.settings.server}:{self.settings.port}/{self.settings.database}"
            )
        except OperationalError as exc:
            # OperationalError typically indicates authentication or connection issues
            error_str = str(exc).lower()
            if "login failed" in error_str or "authentication" in error_str:
                logger.error(f"Authentication failed: {exc}", exc_info=True)
                raise AuthenticationError(
                    message=f"Authentication failed for user '{self.settings.username}': {exc!s}",
                    details={
                        "server": self.settings.server,
                        "database": self.settings.database,
                        "username": self.settings.username,
                    },
                ) from exc
            else:
                logger.error(f"Connection failed: {exc}", exc_info=True)
                raise ConnectionError(
                    message=f"Failed to connect to SQL Server: {exc!s}",
                    details={
                        "server": self.settings.server,
                        "port": self.settings.port,
                        "database": self.settings.database,
                    },
                ) from exc
        except (ConnectionError, AuthenticationError):
            # Re-raise our own exception types
            raise
        except Exception as exc:
            logger.error(f"Unexpected error during connection: {exc}", exc_info=True)
            raise ConnectionError(
                message=f"Failed to connect to SQL Server: {exc!s}",
                details={
                    "server": self.settings.server,
                    "port": self.settings.port,
                    "database": self.settings.database,
                },
            ) from exc

    def test_connection(self) -> tuple[bool, str]:
        """
        Verify that the connection to Microsoft SQL Server is healthy.

        Performs a lightweight check against the backend (a simple SELECT 1 query).
        This method does not raise on connection failure -- instead returns
        (False, "error message"). Exceptions are reserved for unexpected internal errors.

        Returns:
            tuple[bool, str] -- On success: (True, "Connection successfully tested").
            On failure: (False, "reason").

        Rules:
            - Must not raise on connection failure.
            - Must not modify any data.
            - Should complete quickly.
            - Idempotent: Yes.
        """
        try:
            # If not yet connected, attempt to connect first
            if self._connection is None:
                logger.debug("Connection not established, attempting to connect for test...")
                try:
                    self.connect()
                except (ConnectionError, AuthenticationError) as exc:
                    return False, f"Connection failed: {exc.message}"
                except Exception as exc:
                    return False, f"Unexpected error during connection: {exc!s}"

            # Test the existing connection with a simple query
            with self.connection.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()

            logger.debug("Connection test successful.")
            return True, "Connection successfully tested"
        except Exception as exc:
            logger.error(f"Failed to test connection: {exc}", exc_info=True)
            return False, f"Connection test failed: {exc!s}"

    def close(self) -> None:
        """
        Release connections, sessions, or handles held by the linked service.

        This method is safe to call multiple times and does not raise even if
        the connection is already closed. Called automatically by `__exit__`
        when using a context manager.

        Returns:
            None

        Rules:
            - Must release any open connections, sessions, or handles.
            - Must not raise if the connection is already closed.
            - Must be safe to call multiple times.
            - Idempotent: Yes.
        """
        try:
            if self._connection is not None:
                self._connection.dispose()
                self._connection = None
                logger.debug("Connection to SQL Server closed.")
        except Exception as exc:
            logger.error(f"Error closing connection: {exc}", exc_info=True)
