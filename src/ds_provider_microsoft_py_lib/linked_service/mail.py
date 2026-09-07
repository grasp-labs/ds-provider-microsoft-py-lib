"""
**File:** ``mail.py``
**Region:** ``ds_provider_microsoft_py_lib/linked_service/mail``

Microsoft Graph Mail Linked Service

This module implements a linked service for reading mail (messages and
attachments) from a mailbox in Microsoft 365 / Exchange Online via the
Microsoft Graph API, using Azure AD service principal (client credentials)
authentication.

Example:
>>>linked_service = MailLinkedService(
...        settings=MailLinkedServiceSettings(
...            tenant_id="tenant id",
...            client_id="client id",
...            client_secret="client secret",
...        ),
...        id=uuid.uuid4(),
...        name="testmailpackage",
...        version="0.0.1",
...        description="testmailpackage"
...    )
>>> linked_service.connect()
"""

from dataclasses import dataclass, field
from typing import Generic, TypeVar

import requests
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import ClientSecretCredential
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import (
    AuthenticationError,
    ConnectionError,
)

from ..enums import ResourceType

logger = Logger.get_logger(__name__, package=True)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"

_AUTH_REQUIRED_MESSAGE = "Tenant ID, Client ID and Client Secret are required for Microsoft Graph authentication."


@dataclass(kw_only=True)
class MailLinkedServiceSettings(LinkedServiceSettings):
    """
    Settings for the Microsoft Graph mail linked service.

    Authenticates as an Azure AD application (service principal) via client
    credentials. The app registration must be granted the application
    permission ``Mail.Read`` (read-only), or ``Mail.ReadWrite`` if a dataset
    marks messages as read or moves them between folders, with admin consent.
    """

    tenant_id: str
    client_id: str
    client_secret: str = field(metadata={"mask": True})
    api_version: str = "v1.0"


MailLinkedServiceSettingsType = TypeVar(
    "MailLinkedServiceSettingsType",
    bound=MailLinkedServiceSettings,
)


@dataclass(kw_only=True)
class MailLinkedServiceConnection:
    """
    The object containing the Microsoft Graph mail linked service connection.
    """

    session: requests.Session
    base_url: str


@dataclass(kw_only=True)
class MailLinkedService(LinkedService[MailLinkedServiceSettingsType], Generic[MailLinkedServiceSettingsType]):
    """
    Linked service for connecting to Microsoft Graph for mail operations.
    """

    settings: MailLinkedServiceSettingsType
    _session: requests.Session | None = field(default=None, metadata={"serialize": False})
    _credential: ClientSecretCredential | None = field(default=None, metadata={"serialize": False})

    def check_settings_is_set(self) -> None:
        """
        Check if settings are set correctly.

        Returns:
            None
        Raises:
            AttributeError: If settings are not set correctly.
            AuthenticationError: If tenant_id, client_id or client_secret is missing.
        """
        if not isinstance(self.settings, MailLinkedServiceSettings):
            raise AttributeError("settings not set.")
        if not (self.settings.tenant_id and self.settings.client_id and self.settings.client_secret):
            raise AuthenticationError(_AUTH_REQUIRED_MESSAGE)

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the linked service.

        Returns:
             ResourceType
        """
        return ResourceType.MICROSOFT_MAIL_LINKED_SERVICE

    @property
    def base_url(self) -> str:
        """
        Get the Microsoft Graph base URL for the configured API version.

        Returns:
            str
        """
        return f"https://graph.microsoft.com/{self.settings.api_version}/"

    @property
    def connection(self) -> MailLinkedServiceConnection:
        """
        Get the connection object for Microsoft Graph mail.

        Returns:
            MailLinkedServiceConnection
        Raises:
            ConnectionError: If connect() has not been called.
        """
        if self._session is None:
            raise ConnectionError(
                message="Connection has not been established. Call connect() first.",
                details={"provider": self.type.value},
            )
        return MailLinkedServiceConnection(session=self._session, base_url=self.base_url)

    def get_credential(self) -> ClientSecretCredential:
        """
        Build the credential used to authenticate against Microsoft Graph.

        Returns:
            ClientSecretCredential
        Raises:
            AuthenticationError: If tenant_id, client_id or client_secret is missing.
        """
        if not (self.settings.tenant_id and self.settings.client_id and self.settings.client_secret):
            raise AuthenticationError(_AUTH_REQUIRED_MESSAGE)
        return ClientSecretCredential(
            tenant_id=self.settings.tenant_id,
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
        )

    def get_access_token(self) -> str:
        """
        Acquire a Microsoft Graph access token.

        Relies on azure-identity's internal MSAL token cache, so calling this
        on every request does not cost a network round-trip once a valid
        token has been cached.

        Returns:
            str
        Raises:
            AuthenticationError: If a token cannot be acquired.
        """
        if self._credential is None:
            self._credential = self.get_credential()
        try:
            token = self._credential.get_token(GRAPH_SCOPE)
        except ClientAuthenticationError as exc:
            logger.error(f"Failed to acquire Microsoft Graph access token: {exc}", exc_info=True)
            raise AuthenticationError(f"Failed to authenticate with Microsoft Graph: {exc!s}") from exc
        return token.token

    def get_headers(self) -> dict[str, str]:
        """
        Build the Authorization header for a Microsoft Graph request.

        Returns:
            dict[str, str]
        """
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def connect(self) -> None:
        """
        Connect to Microsoft Graph, verifying credentials can mint an access token.

        Returns:
            None
        """
        self.check_settings_is_set()
        self._credential = self.get_credential()
        self.get_access_token()
        self._session = requests.Session()
        logger.debug("Connected to Microsoft Graph for mail operations.")

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection to Microsoft Graph by acquiring an access token.

        Returns:
            tuple[bool, str]
        """
        try:
            if self._session is None:
                self.connect()
            else:
                self.get_access_token()
            logger.debug("Tested connection to Microsoft Graph successfully.")
            return True, "Connection successful."
        except Exception as exc:
            logger.error(f"Failed to test connection: {exc}", exc_info=True)
            return False, str(exc)

    def close(self) -> None:
        """
        Release the underlying HTTP session.

        Returns:
            None
        """
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "MailLinkedService[MailLinkedServiceSettingsType]":
        """
        Enter context manager.

        Returns:
            MailLinkedService: Returns self for use in with statement.
        """
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """
        Exit context manager and close the connection.

        Returns:
            None
        """
        self.close()
