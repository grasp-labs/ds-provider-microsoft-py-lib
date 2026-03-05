"""
**File:** ``enums.py``
**Region:** ``ds_provider_microsoft_py_lib/enums``

Constants for Microsoft provider.

Example:
    >>> ResourceType.MICROSOFT_SQL_LINKED_SERVICE
    'ds.resource.linked_service.microsoft-sql'
    >>> ResourceType.MICROSOFT_SQL_DATASET
    'ds.resource.dataset.microsoft-sql'
"""

from enum import StrEnum


class ResourceType(StrEnum):
    """
    Constants definitions for Microsoft provider.
    """

    MICROSOFT_SQL_LINKED_SERVICE = "ds.resource.linked_service.microsoft-sql"
    MICROSOFT_SQL_DATASET = "ds.resource.dataset.microsoft-sql"
