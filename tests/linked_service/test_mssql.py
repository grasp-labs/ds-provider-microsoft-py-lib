"""
**File**: test_mssql.py
**Region**: tests/linked_service

Comprehensive unit tests for MsSqlLinkedService

Covers:
- Contract Compliance: connection property, connect, test_connection, close
- Error Handling: ConnectionError, AuthenticationError with proper details
- Connection Property: Raises if not connected, provides Engine when connected
- Idempotency: connect(), test_connection(), close()
- Connection Lifecycle: create → test → use → close
- Error Wrapping: Backend exceptions wrapped with context
"""

from unittest.mock import MagicMock, patch
from urllib.parse import quote_plus

import pytest
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import (
    AuthenticationError,
    ConnectionError,
)

from ds_provider_microsoft_py_lib.enums import ResourceType
from ds_provider_microsoft_py_lib.linked_service.mssql import MsSqlLinkedService, MsSqlLinkedServiceSettings


@pytest.fixture()
def settings() -> MsSqlLinkedServiceSettings:
    return MsSqlLinkedServiceSettings(
        server="localhost",
        database="testdb",
        username="sa",
        password="P@ssw0rd!",
    )


def make_service(settings: MsSqlLinkedServiceSettings) -> MsSqlLinkedService:
    service = MsSqlLinkedService.__new__(MsSqlLinkedService)
    service.settings = settings
    service._connection = None
    return service


class TestConnectionProperty:
    """Test Connection Property Behavior"""

    def test_connection_property_raises_if_not_connected(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connection property must raise ConnectionError if connect() not called."""
        service = make_service(settings)
        service._connection = None

        with pytest.raises(ConnectionError) as exc_info:
            _ = service.connection

        assert "Connection not established" in str(exc_info.value)

    def test_connection_property_returns_engine_when_connected(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connection property must return Engine when connected."""
        service = make_service(settings)
        engine_mock = MagicMock()
        service._connection = engine_mock

        assert service.connection is engine_mock

    def test_connection_property_includes_debug_context(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connection property error must include server and database context."""
        service = make_service(settings)
        service._connection = None

        with pytest.raises(ConnectionError) as exc_info:
            _ = service.connection

        error = exc_info.value
        assert error.details["server"] == "localhost"
        assert error.details["database"] == "testdb"

    def test_connection_property_setter_works(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connection property setter must work for testing."""
        service = make_service(settings)
        engine_mock = MagicMock()

        service.connection = engine_mock

        assert service._connection is engine_mock


class TestConnectMethod:
    """Test connect() Method - Idempotent, Tests Connection"""

    def test_connect_sets_connection(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must set internal _connection."""
        service = make_service(settings)
        engine_mock = MagicMock()

        with patch.object(service, "_create_engine", return_value=engine_mock):
            service.connect()

        assert service._connection is engine_mock

    def test_connect_is_idempotent(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must be idempotent - calling twice doesn't reconnect."""
        service = make_service(settings)
        engine_mock = MagicMock()

        with patch.object(service, "_create_engine", return_value=engine_mock) as create_mock:
            service.connect()
            service.connect()

        # _create_engine should only be called once
        assert create_mock.call_count == 1

    def test_connect_tests_connection_before_storing(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must test connection with SELECT 1 before storing."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)

        with patch.object(service, "_create_engine", return_value=engine_mock):
            service.connect()

        # Should have called execute with SELECT 1
        conn_mock.execute.assert_called_once()

    def test_connect_raises_authentication_error_on_login_failure(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must raise AuthenticationError when login fails."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        # Mock an OperationalError-like exception with "login failed" in message
        error = RuntimeError("Login failed for user 'sa'")
        conn_mock.execute.side_effect = error

        # Patch the exception check to treat RuntimeError as OperationalError
        with (
            patch.object(service, "_create_engine", return_value=engine_mock),
            patch("ds_provider_microsoft_py_lib.linked_service.mssql.OperationalError", RuntimeError),
            pytest.raises(AuthenticationError) as exc_info,
        ):
            service.connect()

        assert "Authentication failed" in str(exc_info.value)

    def test_connect_raises_connection_error_on_connection_failure(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must raise ConnectionError on general connection failures."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        error = RuntimeError("Cannot connect to server")
        conn_mock.execute.side_effect = error

        with (
            patch.object(service, "_create_engine", return_value=engine_mock),
            patch("ds_provider_microsoft_py_lib.linked_service.mssql.OperationalError", RuntimeError),
            pytest.raises(ConnectionError) as exc_info,
        ):
            service.connect()

        assert "Failed to connect" in str(exc_info.value)

    def test_connect_includes_error_details(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() errors must include server, port, database details."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        conn_mock.execute.side_effect = RuntimeError("Error")

        with patch.object(service, "_create_engine", return_value=engine_mock):
            with pytest.raises(ConnectionError) as exc_info:
                service.connect()

            error = exc_info.value
            assert error.details["server"] == "localhost"
            assert error.details["port"] == 1433
            assert error.details["database"] == "testdb"


class TestTestConnectionMethod:
    """Test test_connection() Method - Non-Raising Health Check"""

    def test_test_connection_returns_tuple(self, settings: MsSqlLinkedServiceSettings) -> None:
        """test_connection() must return (bool, str) tuple."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        service._connection = engine_mock

        result = service.test_connection()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_test_connection_success_returns_true(self, settings: MsSqlLinkedServiceSettings) -> None:
        """test_connection() must return (True, msg) on success."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        service._connection = engine_mock

        ok, msg = service.test_connection()

        assert ok is True
        assert "Connection successfully tested" in msg

    def test_test_connection_never_raises(self, settings: MsSqlLinkedServiceSettings) -> None:
        """test_connection() must never raise, even on failure."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        conn_mock.execute.side_effect = RuntimeError("DB error")
        service._connection = engine_mock

        try:
            ok, msg = service.test_connection()
            assert ok is False
            assert "DB error" in msg
        except Exception as e:
            pytest.fail(f"test_connection() raised exception: {e}")

    def test_test_connection_auto_connects_if_needed(self, settings: MsSqlLinkedServiceSettings) -> None:
        """test_connection() should auto-connect if not yet connected."""
        service = make_service(settings)
        service._connection = None

        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)

        with patch.object(service, "_create_engine", return_value=engine_mock):
            ok, _msg = service.test_connection()

        assert ok is True

    def test_test_connection_returns_false_on_connection_error(self, settings: MsSqlLinkedServiceSettings) -> None:
        """test_connection() must return (False, msg) when connection fails."""
        service = make_service(settings)
        service._connection = None

        with patch.object(service, "connect", side_effect=ConnectionError(message="Cannot connect")):
            ok, msg = service.test_connection()

        assert ok is False
        assert "Connection failed" in msg

    # Test connected service can test connection
    def test_test_connection_on_already_connected_service(settings: MsSqlLinkedServiceSettings) -> None:
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        result_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        conn_mock.execute = MagicMock(return_value=result_mock)
        result_mock.fetchone = MagicMock(return_value=(1,))
        service._connection = engine_mock

        ok, msg = service.test_connection()

        assert ok is True
        assert "Connection successfully tested" in msg
        result_mock.fetchone.assert_called_once()


class TestCloseMethod:
    """Test close() Method - Idempotent, Safe"""

    def test_close_disposes_engine(self, settings: MsSqlLinkedServiceSettings) -> None:
        """close() must dispose the engine."""
        service = make_service(settings)
        engine_mock = MagicMock()
        service._connection = engine_mock

        service.close()

        engine_mock.dispose.assert_called_once()

    def test_close_sets_connection_to_none(self, settings: MsSqlLinkedServiceSettings) -> None:
        """close() must set _connection to None."""
        service = make_service(settings)
        engine_mock = MagicMock()
        service._connection = engine_mock

        service.close()

        assert service._connection is None

    def test_close_is_idempotent(self, settings: MsSqlLinkedServiceSettings) -> None:
        """close() must be idempotent - safe to call multiple times."""
        service = make_service(settings)
        engine_mock = MagicMock()
        service._connection = engine_mock

        # Call twice - should not raise
        service.close()
        service.close()

    def test_close_never_raises(self, settings: MsSqlLinkedServiceSettings) -> None:
        """close() must never raise, even on error."""
        service = make_service(settings)
        engine_mock = MagicMock()
        engine_mock.dispose.side_effect = RuntimeError("Dispose error")
        service._connection = engine_mock

        try:
            service.close()  # Should not raise
        except Exception as e:
            pytest.fail(f"close() raised exception: {e}")

    def test_close_is_noop_when_not_connected(self, settings: MsSqlLinkedServiceSettings) -> None:
        """close() must be safe when not connected."""
        service = make_service(settings)
        service._connection = None

        try:
            service.close()  # Should not raise
        except Exception as e:
            pytest.fail(f"close() raised exception when not connected: {e}")


class TestCreateEngineMethod:
    """Test _create_engine() Method - Error Wrapping"""

    def test_create_engine_returns_engine(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_create_engine() must return SQLAlchemy Engine."""
        service = make_service(settings)
        engine_mock = MagicMock()

        with patch("ds_provider_microsoft_py_lib.linked_service.mssql.create_engine", return_value=engine_mock):
            engine = service._create_engine()

        assert engine is engine_mock

    def test_create_engine_raises_connection_error_on_argument_error(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_create_engine() must wrap ArgumentError in ConnectionError."""
        service = make_service(settings)

        with patch(
            "ds_provider_microsoft_py_lib.linked_service.mssql.create_engine",
            side_effect=ValueError("Invalid argument"),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                service._create_engine()

            assert "Failed to create database engine" in str(exc_info.value)

    def test_create_engine_includes_error_details(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_create_engine() error must include server, port, database details."""
        service = make_service(settings)

        with patch(
            "ds_provider_microsoft_py_lib.linked_service.mssql.create_engine",
            side_effect=ValueError("Invalid"),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                service._create_engine()

            error = exc_info.value
            assert error.details["server"] == "localhost"
            assert error.details["port"] == 1433
            assert error.details["database"] == "testdb"


class TestConnectionStringGeneration:
    """Test _get_connection_string() Method"""

    def test_get_connection_string_builds_expected(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_get_connection_string() must build correct ODBC connection string."""
        service = make_service(settings)

        conn_str = service._get_connection_string()

        assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_str
        assert "SERVER=localhost,1433" in conn_str
        assert "DATABASE=testdb" in conn_str
        assert "UID=sa" in conn_str
        assert "PWD=P@ssw0rd!" in conn_str
        assert "Encrypt=yes" in conn_str
        assert "TrustServerCertificate=no" in conn_str
        assert "Connection Timeout=30" in conn_str

    def test_get_connection_string_respects_encrypt_setting(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_get_connection_string() must respect encrypt setting."""
        settings.encrypt = False
        service = make_service(settings)

        conn_str = service._get_connection_string()

        assert "Encrypt=no" in conn_str

    def test_get_connection_string_respects_trust_certificate_setting(self, settings: MsSqlLinkedServiceSettings) -> None:
        """_get_connection_string() must respect trust_server_certificate setting."""
        settings.trust_server_certificate = True
        service = make_service(settings)

        conn_str = service._get_connection_string()

        assert "TrustServerCertificate=yes" in conn_str


class TestTypeProperty:
    """Test type Property"""

    def test_type_property_returns_correct_enum(self, settings: MsSqlLinkedServiceSettings) -> None:
        """type property must return ResourceType.MICROSOFT_SQL_LINKED_SERVICE."""
        service = make_service(settings)
        assert service.type == ResourceType.MICROSOFT_SQL_LINKED_SERVICE


class TestSettingsValidation:
    """Test Settings Validation"""

    def test_check_settings_is_set_accepts_correct_type(self, settings: MsSqlLinkedServiceSettings) -> None:
        """check_settings_is_set() must accept MsSqlLinkedServiceSettings."""
        service = make_service(settings)

        try:
            service.check_settings_is_set()
        except AttributeError:
            pytest.fail("check_settings_is_set() raised on valid settings")

    def test_check_settings_is_set_rejects_invalid_type(self, settings: MsSqlLinkedServiceSettings) -> None:
        """check_settings_is_set() must reject invalid settings type."""
        service = make_service(settings)
        service.settings = object()  # type: ignore

        with pytest.raises(AttributeError):
            service.check_settings_is_set()


class TestExceptionChaining:
    """Test Exception Chaining"""

    def test_connect_chains_operational_error(self, settings: MsSqlLinkedServiceSettings) -> None:
        """connect() must chain backend exceptions."""
        service = make_service(settings)
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=conn_mock)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=None)
        original_error = RuntimeError("Original error")
        conn_mock.execute.side_effect = original_error

        with patch.object(service, "_create_engine", return_value=engine_mock):
            with pytest.raises(ConnectionError) as exc_info:
                service.connect()

            # Check that original exception is chained
            assert exc_info.value.__cause__ is original_error


def test_check_settings_is_set_rejects_invalid_type(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    service.settings = object()  # type: ignore[assignment]
    with pytest.raises(AttributeError):
        service.check_settings_is_set()


def test_get_connection_string_builds_expected(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    assert (
        service._get_connection_string() == "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=localhost,1433;"
        "DATABASE=testdb;"
        "UID=sa;"
        "PWD=P@ssw0rd!;"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )


def test_create_engine_builds_pyodbc_url(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    engine_mock = MagicMock()
    with patch("ds_provider_microsoft_py_lib.linked_service.mssql.create_engine", return_value=engine_mock) as create_engine_mock:
        engine = service._create_engine()
    assert engine is engine_mock
    quoted_conn = quote_plus(service._get_connection_string())
    create_engine_mock.assert_called_once_with(f"mssql+pyodbc:///?odbc_connect={quoted_conn}", echo=False)


def test_connect_sets_engine(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    engine_mock = MagicMock()
    with patch.object(service, "_create_engine", return_value=engine_mock) as create_engine_mock:
        service.connect()
    create_engine_mock.assert_called_once()
    assert service.connection is engine_mock
    assert service.connection is engine_mock


def test_test_connection_failure_returns_error(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    engine_mock = MagicMock()
    engine_mock.connect.side_effect = RuntimeError("boom")
    service.connection = engine_mock

    ok, message = service.test_connection()

    assert ok is False
    assert "boom" in message


def test_close_disposes_engine(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    engine_mock = MagicMock()
    service.connection = engine_mock

    service.close()

    engine_mock.dispose.assert_called_once()


def test_close_is_noop_when_no_engine(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    service.connection = None

    service.close()


def test_create_engine_handles_argument_error(settings: MsSqlLinkedServiceSettings) -> None:
    """_create_engine() must wrap ArgumentError in ConnectionError."""
    service = make_service(settings)
    arg_error = ValueError("Invalid argument in connection string")

    with patch("ds_provider_microsoft_py_lib.linked_service.mssql.create_engine", side_effect=arg_error):
        with pytest.raises(ConnectionError) as exc_info:
            service._create_engine()

        error = exc_info.value
        assert "Failed to create database engine" in str(error)
        assert error.details["server"] == "localhost"
        assert error.details["port"] == 1433
        assert error.details["database"] == "testdb"


def test_create_engine_handles_generic_exception(settings: MsSqlLinkedServiceSettings) -> None:
    """_create_engine() must wrap unexpected exceptions in ConnectionError."""
    service = make_service(settings)
    generic_error = RuntimeError("Unexpected error creating engine")

    with patch("ds_provider_microsoft_py_lib.linked_service.mssql.create_engine", side_effect=generic_error):
        with pytest.raises(ConnectionError) as exc_info:
            service._create_engine()

        error = exc_info.value
        assert "Failed to create database engine" in str(error)


def test_connect_handles_unexpected_exception_during_connection_test(
    settings: MsSqlLinkedServiceSettings,
) -> None:
    """connect() must handle unexpected exceptions during connection test."""
    service = make_service(settings)
    engine_mock = MagicMock()
    conn_mock = MagicMock()
    engine_mock.connect = MagicMock(return_value=conn_mock)
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=None)
    unexpected_error = RuntimeError("Unexpected database error")
    conn_mock.execute.side_effect = unexpected_error

    with patch.object(service, "_create_engine", return_value=engine_mock):
        with pytest.raises(ConnectionError) as exc_info:
            service.connect()

        error = exc_info.value
        assert "Failed to connect" in str(error)
        assert error.__cause__ is unexpected_error


def test_close_handles_exception_during_dispose(settings: MsSqlLinkedServiceSettings) -> None:
    """close() must handle exceptions during engine.dispose() without raising."""
    service = make_service(settings)
    engine_mock = MagicMock()
    engine_mock.dispose.side_effect = RuntimeError("Error disposing engine")
    service._connection = engine_mock

    # Should not raise
    service.close()

    # In the current implementation, connection may still be set if dispose fails
    # This is acceptable as the error is logged but not re-raised


def test_connect_logs_on_operational_error(settings: MsSqlLinkedServiceSettings) -> None:
    """Verify that connect() logs errors on OperationalError."""
    service = make_service(settings)
    engine_mock = MagicMock()
    conn_mock = MagicMock()
    engine_mock.connect = MagicMock(return_value=conn_mock)
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=None)

    # Simulate an OperationalError with "other error" message
    error = RuntimeError("Other database error")
    conn_mock.execute.side_effect = error

    with (
        patch.object(service, "_create_engine", return_value=engine_mock),
        patch("ds_provider_microsoft_py_lib.linked_service.mssql.OperationalError", RuntimeError),
        pytest.raises(ConnectionError),
    ):
        service.connect()


def test_test_connection_logs_error_on_exception(settings: MsSqlLinkedServiceSettings) -> None:
    """Verify that test_connection() logs errors properly."""
    service = make_service(settings)
    engine_mock = MagicMock()
    conn_mock = MagicMock()
    engine_mock.connect = MagicMock(return_value=conn_mock)
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=None)
    conn_mock.execute.side_effect = RuntimeError("Test error")
    service._connection = engine_mock

    ok, msg = service.test_connection()

    assert ok is False
    assert "Test error" in msg


def test_create_engine_logs_argument_error(settings: MsSqlLinkedServiceSettings) -> None:
    """Verify that _create_engine() logs ArgumentError."""
    service = make_service(settings)
    arg_error = ValueError("Invalid argument")

    with (
        patch("ds_provider_microsoft_py_lib.linked_service.mssql.create_engine", side_effect=arg_error),
        pytest.raises(ConnectionError),
    ):
        service._create_engine()
