"""
**File**: test_mail.py
**Region**: tests/linked_service

Unit tests for MailLinkedService.

Covers:
- Settings validation and required-field errors
- Credential/token acquisition and caching
- Connection lifecycle: connect -> test_connection -> close
- Error wrapping: AuthenticationError, ConnectionError
- Context manager behavior
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import (
    AuthenticationError,
    ConnectionError,
)

from ds_provider_microsoft_py_lib.enums import ResourceType
from ds_provider_microsoft_py_lib.linked_service.mail import (
    GRAPH_SCOPE,
    MailLinkedService,
    MailLinkedServiceConnection,
    MailLinkedServiceSettings,
)


@pytest.fixture()
def settings() -> MailLinkedServiceSettings:
    return MailLinkedServiceSettings(
        tenant_id="tenant-id",
        client_id="client-id",
        client_secret="client-secret",
    )


def make_service(settings: MailLinkedServiceSettings) -> MailLinkedService:
    service = MailLinkedService.__new__(MailLinkedService)
    service.settings = settings
    service._session = None
    service._credential = None
    return service


class TestSettingsValidation:
    def test_check_settings_is_set_accepts_correct_type(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        service.check_settings_is_set()

    def test_check_settings_is_set_rejects_invalid_type(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        service.settings = object()  # type: ignore

        with pytest.raises(AttributeError):
            service.check_settings_is_set()

    @pytest.mark.parametrize(
        "field_name",
        ["tenant_id", "client_id", "client_secret"],
    )
    def test_check_settings_is_set_raises_when_missing_required_field(
        self, settings: MailLinkedServiceSettings, field_name: str
    ) -> None:
        setattr(settings, field_name, "")
        service = make_service(settings)

        with pytest.raises(AuthenticationError):
            service.check_settings_is_set()


class TestTypeAndBaseUrl:
    def test_type_property_returns_correct_enum(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        assert service.type == ResourceType.MICROSOFT_MAIL_LINKED_SERVICE

    def test_base_url_uses_default_api_version(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        assert service.base_url == "https://graph.microsoft.com/v1.0/"

    def test_base_url_uses_custom_api_version(self, settings: MailLinkedServiceSettings) -> None:
        settings.api_version = "beta"
        service = make_service(settings)
        assert service.base_url == "https://graph.microsoft.com/beta/"


class TestConnectionProperty:
    def test_connection_raises_if_not_connected(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        with pytest.raises(ConnectionError) as exc_info:
            _ = service.connection

        assert "Connection has not been established" in str(exc_info.value)

    def test_connection_returns_session_and_base_url_when_connected(
        self, settings: MailLinkedServiceSettings
    ) -> None:
        service = make_service(settings)
        session_mock = MagicMock()
        service._session = session_mock

        connection = service.connection

        assert isinstance(connection, MailLinkedServiceConnection)
        assert connection.session is session_mock
        assert connection.base_url == "https://graph.microsoft.com/v1.0/"


class TestGetCredential:
    def test_get_credential_raises_when_settings_incomplete(self, settings: MailLinkedServiceSettings) -> None:
        settings.client_secret = ""
        service = make_service(settings)

        with pytest.raises(AuthenticationError):
            service.get_credential()

    def test_get_credential_builds_client_secret_credential(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        with patch("ds_provider_microsoft_py_lib.linked_service.mail.ClientSecretCredential") as mock_cls:
            service.get_credential()

        mock_cls.assert_called_once_with(
            tenant_id="tenant-id",
            client_id="client-id",
            client_secret="client-secret",
        )


class TestGetAccessToken:
    def test_get_access_token_returns_token_string(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        credential_mock = MagicMock()
        credential_mock.get_token.return_value = AccessToken("access-token-value", 9999999999)
        service._credential = credential_mock

        token = service.get_access_token()

        assert token == "access-token-value"
        credential_mock.get_token.assert_called_once_with(GRAPH_SCOPE)

    def test_get_access_token_builds_credential_if_missing(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        credential_mock = MagicMock()
        credential_mock.get_token.return_value = AccessToken("token", 1)

        with patch.object(service, "get_credential", return_value=credential_mock) as get_credential_mock:
            token = service.get_access_token()

        get_credential_mock.assert_called_once()
        assert token == "token"
        assert service._credential is credential_mock

    def test_get_access_token_reuses_cached_credential(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        credential_mock = MagicMock()
        credential_mock.get_token.return_value = AccessToken("token", 1)
        service._credential = credential_mock

        with patch.object(service, "get_credential") as get_credential_mock:
            service.get_access_token()
            service.get_access_token()

        get_credential_mock.assert_not_called()
        assert credential_mock.get_token.call_count == 2

    def test_get_access_token_raises_authentication_error_on_failure(
        self, settings: MailLinkedServiceSettings
    ) -> None:
        service = make_service(settings)
        credential_mock = MagicMock()
        credential_mock.get_token.side_effect = ClientAuthenticationError("bad credentials")
        service._credential = credential_mock

        with pytest.raises(AuthenticationError) as exc_info:
            service.get_access_token()

        assert "Failed to authenticate with Microsoft Graph" in str(exc_info.value)


class TestGetHeaders:
    def test_get_headers_returns_bearer_token(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        with patch.object(service, "get_access_token", return_value="abc123"):
            headers = service.get_headers()

        assert headers == {"Authorization": "Bearer abc123"}


class TestConnectMethod:
    def test_connect_sets_session_and_credential(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        credential_mock = MagicMock()

        with (
            patch.object(service, "get_credential", return_value=credential_mock),
            patch.object(service, "get_access_token", return_value="token"),
        ):
            service.connect()

        assert service._credential is credential_mock
        assert service._session is not None

    def test_connect_raises_when_settings_incomplete(self, settings: MailLinkedServiceSettings) -> None:
        settings.tenant_id = ""
        service = make_service(settings)

        with pytest.raises(AuthenticationError):
            service.connect()

    def test_connect_is_idempotent(self, settings: MailLinkedServiceSettings) -> None:
        """connect() must be idempotent - calling twice must not leak the existing session."""
        service = make_service(settings)
        credential_mock = MagicMock()

        with (
            patch.object(service, "get_credential", return_value=credential_mock) as get_credential_mock,
            patch.object(service, "get_access_token", return_value="token") as get_token_mock,
        ):
            service.connect()
            first_session = service._session
            service.connect()

        assert service._session is first_session
        get_credential_mock.assert_called_once()
        get_token_mock.assert_called_once()


class TestTestConnectionMethod:
    def test_test_connection_success_when_not_connected(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        with patch.object(service, "connect") as connect_mock:

            def _connect_side_effect() -> None:
                service._session = MagicMock()

            connect_mock.side_effect = _connect_side_effect
            ok, msg = service.test_connection()

        connect_mock.assert_called_once()
        assert ok is True
        assert msg == "Connection successful."

    def test_test_connection_success_when_already_connected(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        service._session = MagicMock()

        with patch.object(service, "get_access_token", return_value="token") as get_token_mock:
            ok, msg = service.test_connection()

        get_token_mock.assert_called_once()
        assert ok is True
        assert msg == "Connection successful."

    def test_test_connection_returns_false_on_failure(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        service._session = MagicMock()

        with patch.object(service, "get_access_token", side_effect=AuthenticationError("boom")):
            ok, msg = service.test_connection()

        assert ok is False
        assert "boom" in msg


class TestCloseMethod:
    def test_close_closes_session_and_clears_it(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        session_mock = MagicMock()
        service._session = session_mock

        service.close()

        session_mock.close.assert_called_once()
        assert service._session is None

    def test_close_is_noop_when_not_connected(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        service.close()  # should not raise

        assert service._session is None


class TestContextManager:
    def test_enter_returns_self(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)

        assert service.__enter__() is service

    def test_exit_closes_connection(self, settings: MailLinkedServiceSettings) -> None:
        service = make_service(settings)
        session_mock = MagicMock()
        service._session = session_mock

        service.__exit__(None, None, None)

        session_mock.close.assert_called_once()
        assert service._session is None


class TestInternalFieldsExcludedFromInitAndRepr:
    def test_constructor_does_not_accept_internal_fields(self, settings: MailLinkedServiceSettings) -> None:
        """_session/_credential are runtime-only; callers must not be able to set them via the constructor."""
        service = MailLinkedService(
            settings=settings, id=uuid.uuid4(), name="test", version="0.0.1", description="test"
        )

        assert service._session is None
        assert service._credential is None

    def test_repr_excludes_internal_fields(self, settings: MailLinkedServiceSettings) -> None:
        service = MailLinkedService(
            settings=settings, id=uuid.uuid4(), name="test", version="0.0.1", description="test"
        )
        service._session = MagicMock()
        service._credential = MagicMock()

        representation = repr(service)

        assert "_session" not in representation
        assert "_credential" not in representation
