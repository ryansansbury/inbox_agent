"""The mailbox an agent works, as one small interface with an adapter for Microsoft 365 and one for Google Workspace.

The page never runs this code. It shows the shape a real deployment takes. The agent reads new mail in one shared order
desk mailbox, puts one of its four labels on each email and saves its reply as a draft in the thread. The interface has
no send and no delete, so neither exists for the agent to call, and a person sends every reply from their own mail app.

Each adapter builds its requests through a transport it's handed: a function that takes a method, an address, a body and
headers and gives back a status and the decoded answer. The tests hand it made-up sample answers, so nothing here opens a
network connection on its own. A real transport adds the access token from the company's sign-in setup.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

LANES = ("needs_you", "handled", "customer", "stopped")
# The label or category name the agent's four lanes carry in the real mailbox. Each lane replaces the others.
LABELS = {"needs_you": "Inbox Agent/Needs you", "handled": "Inbox Agent/Handled",
          "customer": "Inbox Agent/Waiting on the customer", "stopped": "Inbox Agent/Stopped"}
Transport = Callable[[str, str, Optional[dict], Dict[str, str]], Tuple[int, dict]]


class MailError(Exception):
    """A request the mail service refused, with its status and the service's own message."""


@dataclass
class Message:
    id: str
    thread: str
    sender_name: str
    sender_address: str
    subject: str
    received: str
    text: str
    ref: str = ""  # the Message-ID header, which a reply's In-Reply-To names


class Mailbox:
    """What the agent may do in a mailbox. Nothing else is here on purpose."""

    def new_messages(self, cursor: Optional[str] = None) -> Tuple[List[Message], Optional[str]]:
        """The inbox's new messages since the cursor, and the cursor for next time. No cursor starts from now."""
        raise NotImplementedError

    def label(self, message_id: str, lane: str) -> None:
        """Puts the lane's label on a message and takes off any other lane's label."""
        raise NotImplementedError

    def draft_reply(self, message_id: str, text: str) -> str:
        """Saves a reply as a draft in the message's thread and returns the draft's id. Nothing is sent."""
        raise NotImplementedError


def lane_label(lane: str) -> str:
    if lane not in LABELS:
        raise ValueError(f"no lane called {lane!r}")
    return LABELS[lane]


def checked(status: int, data: dict, what: str) -> dict:
    if status >= 400:
        detail = (data or {}).get("error")
        message = detail.get("message") if isinstance(detail, dict) else detail
        raise MailError(f"{what} failed with {status}: {message or 'no message'}")
    return data or {}
