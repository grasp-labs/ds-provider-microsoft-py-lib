"""
**File:** ``__init__.py``
**Region:** ``ds-provider-microsoft-py-lib``

Description
-----------
A Python package from the ds-provider-microsoft-py-lib library.

Example
-------
.. code-block:: python

    from ds_provider_microsoft_py_lib import __version__

    print(f"Package version: {__version__}")
"""

from importlib.metadata import version

from .dataset import MailMessage, MailMessageDatasetSettings, MsSqlTable, MsSqlTableDatasetSettings
from .linked_service import MailLinkedService, MailLinkedServiceSettings, MsSqlLinkedService, MsSqlLinkedServiceSettings

__version__ = version("ds-provider-microsoft-py-lib")

__all__ = [
    "MailLinkedService",
    "MailLinkedServiceSettings",
    "MailMessage",
    "MailMessageDatasetSettings",
    "MsSqlLinkedService",
    "MsSqlLinkedServiceSettings",
    "MsSqlTable",
    "MsSqlTableDatasetSettings",
    "__version__",
]
