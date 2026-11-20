"""The Microsoft 365 adapter, through Microsoft Graph's mail API.

It reads one shared mailbox by its address. New mail comes from a delta query over the inbox, which hands back a link
for the next call so nothing is read twice. A lane becomes an Outlook category on the message, and the other categories
a person set stay as they were. A reply is saved with createReply, which puts a draft in the thread with the agent's
text above the quoted email. Nothing here sends, moves or deletes a message.
"""
from typing import List, Optional, Tuple
from urllib.parse import quote

from connect.base import LABELS, Mailbox, Message, Transport, checked, lane_label

BASE = "https://graph.microsoft.com/v1.0"
FIELDS = "id,conversationId,from,subject,receivedDateTime,body,internetMessageId"


class GraphMailbox(Mailbox):
    def __init__(self, transport: Transport, mailbox: str):
        self.transport = transport
        self.root = f"/users/{quote(mailbox)}"

    def _call(self, method: str, path: str, body: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
        url = path if path.startswith("https://") else BASE + self.root + path
        status, data = self.transport(method, url, body, headers or {})
        return checked(status, data, f"{method} {path}")

    def new_messages(self, cursor: Optional[str] = None) -> Tuple[List[Message], Optional[str]]:
        url = cursor or f"/mailFolders/inbox/messages/delta?$select={FIELDS}"
        # The body comes back as plain text, which is what the agent reads.
        headers = {"Prefer": 'outlook.body-content-type="text"'}
        out = []
        while True:
            data = self._call("GET", url, headers=headers)
            out += [self._message(m) for m in data.get("value", []) if "@removed" not in m]
            if data.get("@odata.nextLink"):
                url = data["@odata.nextLink"]
                continue
            return out, data.get("@odata.deltaLink", cursor)

    @staticmethod
    def _message(m: dict) -> Message:
        sender = (m.get("from") or {}).get("emailAddress") or {}
        return Message(id=m["id"], thread=m.get("conversationId", ""), sender_name=sender.get("name", ""),
                       sender_address=sender.get("address", ""), subject=m.get("subject", ""),
                       received=m.get("receivedDateTime", ""), text=(m.get("body") or {}).get("content", ""),
                       ref=m.get("internetMessageId", ""))

    def label(self, message_id: str, lane: str) -> None:
        mine = lane_label(lane)
        path = f"/messages/{quote(message_id, safe='')}"
        now = self._call("GET", path + "?$select=categories").get("categories") or []
        kept = [c for c in now if c not in LABELS.values()]
        self._call("PATCH", path, {"categories": kept + [mine]})

    def draft_reply(self, message_id: str, text: str) -> str:
        draft = self._call("POST", f"/messages/{quote(message_id, safe='')}/createReply", {"comment": text})
        return draft["id"]
