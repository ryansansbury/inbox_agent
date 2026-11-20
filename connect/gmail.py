"""The Google Workspace adapter, through the Gmail API.

It reads one mailbox ("me" is the mailbox the access token speaks for, which for a shared order desk is the account the
company grants the app). The first call lists the inbox and keeps the mailbox's history id, and every later call reads
only what the history says was added since. A lane becomes a Gmail label, made once if the mailbox doesn't have it,
and a message carries one lane's label at a time. A reply is saved as a draft in the thread with the headers that keep
it there. Nothing here sends, trashes or deletes a message.
"""
import base64
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from connect.base import LABELS, Mailbox, MailError, Message, Transport, checked, lane_label

BASE = "https://gmail.googleapis.com/gmail/v1/users"


def _text(part: dict) -> str:
    """The first plain text part of a message, decoded."""
    if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
        data = part["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for sub in part.get("parts") or []:
        found = _text(sub)
        if found:
            return found
    return ""


class GmailMailbox(Mailbox):
    def __init__(self, transport: Transport, user: str = "me", page: int = 50):
        self.transport = transport
        self.root = f"{BASE}/{quote(user)}"
        self.page = page
        self.label_ids: Dict[str, str] = {}

    def _call(self, method: str, path: str, body: Optional[dict] = None, query: Optional[dict] = None) -> dict:
        url = self.root + path + ("?" + urlencode(query) if query else "")
        status, data = self.transport(method, url, body, {})
        return checked(status, data, f"{method} {path}")

    def new_messages(self, cursor: Optional[str] = None) -> Tuple[List[Message], Optional[str]]:
        ids: List[str] = []
        if cursor is None:
            nxt = str(self._call("GET", "/profile").get("historyId", ""))
            listed = self._call("GET", "/messages", query={"labelIds": "INBOX", "maxResults": self.page})
            ids = [m["id"] for m in listed.get("messages", [])]
        else:
            token, nxt = None, cursor
            while True:
                query = {"startHistoryId": cursor, "historyTypes": "messageAdded", "labelId": "INBOX"}
                if token:
                    query["pageToken"] = token
                try:
                    data = self._call("GET", "/history", query=query)
                except MailError as e:
                    if " 404" not in str(e):
                        raise
                    return self.new_messages(None)  # the history id is too old, so read the inbox afresh
                for h in data.get("history", []):
                    ids += [a["message"]["id"] for a in h.get("messagesAdded", []) if a["message"]["id"] not in ids]
                nxt = str(data.get("historyId", nxt))
                token = data.get("nextPageToken")
                if not token:
                    break
        return [self._get(i) for i in ids], nxt

    def _get(self, message_id: str) -> Message:
        m = self._call("GET", f"/messages/{quote(message_id, safe='')}", query={"format": "full"})
        head = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers", [])}
        sender = head.get("from", "")
        name, _, address = sender.rpartition("<")
        return Message(id=m["id"], thread=m.get("threadId", ""), sender_name=name.strip().strip('"'),
                       sender_address=address.rstrip(">").strip() or sender, subject=head.get("subject", ""),
                       received=head.get("date", ""), text=_text(m.get("payload") or {}), ref=head.get("message-id", ""))

    def _label_id(self, name: str) -> str:
        if not self.label_ids:
            for lab in self._call("GET", "/labels").get("labels", []):
                self.label_ids[lab["name"]] = lab["id"]
        if name not in self.label_ids:
            made = self._call("POST", "/labels", {"name": name, "labelListVisibility": "labelShow",
                                                  "messageListVisibility": "show"})
            self.label_ids[name] = made["id"]
        return self.label_ids[name]

    def label(self, message_id: str, lane: str) -> None:
        mine = self._label_id(lane_label(lane))
        others = [self.label_ids[n] for n in LABELS.values() if n in self.label_ids and self.label_ids[n] != mine]
        self._call("POST", f"/messages/{quote(message_id, safe='')}/modify", {"addLabelIds": [mine], "removeLabelIds": others})

    def draft_reply(self, message_id: str, text: str) -> str:
        m = self._get(message_id)
        reply = EmailMessage()
        reply["To"] = m.sender_address
        reply["Subject"] = m.subject if m.subject.lower().startswith("re:") else "Re: " + m.subject
        if m.ref:
            reply["In-Reply-To"] = m.ref
            reply["References"] = m.ref
        reply.set_content(text)
        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode("ascii")
        draft = self._call("POST", "/drafts", {"message": {"raw": raw, "threadId": m.thread}})
        return draft["id"]
