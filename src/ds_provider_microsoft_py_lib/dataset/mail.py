"""
**File:** ``mail.py``
**Region:** ``ds_provider_microsoft_py_lib/dataset/mail``

Microsoft Graph Mail Message Dataset

This module implements a dataset that reads messages (and their attachments)
from a mailbox via the Microsoft Graph API. It is intended for mailboxes that
receive inbound files from external clients as email attachments.

Each read() call:
    1. Lists messages in the configured folder matching the configured filter
       (by default, unread messages only), expanding attachments inline.
    2. Optionally marks the returned messages as read.
    3. Optionally moves the returned messages to a "processed" folder.

Both post-read actions require the app registration to hold the Graph
application permission ``Mail.ReadWrite`` (with admin consent); read-only
use only needs ``Mail.Read``.

Example:
    >>> mail = MailMessage(
    ...     settings=MailMessageDatasetSettings(
    ...         mailbox="clients@contoso.com",
    ...         folder="inbox",
    ...         unread_only=True,
    ...         mark_as_read=True,
    ...         move_to_processed_folder="Processed",
    ...     ),
    ...     linked_service=MailLinkedService(
    ...         settings=MailLinkedServiceSettings(
    ...             tenant_id="tenant id",
    ...             client_id="client id",
    ...             client_secret="client secret",
    ...         ),
    ...         id=uuid.uuid4(),
    ...         name="testmailpackage",
    ...         version="0.0.1",
    ...         description="testmailpackage",
    ...     ),
    ...     id=uuid.uuid4(),
    ...     name="testmailmessage",
    ...     version="0.0.1",
    ...     description="testmailmessage",
    ... )
    >>> mail.read()
    >>> messages = mail.output  # pandas DataFrame, one row per message
    >>> messages.iloc[0]["attachments"]  # list[dict] with base64 content_bytes
"""

from dataclasses import dataclass, field
from typing import Any, Generic, NoReturn, TypeVar
from urllib.parse import quote

import pandas as pd
import requests
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.dataset import DatasetSettings, DatasetStorageFormatType, TabularDataset
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError, UpdateError
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer

from ..enums import ResourceType
from ..linked_service.mail import MailLinkedService

logger = Logger.get_logger(__name__, package=True)

REQUEST_TIMEOUT_SECONDS = 30


@dataclass(kw_only=True)
class MailMessageDatasetSettings(DatasetSettings):
    """
    Settings for reading messages from a mailbox via Microsoft Graph.
    """

    mailbox: str
    """User principal name or shared-mailbox address to read from, e.g. 'clients@contoso.com'."""
    folder: str = "inbox"
    """Well-known folder name (e.g. 'inbox') or a mailFolder id to read messages from."""
    unread_only: bool = True
    """If True, only messages with isRead=false are returned."""
    odata_filter: str | None = None
    """Additional raw OData $filter expression, ANDed with unread_only if both are set."""
    top: int = 50
    """Maximum number of messages to return per read() call."""
    include_attachments: bool = True
    """If True, file attachments are expanded inline as base64 content."""
    mark_as_read: bool = False
    """If True, messages returned by read() are marked isRead=true afterwards. Requires Mail.ReadWrite."""
    move_to_processed_folder: str | None = None
    """If set, messages returned by read() are moved to this folder (display name or id) afterwards.
    Requires Mail.ReadWrite."""


MailMessageDatasetSettingsType = TypeVar(
    "MailMessageDatasetSettingsType",
    bound=MailMessageDatasetSettings,
)
MailLinkedServiceType = TypeVar(
    "MailLinkedServiceType",
    bound=MailLinkedService[Any],
)


@dataclass(kw_only=True)
class MailMessage(
    TabularDataset[
        MailLinkedServiceType,
        MailMessageDatasetSettingsType,
        PandasSerializer,
        PandasDeserializer,
    ],
    Generic[MailLinkedServiceType, MailMessageDatasetSettingsType],
):
    linked_service: MailLinkedServiceType
    settings: MailMessageDatasetSettingsType

    serializer: PandasSerializer | None = field(
        default_factory=lambda: PandasSerializer(format=DatasetStorageFormatType.JSON),
    )
    deserializer: PandasDeserializer | None = field(
        default_factory=lambda: PandasDeserializer(format=DatasetStorageFormatType.JSON),
    )

    _processed_folder_id: str | None = field(default=None, init=False, repr=False, metadata={"serialize": False})

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the dataset.

        Returns:
             ResourceType
        """
        return ResourceType.MICROSOFT_MAIL_DATASET

    @property
    def _mailbox_segment(self) -> str:
        return quote(self.settings.mailbox, safe="@")

    @property
    def _messages_url(self) -> str:
        base_url = self.linked_service.connection.base_url
        folder = quote(self.settings.folder, safe="")
        return f"{base_url}users/{self._mailbox_segment}/mailFolders/{folder}/messages"

    def _build_filter(self) -> str | None:
        clauses = []
        if self.settings.unread_only:
            clauses.append("isRead eq false")
        if self.settings.odata_filter:
            clauses.append(f"({self.settings.odata_filter})")
        return " and ".join(clauses) if clauses else None

    def _list_messages(self) -> list[dict[str, Any]]:
        """
        List messages matching settings, paging until `top` is reached.

        Returns:
            list[dict[str, Any]]: Raw Graph message resources.
        Raises:
            ReadError: If listing messages fails.
        """
        session: requests.Session = self.linked_service.connection.session
        first_url = self._messages_url
        params: dict[str, Any] = {
            "$top": self.settings.top,
            "$orderby": "receivedDateTime asc",
        }
        odata_filter = self._build_filter()
        if odata_filter:
            params["$filter"] = odata_filter
        if self.settings.include_attachments:
            params["$expand"] = "attachments"

        messages: list[dict[str, Any]] = []
        url: str | None = first_url
        while url and len(messages) < self.settings.top:
            try:
                response = session.get(
                    url,
                    headers=self.linked_service.get_headers(),
                    params=params if url == first_url else None,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.error(f"Failed to list messages in mailbox {self.settings.mailbox}: {exc!s}")
                raise ReadError(
                    f"Failed to list messages in mailbox {self.settings.mailbox}: {exc!s}",
                    details=self.get_details(),
                    status_code=getattr(exc.response, "status_code", 500),
                ) from exc

            payload = response.json()
            messages.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")

        return messages[: self.settings.top]

    @staticmethod
    def _extract_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
        attachments = []
        for attachment in message.get("attachments", []) or []:
            if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
                logger.warning(
                    f"Skipping non-file attachment {attachment.get('name')} of type {attachment.get('@odata.type')}"
                )
                continue
            attachments.append(
                {
                    "name": attachment.get("name"),
                    "content_type": attachment.get("contentType"),
                    "size": attachment.get("size"),
                    "content_bytes": attachment.get("contentBytes"),  # base64-encoded
                }
            )
        return attachments

    def _to_dataframe(self, messages: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for message in messages:
            sender = (message.get("from") or {}).get("emailAddress", {})
            body = message.get("body") or {}
            rows.append(
                {
                    "id": message.get("id"),
                    "subject": message.get("subject"),
                    "from_address": sender.get("address"),
                    "from_name": sender.get("name"),
                    "received_datetime": message.get("receivedDateTime"),
                    "is_read": message.get("isRead"),
                    "has_attachments": message.get("hasAttachments"),
                    "body_preview": message.get("bodyPreview"),
                    "body_content": body.get("content"),
                    "body_content_type": body.get("contentType"),
                    "attachments": self._extract_attachments(message) if self.settings.include_attachments else [],
                }
            )
        return pd.DataFrame(rows)

    def _mark_messages_as_read(self, message_ids: list[str]) -> None:
        session: requests.Session = self.linked_service.connection.session
        base_url = self.linked_service.connection.base_url
        for message_id in message_ids:
            url = f"{base_url}users/{self._mailbox_segment}/messages/{message_id}"
            try:
                response = session.patch(
                    url,
                    headers=self.linked_service.get_headers(),
                    json={"isRead": True},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.error(f"Failed to mark message {message_id} as read: {exc!s}")
                raise UpdateError(
                    f"Failed to mark message {message_id} as read: {exc!s}", details=self.get_details()
                ) from exc

    def _resolve_processed_folder_id(self, display_name_or_id: str) -> str:
        if self._processed_folder_id:
            return self._processed_folder_id

        session: requests.Session = self.linked_service.connection.session
        base_url = self.linked_service.connection.base_url
        url = f"{base_url}users/{self._mailbox_segment}/mailFolders"
        try:
            response = session.get(
                url,
                headers=self.linked_service.get_headers(),
                params={"$filter": f"displayName eq '{display_name_or_id}'"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error(f"Failed to resolve mail folder '{display_name_or_id}': {exc!s}")
            raise UpdateError(
                f"Failed to resolve mail folder '{display_name_or_id}': {exc!s}", details=self.get_details()
            ) from exc

        results = response.json().get("value", [])
        # Falls back to treating the setting itself as an id/well-known name if no display-name match is found.
        folder_id = results[0]["id"] if results else display_name_or_id
        self._processed_folder_id = folder_id
        return folder_id

    def _move_messages(self, message_ids: list[str], destination: str) -> None:
        destination_id = self._resolve_processed_folder_id(destination)
        session: requests.Session = self.linked_service.connection.session
        base_url = self.linked_service.connection.base_url
        for message_id in message_ids:
            url = f"{base_url}users/{self._mailbox_segment}/messages/{message_id}/move"
            try:
                response = session.post(
                    url,
                    headers=self.linked_service.get_headers(),
                    json={"destinationId": destination_id},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.error(f"Failed to move message {message_id} to '{destination}': {exc!s}")
                raise UpdateError(
                    f"Failed to move message {message_id} to '{destination}': {exc!s}", details=self.get_details()
                ) from exc

    def read(self, **_kwargs: Any) -> None:
        """
        Read messages (and attachments) from the configured mailbox/folder.

        Returns:
            None
        Raises:
            ReadError: If listing messages fails.
            UpdateError: If marking-as-read or moving processed messages fails.
        """
        messages = self._list_messages()
        self.output = self._to_dataframe(messages)

        message_ids = [m["id"] for m in messages if m.get("id")]
        if message_ids and self.settings.mark_as_read:
            self._mark_messages_as_read(message_ids)
        if message_ids and self.settings.move_to_processed_folder:
            self._move_messages(message_ids, self.settings.move_to_processed_folder)

        logger.info(f"Read {len(self.output)} message(s) from mailbox {self.settings.mailbox}.")

    def create(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Create operation is not supported for Mail datasets")

    def update(self) -> NoReturn:
        raise NotSupportedError(
            "Update operation is not supported directly; use mark_as_read/move_to_processed_folder settings"
        )

    def upsert(self) -> NoReturn:
        raise NotSupportedError("Upsert operation is not supported for Mail datasets")

    def delete(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Delete operation is not supported for Mail datasets")

    def purge(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Purge operation is not supported for Mail datasets")

    def list(self) -> NoReturn:
        raise NotSupportedError("List operation is not supported for Mail datasets; use read() instead")

    def rename(self) -> NoReturn:
        raise NotSupportedError("Rename operation is not supported for Mail datasets")

    def close(self) -> None:
        """
        No need to close the linked service. Just to comply with the interface.

        Returns:
            None
        """
        pass

    def get_details(self) -> dict[str, Any]:
        """
        Get details of the dataset.

        Returns:
            dict[str, Any]: Details of the dataset.
        """
        return {
            "type": self.type.value,
            "mailbox": self.settings.mailbox,
            "folder": self.settings.folder,
        }
