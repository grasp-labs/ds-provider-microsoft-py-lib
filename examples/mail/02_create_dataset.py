"""
**File:** ``02_create_dataset.py``
**Region:** ``examples/02_create_dataset.py``

Example 02: Read messages and attachments using MailMessage
--------------------------------------------------------------------------------------------

This example demonstrates how to:
- Create an instance of `MailMessageDatasetSettings` with the mailbox to operate on and its
nested `ReadSettings`/`UpdateSettings`/`RenameSettings`, one per dataset operation.
- Create an instance of `MailMessage` using the settings, a linked service, and additional
metadata such as id, name, version, and description.
- Connect to the linked service and read messages (with attachments expanded inline) into
`dataset.output`, a pandas DataFrame with one row per message. `read()` never mutates the
mailbox and is idempotent.
- Decode an attachment's base64 `content_bytes` back into raw file bytes.
- Optionally mark the messages as read (`update()`) and move them to a "processed" folder
(`rename()`, since relocating a message is a rename of the resource, not a read-time side
effect or a generic field update) by assigning them to `dataset.input` -- gated behind the
`MAIL_ALLOW_MUTATIONS` environment variable since, unlike the mssql example's disposable
docker database, this reads a real mailbox and these actions are not reversible from this
script.

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

from ds_provider_microsoft_py_lib.dataset.mail import (
    MailMessage,
    MailMessageDatasetSettings,
    ReadSettings,
    RenameSettings,
    UpdateSettings,
)
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
        read=ReadSettings(
            folder="inbox",
            unread_only=True,
            top=5,
            include_attachments=True,
        ),
        update=UpdateSettings(mark_as_read=allow_mutations),
        rename=RenameSettings(target_folder="Processed" if allow_mutations else None),
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

if allow_mutations and not output.empty:
    dataset.input = output
    dataset.update()  # mark as read
    dataset.rename()  # move to settings.rename.target_folder
    print("MAIL_ALLOW_MUTATIONS=true: messages above were marked as read and moved to 'Processed'.")
else:
    print("MAIL_ALLOW_MUTATIONS not set: messages were left untouched (read-only run).")
