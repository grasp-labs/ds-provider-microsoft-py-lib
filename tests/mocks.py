"""
Mock utilities for testing dataset and linked service implementations.
"""

from __future__ import annotations

import uuid
from typing import Any, cast
from unittest.mock import MagicMock

import pandas as pd

from ds_provider_microsoft_py_lib.dataset.mail import MailMessage, MailMessageDatasetSettings
from ds_provider_microsoft_py_lib.dataset.mssql import MsSqlTable, MsSqlTableDatasetSettings, ReadSettings
from ds_provider_microsoft_py_lib.linked_service.mail import MailLinkedService
from ds_provider_microsoft_py_lib.linked_service.mssql import MsSqlLinkedService


def create_mock_mail_linked_service(base_url: str = "https://graph.microsoft.com/v1.0/") -> MagicMock:
    """
    Create a mock MailLinkedService for testing.

    Returns:
        MagicMock: A mocked linked service with connection and headers configured.
    """
    session = MagicMock()
    mock_service = MagicMock(spec=MailLinkedService)
    mock_service.connection.session = session
    mock_service.connection.base_url = base_url
    mock_service.get_headers.return_value = {"Authorization": "Bearer test-token"}
    return mock_service


def create_mock_mail_dataset(
    mailbox: str = "clients@contoso.com",
    folder: str = "inbox",
    linked_service: MailLinkedService | None = None,
    **settings_kwargs: Any,
) -> MailMessage:
    """
    Create a mock MailMessage dataset for testing.

    Args:
        mailbox: The mailbox address.
        folder: The mail folder to read from.
        linked_service: Optional linked service. If None, creates a mock one.
        settings_kwargs: Additional MailMessageDatasetSettings overrides.

    Returns:
        MailMessage: A dataset instance ready for testing.
    """
    if linked_service is None:
        linked_service = create_mock_mail_linked_service()

    settings = MailMessageDatasetSettings(mailbox=mailbox, folder=folder, **settings_kwargs)
    dataset = MailMessage(
        id=uuid.uuid4(),
        name="test-mail-dataset",
        version="1.0.0",
        linked_service=cast("Any", linked_service),
        settings=settings,
    )
    return dataset


def create_mock_linked_service() -> MagicMock:
    """
    Create a mock MsSqlLinkedService for testing.

    Returns:
        MagicMock: A mocked linked service with connection configured.
    """
    engine = MagicMock()
    engine.dialect.identifier_preparer.quote = MagicMock(side_effect=lambda name: f"[{name}]")

    mock_service = MagicMock(spec=MsSqlLinkedService)
    mock_service.connection = engine
    mock_service.close = MagicMock()

    return mock_service


def create_mock_dataset(
    table: str = "test_table",
    schema: str = "public",
    linked_service: MsSqlLinkedService | None = None,
    read_props: ReadSettings | None = None,
) -> MsSqlTable:
    """
    Create a mock MsSqlTable for testing.

    Args:
        table: The table name.
        schema: The schema name.
        linked_service: Optional linked service. If None, creates a mock one.
        read_props: Optional read settings.

    Returns:
        MsSqlTable: A dataset instance ready for testing.
    """
    if linked_service is None:
        linked_service = create_mock_linked_service()

    props = MsSqlTableDatasetSettings(
        table=table,
        schema=schema,
        read=read_props,
    )
    dataset = MsSqlTable(
        id=uuid.uuid4(),
        name="test-dataset",
        version="1.0.0",
        linked_service=cast("Any", linked_service),
        settings=props,
    )
    return dataset


def create_test_dataframe() -> pd.DataFrame:
    """
    Create a test DataFrame with sample data.

    Returns:
        pd.DataFrame: A test DataFrame with multiple column types.
    """
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
            "status": ["active", "inactive", "active", "active", "inactive"],
            "amount": [100.50, 200.75, 150.25, 300.00, 250.50],
            "is_active": [True, False, True, True, False],
        }
    )
