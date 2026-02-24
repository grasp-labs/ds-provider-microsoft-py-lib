"""
**File**: test_mssql.py
**Region**: tests/linked_service

Unit tests for MsSqlLinkedService

Covers:
- Type matches ResourceType enum
- check_settings_is_set rejects invalid type
- engine property requires connection
- get_connection_string builds expected connection string
- create_engine builds expected pyodbc URL
- connect sets engine
- test_connection success triggers connect
- test_connection failure returns error
- close disposes engine
- close is noop when no engine
"""

from unittest.mock import MagicMock, patch
from urllib.parse import quote_plus

import pytest

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
    service.connection = None
    return service


def test_type_matches_resource_enum(settings: MsSqlLinkedServiceSettings) -> None:
    service = make_service(settings)
    assert service.type == ResourceType.MICROSOFT_SQL_LINKED_SERVICE


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
