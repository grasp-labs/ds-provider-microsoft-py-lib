"""
**File:** ``mail.py``
**Region:** ``ds_provider_microsoft_py_lib/dataset/mail``

Microsoft Graph Mail Message Dataset

This module implements a dataset that reads messages (and their attachments)
from a mailbox via the Microsoft Graph API. It is intended for mailboxes that
receive inbound files from external clients as email attachments.

``read()`` only lists messages in the configured folder matching the
configured filter (by default, unread messages only), expanding attachments
inline. It does not mutate the mailbox and is idempotent, per the dataset
contract.

Marking messages as read and moving them to another folder are separate,
explicit mutations: assign the messages to act on (e.g. ``mail.output`` from
a prior ``read()``, or a subset of it) to ``mail.input``, then call
``update()`` to mark them as read, or ``rename()`` to move them -- moving a
message to a different folder is, per the dataset contract, a rename of the
resource in the backend, not a read-time side effect or a generic update.
Both require the app registration to hold the Graph application permission
``Mail.ReadWrite`` (with admin consent); read-only use only needs
``Mail.Read``.

Example:
    >>> mail = MailMessage(
    ...     settings=MailMessageDatasetSettings(
    ...         mailbox="clients@contoso.com",
    ...         read=ReadSettings(folder="inbox", unread_only=True),
    ...         update=UpdateSettings(mark_as_read=True),
    ...         rename=RenameSettings(target_folder="Processed"),
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
    >>> mail.input = messages
    >>> mail.update()  # mark as read, per settings.update
    >>> mail.rename()  # move to settings.rename.target_folder
"""

from dataclasses import dataclass, field
from typing import Any, Generic, NoReturn, TypeVar
from urllib.parse import quote

import pandas as pd
import requests
from ds_common_logger_py_lib import Logger
from ds_common_serde_py_lib import Serializable
from ds_resource_plugin_py_lib.common.resource.dataset import DatasetSettings, DatasetStorageFormatType, TabularDataset
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError, RenameError, UpdateError
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer

from ..enums import ResourceType
from ..linked_service.mail import MailLinkedService

logger = Logger.get_logger(__name__, package=True)

REQUEST_TIMEOUT_SECONDS = 30


@dataclass(kw_only=True)
class ReadSettings(Serializable):
    """
    Settings specific to the read() operation.
    """

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


@dataclass(kw_only=True)
class UpdateSettings(Serializable):
    """
    Settings specific to the update() operation.
    """

    mark_as_read: bool = False
    """If True, messages in self.input are marked isRead=true. Requires Mail.ReadWrite."""


@dataclass(kw_only=True)
class RenameSettings(Serializable):
    """
    Settings specific to the rename() operation.
    """

    target_folder: str | None = None
    """Folder (display name or id) that messages in self.input are moved to. Requires Mail.ReadWrite."""


@dataclass(kw_only=True)
class MailMessageDatasetSettings(DatasetSettings):
    """
    Settings for reading messages from a mailbox via Microsoft Graph.
    """

    mailbox: str
    """User principal name or shared-mailbox address to operate on, e.g. 'clients@contoso.com'."""

    read: ReadSettings = field(default_factory=ReadSettings)
    """Settings for read()."""

    update: UpdateSettings = field(default_factory=UpdateSettings)
    """Settings for update()."""

    rename: RenameSettings = field(default_factory=RenameSettings)
    """Settings for rename()."""


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
        folder = quote(self.settings.read.folder, safe="")
        return f"{base_url}users/{self._mailbox_segment}/mailFolders/{folder}/messages"

    def _build_filter(self) -> str | None:
        clauses = []
        if self.settings.read.unread_only:
            clauses.append("isRead eq false")
        if self.settings.read.odata_filter:
            clauses.append(f"({self.settings.read.odata_filter})")
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
            "$top": self.settings.read.top,
            "$orderby": "receivedDateTime asc",
        }
        odata_filter = self._build_filter()
        if odata_filter:
            params["$filter"] = odata_filter
        if self.settings.read.include_attachments:
            params["$expand"] = "attachments"

        messages: list[dict[str, Any]] = []
        url: str | None = first_url
        while url and len(messages) < self.settings.read.top:
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

        return messages[: self.settings.read.top]

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
                    "attachments": self._extract_attachments(message)
                    if self.settings.read.include_attachments
                    else [],
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _escape_odata_string_literal(value: str) -> str:
        """
        Escape a value for safe interpolation into an OData string literal.

        Single quotes delimit OData string literals; a literal single quote
        within the value must be doubled, per the OData URL conventions.

        Returns:
            str: The value with embedded single quotes doubled.
        """
        return value.replace("'", "''")

    @staticmethod
    def _message_ids_from_input(input_df: pd.DataFrame) -> list[str]:
        """
        Extract well-formed Graph message ids from an input DataFrame's `id` column.

        Excludes NaN/None and non-string values, which pandas would otherwise
        treat as truthy and let flow into a mailbox mutation.

        Returns:
            list[str]: Non-empty string message ids.
        """
        return [message_id for message_id in input_df["id"].tolist() if isinstance(message_id, str) and message_id]

    def _mark_messages_as_read(self, message_ids: list[str]) -> None:
        session: requests.Session = self.linked_service.connection.session
        base_url = self.linked_service.connection.base_url
        for message_id in message_ids:
            url = f"{base_url}users/{self._mailbox_segment}/messages/{quote(message_id, safe='')}"
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
                params={"$filter": f"displayName eq '{self._escape_odata_string_literal(display_name_or_id)}'"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error(f"Failed to resolve mail folder '{display_name_or_id}': {exc!s}")
            raise RenameError(
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
            url = f"{base_url}users/{self._mailbox_segment}/messages/{quote(message_id, safe='')}/move"
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
                raise RenameError(
                    f"Failed to move message {message_id} to '{destination}': {exc!s}", details=self.get_details()
                ) from exc

    def read(self, **_kwargs: Any) -> None:
        """
        Read messages (and attachments) from the configured mailbox/folder.

        Does not mutate the mailbox. To mark the returned messages as read,
        assign them to ``self.input`` and call ``update()``; to move them to
        another folder, call ``rename()`` instead.

        Returns:
            None
        Raises:
            ReadError: If listing messages fails.
        """
        messages = self._list_messages()
        self.output = self._to_dataframe(messages)
        logger.info(f"Read {len(self.output)} message(s) from mailbox {self.settings.mailbox}.")

    def create(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Create operation is not supported for Mail datasets")

    def update(self, **_kwargs: Any) -> None:
        """
        Mark messages in ``self.input`` as read, per ``settings.update.mark_as_read``.
        Messages are matched by the Graph message ``id`` column, as produced
        by ``read()``.

        A no-op when ``self.input`` is empty, or when ``mark_as_read`` is disabled.

        Returns:
            None
        Raises:
            UpdateError: If ``self.input`` is missing an ``id`` column, or if
                marking messages as read fails.
        """
        if self.input is None or self.input.empty:
            logger.debug("Empty input provided to update(); returning without action.")
            self.output = self.input.copy() if self.input is not None else pd.DataFrame()
            return

        if "id" not in self.input.columns:
            raise UpdateError(
                "self.input must include an 'id' column with Graph message ids, as produced by read().",
                details=self.get_details(),
            )

        message_ids = self._message_ids_from_input(self.input)
        if message_ids and self.settings.update.mark_as_read:
            self._mark_messages_as_read(message_ids)

        self.output = self.input.copy()
        logger.info(f"Updated {len(message_ids)} message(s) in mailbox {self.settings.mailbox}.")

    def upsert(self) -> NoReturn:
        raise NotSupportedError("Upsert operation is not supported for Mail datasets")

    def delete(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Delete operation is not supported for Mail datasets")

    def purge(self, **_kwargs: Any) -> NoReturn:
        raise NotSupportedError("Purge operation is not supported for Mail datasets")

    def list(self) -> NoReturn:
        raise NotSupportedError("List operation is not supported for Mail datasets; use read() instead")

    def rename(self, **_kwargs: Any) -> None:
        """
        Move messages in ``self.input`` to ``settings.rename.target_folder``.
        Messages are matched by the Graph message ``id`` column, as produced
        by ``read()``.

        A no-op when ``self.input`` is empty. Not idempotent: calling this
        again with the same input after a successful move will fail, since
        the messages are no longer in their original location.

        Returns:
            None
        Raises:
            RenameError: If ``self.input`` is missing an ``id`` column,
                ``settings.rename.target_folder`` is not set, or moving
                messages fails.
        """
        if self.input is None or self.input.empty:
            logger.debug("Empty input provided to rename(); returning without action.")
            self.output = self.input.copy() if self.input is not None else pd.DataFrame()
            return

        if "id" not in self.input.columns:
            raise RenameError(
                "self.input must include an 'id' column with Graph message ids, as produced by read().",
                details=self.get_details(),
            )
        if not self.settings.rename.target_folder:
            raise RenameError(
                "settings.rename.target_folder must be set to move messages.",
                details=self.get_details(),
            )

        message_ids = self._message_ids_from_input(self.input)
        if message_ids:
            self._move_messages(message_ids, self.settings.rename.target_folder)

        self.output = self.input.copy()
        logger.info(
            f"Moved {len(message_ids)} message(s) in mailbox {self.settings.mailbox} "
            f"to '{self.settings.rename.target_folder}'."
        )

    def close(self) -> None:
        """
        Release the connection held by the linked service.

        Per contract: must be safe to call multiple times and never raise.

        Returns:
            None
        """
        try:
            self.linked_service.close()
        except Exception:
            logger.debug("Exception suppressed during close().", exc_info=True)

    def get_details(self) -> dict[str, Any]:
        """
        Get details of the dataset.

        Returns:
            dict[str, Any]: Details of the dataset.
        """
        return {
            "type": self.type.value,
            "mailbox": self.settings.mailbox,
            "folder": self.settings.read.folder,
        }
