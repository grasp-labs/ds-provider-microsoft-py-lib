"""
**File:** ``02_create_dataset.py``
**Region:** ``examples/02_create_dataset.py``

Example 02: Read messages and attachments using MailMessage
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create an instance of `MailMessageDatasetSettings` with the mailbox and folder to read from.
- Create an instance of `MailMessage` using the settings, a linked service, and additional
metadata such as id, name, version, and description.
- Connect to the linked service and read messages (with attachments expanded inline) into
`dataset.output`, a pandas DataFrame with one row per message.
- Decode an attachment's base64 `content_bytes` back into raw file bytes.
- Optionally mark the returned messages as read and move them to a "processed" folder --
gated behind the `MAIL_ALLOW_MUTATIONS` environment variable since, unlike the mssql example's
disposable docker database, this reads a real mailbox and these actions are not reversible
from this script.

Reads credentials and the mailbox to query from environment variables:
- MAIL_TENANT_ID
- MAIL_CLIENT_ID
- MAIL_CLIENT_SECRET
- MAIL_MAILBOX

Marking messages as read or moving them requires the app registration to hold the Microsoft
Graph application permission ``Mail.ReadWrite`` (with admin consent); read-only use only needs
``Mail.Read``.
"""

import base64
import os
import uuid

from ds_provider_microsoft_py_lib.dataset.mail import MailMessage, MailMessageDatasetSettings
from ds_provider_microsoft_py_lib.linked_service.mail import MailLinkedService, MailLinkedServiceSettings

allow_mutations = os.environ.get("MAIL_ALLOW_MUTATIONS", "false").lower() == "true"

linked_service = MailLinkedService(
    settings=MailLinkedServiceSettings(
        tenant_id=os.environ["MAIL_TENANT_ID"],
        client_id=os.environ["MAIL_CLIENT_ID"],
        client_secret=os.environ["MAIL_CLIENT_SECRET"],
    ),
    id=uuid.uuid4(),
    name="testmailpackage",
    version="0.0.1",
    description="testmailpackage",
)
dataset = MailMessage(
    linked_service=linked_service,
    settings=MailMessageDatasetSettings(
        mailbox=os.environ["MAIL_MAILBOX"],
        folder="inbox",
        unread_only=True,
        top=5,
        include_attachments=True,
        mark_as_read=allow_mutations,
        move_to_processed_folder="Processed" if allow_mutations else None,
    ),
    id=uuid.uuid4(),
    name="testmaildataset",
    version="0.0.1",
    description="testmaildataset",
)

dataset.linked_service.connect()
dataset.read()
output = dataset.output

print(f"Read {len(output)} unread message(s):")
print(output[["subject", "from_address", "received_datetime", "has_attachments"]])

for _, row in output.iterrows():
    for attachment in row["attachments"]:
        content = base64.b64decode(attachment["content_bytes"])
        print(f"Attachment {attachment['name']!r} decoded to {len(content)} bytes ({attachment['content_type']}).")

if allow_mutations:
    print("MAIL_ALLOW_MUTATIONS=true: messages above were marked as read and moved to 'Processed'.")
else:
    print("MAIL_ALLOW_MUTATIONS not set: messages were left untouched (read-only run).")
