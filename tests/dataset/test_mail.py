"""
**File**: test_mail.py
**Region**: tests/dataset

Unit tests for MailMessage dataset implementation.
"""

from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError, RenameError, UpdateError
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError

from ds_provider_microsoft_py_lib.dataset.mail import (
    MailMessage,
    MailMessageDatasetSettings,
    ReadSettings,
    RenameSettings,
    UpdateSettings,
)
from ds_provider_microsoft_py_lib.enums import ResourceType

BASE_URL = "https://graph.microsoft.com/v1.0/"


@pytest.fixture()
def settings() -> MailMessageDatasetSettings:
    return MailMessageDatasetSettings(mailbox="clients@contoso.com")


@pytest.fixture()
def linked_service() -> MagicMock:
    svc = MagicMock()
    svc.connection.session = MagicMock()
    svc.connection.base_url = BASE_URL
    svc.get_headers.return_value = {"Authorization": "Bearer test-token"}
    return svc


def make_dataset(settings: MailMessageDatasetSettings, linked_service: MagicMock) -> MailMessage:
    dataset = MailMessage.__new__(MailMessage)
    dataset.settings = settings
    dataset.linked_service = linked_service
    dataset.input = None  # type: ignore
    dataset.output = None  # type: ignore
    dataset._processed_folder_id = None
    return dataset


def make_response(json_data: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


def make_message(message_id: str = "msg-1", *, with_attachments: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {
        "id": message_id,
        "subject": "Invoice attached",
        "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
        "receivedDateTime": "2026-01-01T00:00:00Z",
        "isRead": False,
        "hasAttachments": with_attachments,
        "bodyPreview": "preview",
        "body": {"content": "<p>body</p>", "contentType": "html"},
    }
    if with_attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "invoice.pdf",
                "contentType": "application/pdf",
                "size": 1234,
                "contentBytes": "YmFzZTY0",
            },
            {
                "@odata.type": "#microsoft.graph.itemAttachment",
                "name": "embedded-email.eml",
            },
        ]
    return message


class TestTypeProperty:
    def test_type_property_returns_correct_enum(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        assert dataset.type == ResourceType.MICROSOFT_MAIL_DATASET


class TestMailboxSegmentAndUrl:
    def test_mailbox_segment_preserves_at_symbol(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        assert dataset._mailbox_segment == "clients@contoso.com"

    def test_messages_url_builds_expected_path(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        assert dataset._messages_url == f"{BASE_URL}users/clients@contoso.com/mailFolders/inbox/messages"


class TestBuildFilter:
    def test_build_filter_defaults_to_unread_only(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        assert dataset._build_filter() == "isRead eq false"

    def test_build_filter_returns_none_when_no_filters(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.unread_only = False
        dataset = make_dataset(settings, linked_service)
        assert dataset._build_filter() is None

    def test_build_filter_combines_unread_only_and_odata_filter(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.odata_filter = "hasAttachments eq true"
        dataset = make_dataset(settings, linked_service)
        assert dataset._build_filter() == "isRead eq false and (hasAttachments eq true)"

    def test_build_filter_with_only_odata_filter(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.unread_only = False
        settings.read.odata_filter = "hasAttachments eq true"
        dataset = make_dataset(settings, linked_service)
        assert dataset._build_filter() == "(hasAttachments eq true)"


class TestListMessages:
    def test_list_messages_single_page_success(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        message = make_message()
        linked_service.connection.session.get.return_value = make_response({"value": [message]})

        messages = dataset._list_messages()

        assert messages == [message]
        call_kwargs = linked_service.connection.session.get.call_args.kwargs
        assert call_kwargs["params"]["$top"] == settings.read.top
        assert call_kwargs["params"]["$filter"] == "isRead eq false"
        assert call_kwargs["params"]["$expand"] == "attachments"
        assert call_kwargs["headers"] == {"Authorization": "Bearer test-token"}

    def test_list_messages_paginates_until_next_link_missing(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        first_page = make_response(
            {"value": [make_message("msg-1")], "@odata.nextLink": f"{BASE_URL}next-page"}
        )
        second_page = make_response({"value": [make_message("msg-2")]})
        linked_service.connection.session.get.side_effect = [first_page, second_page]

        messages = dataset._list_messages()

        assert [m["id"] for m in messages] == ["msg-1", "msg-2"]
        assert linked_service.connection.session.get.call_count == 2
        second_call_kwargs = linked_service.connection.session.get.call_args_list[1].kwargs
        assert second_call_kwargs["params"] is None

    def test_list_messages_stops_once_top_reached(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.top = 1
        dataset = make_dataset(settings, linked_service)
        first_page = make_response(
            {"value": [make_message("msg-1"), make_message("msg-2")], "@odata.nextLink": f"{BASE_URL}next-page"}
        )
        linked_service.connection.session.get.return_value = first_page

        messages = dataset._list_messages()

        assert len(messages) == 1
        linked_service.connection.session.get.assert_called_once()

    def test_list_messages_raises_read_error_on_request_exception(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.side_effect = requests.RequestException("network error")

        with pytest.raises(ReadError) as exc_info:
            dataset._list_messages()

        assert "Failed to list messages" in str(exc_info.value)
        assert exc_info.value.details["mailbox"] == "clients@contoso.com"

    def test_list_messages_excludes_expand_when_attachments_disabled(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.include_attachments = False
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": []})

        dataset._list_messages()

        call_kwargs = linked_service.connection.session.get.call_args.kwargs
        assert "$expand" not in call_kwargs["params"]


class TestExtractAttachments:
    def test_extract_attachments_includes_file_attachments(self) -> None:
        message = make_message(with_attachments=True)

        attachments = MailMessage._extract_attachments(message)

        assert len(attachments) == 1
        assert attachments[0]["name"] == "invoice.pdf"
        assert attachments[0]["content_bytes"] == "YmFzZTY0"

    def test_extract_attachments_skips_non_file_attachments(self) -> None:
        message = {
            "attachments": [
                {"@odata.type": "#microsoft.graph.itemAttachment", "name": "embedded.eml"},
            ]
        }

        attachments = MailMessage._extract_attachments(message)

        assert attachments == []

    def test_extract_attachments_handles_missing_attachments_key(self) -> None:
        assert MailMessage._extract_attachments({}) == []


class TestToDataFrame:
    def test_to_dataframe_includes_attachments_by_default(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        message = make_message(with_attachments=True)

        df = dataset._to_dataframe([message])

        assert len(df) == 1
        assert df.iloc[0]["from_address"] == "sender@example.com"
        assert len(df.iloc[0]["attachments"]) == 1

    def test_to_dataframe_excludes_attachments_when_disabled(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.read.include_attachments = False
        dataset = make_dataset(settings, linked_service)
        message = make_message(with_attachments=True)

        df = dataset._to_dataframe([message])

        assert df.iloc[0]["attachments"] == []


class TestMarkMessagesAsRead:
    def test_mark_messages_as_read_success(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.patch.return_value = make_response({})

        dataset._mark_messages_as_read(["msg-1", "msg-2"])

        assert linked_service.connection.session.patch.call_count == 2
        first_call = linked_service.connection.session.patch.call_args_list[0]
        assert first_call.kwargs["json"] == {"isRead": True}

    def test_mark_messages_as_read_raises_update_error_on_failure(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.patch.side_effect = requests.RequestException("boom")

        with pytest.raises(UpdateError):
            dataset._mark_messages_as_read(["msg-1"])

    def test_mark_messages_as_read_url_encodes_message_id(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        """Graph message ids can contain '+', '/' and '=', which must be percent-encoded in the URL path."""
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.patch.return_value = make_response({})

        dataset._mark_messages_as_read(["AAMk/ADY3+ZDMw=="])

        called_url = linked_service.connection.session.patch.call_args.args[0]
        assert "AAMk/ADY3+ZDMw==" not in called_url
        assert "AAMk%2FADY3%2BZDMw%3D%3D" in called_url


class TestResolveProcessedFolderId:
    def test_returns_cached_folder_id_without_request(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset._processed_folder_id = "cached-id"

        result = dataset._resolve_processed_folder_id("Processed")

        assert result == "cached-id"
        linked_service.connection.session.get.assert_not_called()

    def test_resolves_folder_id_by_display_name(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response(
            {"value": [{"id": "resolved-folder-id"}]}
        )

        result = dataset._resolve_processed_folder_id("Processed")

        assert result == "resolved-folder-id"
        assert dataset._processed_folder_id == "resolved-folder-id"

    def test_falls_back_to_given_name_when_not_found(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": []})

        result = dataset._resolve_processed_folder_id("Processed")

        assert result == "Processed"

    def test_raises_rename_error_on_request_failure(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.side_effect = requests.RequestException("boom")

        with pytest.raises(RenameError):
            dataset._resolve_processed_folder_id("Processed")

    def test_escapes_single_quotes_in_folder_display_name(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        """A folder name containing an apostrophe (e.g. "Client's") must not break the OData $filter."""
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": []})

        dataset._resolve_processed_folder_id("Client's Invoices")

        call_kwargs = linked_service.connection.session.get.call_args.kwargs
        assert call_kwargs["params"]["$filter"] == "displayName eq 'Client''s Invoices'"


class TestMoveMessages:
    def test_move_messages_success(self, settings: MailMessageDatasetSettings, linked_service: MagicMock) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset._processed_folder_id = "folder-id"
        linked_service.connection.session.post.return_value = make_response({})

        dataset._move_messages(["msg-1", "msg-2"], "Processed")

        assert linked_service.connection.session.post.call_count == 2
        first_call = linked_service.connection.session.post.call_args_list[0]
        assert first_call.kwargs["json"] == {"destinationId": "folder-id"}

    def test_move_messages_raises_rename_error_on_failure(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset._processed_folder_id = "folder-id"
        linked_service.connection.session.post.side_effect = requests.RequestException("boom")

        with pytest.raises(RenameError):
            dataset._move_messages(["msg-1"], "Processed")

    def test_move_messages_url_encodes_message_id(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset._processed_folder_id = "folder-id"
        linked_service.connection.session.post.return_value = make_response({})

        dataset._move_messages(["AAMk/ADY3+ZDMw=="], "Processed")

        called_url = linked_service.connection.session.post.call_args.args[0]
        assert "AAMk/ADY3+ZDMw==" not in called_url
        assert "AAMk%2FADY3%2BZDMw%3D%3D" in called_url


class TestRead:
    def test_read_populates_output_dataframe(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": [make_message("msg-1")]})

        dataset.read()

        assert isinstance(dataset.output, pd.DataFrame)
        assert len(dataset.output) == 1

    def test_read_with_no_messages_produces_empty_output(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": []})

        dataset.read()

        assert isinstance(dataset.output, pd.DataFrame)
        assert dataset.output.empty

    def test_read_does_not_mark_as_read_or_move(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        """read() must never mutate the mailbox, regardless of update/rename settings."""
        settings.update.mark_as_read = True
        settings.rename.target_folder = "Processed"
        dataset = make_dataset(settings, linked_service)
        linked_service.connection.session.get.return_value = make_response({"value": [make_message("msg-1")]})

        dataset.read()

        linked_service.connection.session.patch.assert_not_called()
        linked_service.connection.session.post.assert_not_called()


class TestUpdate:
    def test_update_empty_input_returns_immediately(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame()

        dataset.update()

        assert dataset.output is not None
        assert dataset.output.empty
        linked_service.connection.session.patch.assert_not_called()

    def test_update_raises_when_id_column_missing(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"subject": ["hi"]})

        with pytest.raises(UpdateError):
            dataset.update()

    def test_update_is_noop_when_mark_as_read_disabled(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1"]})

        dataset.update()

        linked_service.connection.session.patch.assert_not_called()
        assert len(dataset.output) == 1

    def test_update_marks_as_read_when_enabled(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.update.mark_as_read = True
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1"]})
        linked_service.connection.session.patch.return_value = make_response({})

        dataset.update()

        linked_service.connection.session.patch.assert_called_once()

    def test_update_populates_output_from_input(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        df = pd.DataFrame({"id": ["msg-1", "msg-2"]})
        dataset.input = df

        dataset.update()

        assert dataset.output is not None
        assert len(dataset.output) == 2
        assert dataset.output is not df

    def test_update_excludes_non_string_ids(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        """A NaN id (e.g. from a filtered/reindexed DataFrame) must never reach a mailbox mutation."""
        settings.update.mark_as_read = True
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1", float("nan"), None, ""]})
        linked_service.connection.session.patch.return_value = make_response({})

        dataset.update()

        linked_service.connection.session.patch.assert_called_once()
        called_url = linked_service.connection.session.patch.call_args.args[0]
        assert "msg-1" in called_url


class TestRename:
    def test_rename_empty_input_returns_immediately(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame()

        dataset.rename()

        assert dataset.output is not None
        assert dataset.output.empty
        linked_service.connection.session.post.assert_not_called()

    def test_rename_raises_when_id_column_missing(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.rename.target_folder = "Processed"
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"subject": ["hi"]})

        with pytest.raises(RenameError):
            dataset.rename()

    def test_rename_raises_when_target_folder_not_configured(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1"]})

        with pytest.raises(RenameError):
            dataset.rename()

    def test_rename_moves_messages_to_target_folder(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.rename.target_folder = "Processed"
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1"]})
        linked_service.connection.session.get.return_value = make_response(
            {"value": [{"id": "processed-folder-id"}]}
        )
        linked_service.connection.session.post.return_value = make_response({})

        dataset.rename()

        linked_service.connection.session.post.assert_called_once()
        assert linked_service.connection.session.post.call_args.kwargs["json"] == {
            "destinationId": "processed-folder-id"
        }

    def test_rename_populates_output_from_input(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.rename.target_folder = "Processed"
        dataset = make_dataset(settings, linked_service)
        df = pd.DataFrame({"id": ["msg-1", "msg-2"]})
        dataset.input = df
        linked_service.connection.session.get.return_value = make_response(
            {"value": [{"id": "processed-folder-id"}]}
        )
        linked_service.connection.session.post.return_value = make_response({})

        dataset.rename()

        assert dataset.output is not None
        assert len(dataset.output) == 2
        assert dataset.output is not df

    def test_rename_excludes_non_string_ids(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        settings.rename.target_folder = "Processed"
        dataset = make_dataset(settings, linked_service)
        dataset.input = pd.DataFrame({"id": ["msg-1", float("nan"), None, ""]})
        linked_service.connection.session.get.return_value = make_response(
            {"value": [{"id": "processed-folder-id"}]}
        )
        linked_service.connection.session.post.return_value = make_response({})

        dataset.rename()

        linked_service.connection.session.post.assert_called_once()
        called_url = linked_service.connection.session.post.call_args.args[0]
        assert "msg-1" in called_url


class TestUnsupportedOperations:
    @pytest.mark.parametrize("method_name", ["create", "upsert", "delete", "purge", "list"])
    def test_unsupported_operations_raise_not_supported_error(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock, method_name: str
    ) -> None:
        dataset = make_dataset(settings, linked_service)

        with pytest.raises(NotSupportedError):
            getattr(dataset, method_name)()


class TestCloseAndDetails:
    def test_close_delegates_to_linked_service(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)

        dataset.close()

        linked_service.close.assert_called_once()

    def test_close_suppresses_linked_service_exceptions(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)
        linked_service.close.side_effect = RuntimeError("boom")

        dataset.close()  # should not raise

    def test_close_is_idempotent(self, settings: MailMessageDatasetSettings, linked_service: MagicMock) -> None:
        dataset = make_dataset(settings, linked_service)

        dataset.close()
        dataset.close()

        assert linked_service.close.call_count == 2

    def test_get_details_returns_expected_dict(
        self, settings: MailMessageDatasetSettings, linked_service: MagicMock
    ) -> None:
        dataset = make_dataset(settings, linked_service)

        details = dataset.get_details()

        assert details == {
            "type": ResourceType.MICROSOFT_MAIL_DATASET.value,
            "mailbox": "clients@contoso.com",
            "folder": "inbox",
        }


class TestSettingsStructure:
    def test_default_settings_have_expected_defaults(self) -> None:
        settings = MailMessageDatasetSettings(mailbox="clients@contoso.com")

        assert isinstance(settings.read, ReadSettings)
        assert isinstance(settings.update, UpdateSettings)
        assert isinstance(settings.rename, RenameSettings)
        assert settings.read.folder == "inbox"
        assert settings.read.unread_only is True
        assert settings.update.mark_as_read is False
        assert settings.rename.target_folder is None
