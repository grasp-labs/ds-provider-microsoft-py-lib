"""
**File:** ``enums.py``
**Region:** ``ds_provider_microsoft_py_lib/enums``

Constants for Microsoft provider.

Example:
    >>> ResourceType.MICROSOFT_SQL_LINKED_SERVICE
    'DS.RESOURCE.LINKED_SERVICE.MICROSOFT_SQL'
    >>> ResourceType.MICROSOFT_SQL_DATASET
    'DS.RESOURCE.DATASET.MICROSOFT_SQL'
"""

from enum import StrEnum


class ResourceType(StrEnum):
    """
    Constants definitions for Microsoft provider.
    """

    MICROSOFT_SQL_LINKED_SERVICE = "ds.resource.linked_service.microsoft_sql"
    MICROSOFT_SQL_DATASET = "ds.resource.dataset.microsoft_sql"
