"""
**File:** ``01_create_linked_service.py``
**Region:** ``examples/01_create_linked_service.py``

Example 01: Connect to Microsoft Graph mail using MailLinkedService
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create an instance of MailLinkedServiceSettings with the Azure AD app registration
credentials (tenant_id, client_id, client_secret) used for client-credential authentication.
- Create an instance of MailLinkedService using the settings and additional metadata such as
id, name, version, and description.
- Test the connection to Microsoft Graph using the test_connection method of the
MailLinkedService instance and print the result.

This example reads credentials from environment variables rather than hardcoding them, since
(unlike the mssql examples) there is no local sandbox server to connect to -- this talks to the
real Microsoft Graph API for the tenant configured in the app registration:
- MAIL_TENANT_ID
- MAIL_CLIENT_ID
- MAIL_CLIENT_SECRET

The app registration must be granted the Microsoft Graph application permission ``Mail.Read``
(or ``Mail.ReadWrite``, see example 02) with admin consent.
"""

import os
import uuid

from ds_provider_microsoft_py_lib.linked_service.mail import MailLinkedService, MailLinkedServiceSettings

settings = MailLinkedServiceSettings(
    tenant_id=os.environ["MAIL_TENANT_ID"],
    client_id=os.environ["MAIL_CLIENT_ID"],
    client_secret=os.environ["MAIL_CLIENT_SECRET"],
)
linked_service = MailLinkedService(
    settings=settings, id=uuid.uuid4(), name="testmailpackage", version="0.0.1", description="testmailpackage"
)

result = linked_service.test_connection()
print(result)
