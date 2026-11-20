"""The two mailbox adapters against made-up sample answers shaped like each service's own. Every request is recorded, so
the tests also prove what the adapters never ask for: no send, no move, no trash and no delete, and no address outside
the one mail service."""
import base64
import email
import unittest

from connect.base import LABELS, Mailbox, MailError
from connect.gmail import GmailMailbox
from connect.graph import GraphMailbox

BOX = "orders@wendlow.example"


class Fake:
    """A transport that answers from a table of (method, start of the address) and records every request."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        for (m, start), answer in self.answers.items():
            if m == method and url.startswith(start):
                return answer(url, body) if callable(answer) else answer
        return 404, {"error": {"message": f"nothing at {method} {url}"}}

    def never(self, host):
        bad = [(m, u) for m, u, _, _ in self.calls if not u.startswith(host) or
               any(w in u.lower() for w in ("/send", "/move", "/trash", "/delete")) or m == "DELETE"]
        return bad


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class Interface(unittest.TestCase):
    def test_the_agent_can_only_read_label_and_draft(self):
        public = sorted(n for n in vars(Mailbox) if not n.startswith("_"))
        self.assertEqual(public, ["draft_reply", "label", "new_messages"])
        for cls in (GraphMailbox, GmailMailbox):
            for name in ("send", "send_mail", "delete", "move", "trash", "forward"):
                self.assertFalse(hasattr(cls, name), f"{cls.__name__}.{name}")


class Graph(unittest.TestCase):
    ROOT = "https://graph.microsoft.com/v1.0/users/orders%40wendlow.example"

    def setUp(self):
        one = {"id": "AAMk1", "conversationId": "c1", "subject": "Rush: 60 bundles",
               "from": {"emailAddress": {"name": "Clara Voss", "address": "clara@tallowandteak.example"}},
               "receivedDateTime": "2026-10-27T14:48:00Z", "body": {"contentType": "text", "content": "Can we get 60?"},
               "internetMessageId": "<m05@tallowandteak.example>"}
        two = dict(one, id="AAMk2", subject="PO 4471")
        self.fake = Fake({
            ("GET", self.ROOT + "/mailFolders/inbox/messages/delta"): (200, {"value": [one, {"id": "gone", "@removed": {}}],
                                                                             "@odata.nextLink": self.ROOT + "/page2"}),
            ("GET", self.ROOT + "/page2"): (200, {"value": [two], "@odata.deltaLink": self.ROOT + "/next"}),
            ("GET", self.ROOT + "/messages/AAMk1?$select=categories"): (200, {"categories": ["Blue", LABELS["handled"]]}),
            ("PATCH", self.ROOT + "/messages/AAMk1"): (200, {}),
            ("POST", self.ROOT + "/messages/AAMk1/createReply"): (201, {"id": "draft-1", "isDraft": True}),
        })
        self.box = GraphMailbox(self.fake, BOX)

    def test_new_mail_follows_every_page_and_keeps_the_next_link(self):
        msgs, cursor = self.box.new_messages()
        self.assertEqual([m.id for m in msgs], ["AAMk1", "AAMk2"])
        self.assertEqual(msgs[0].sender_address, "clara@tallowandteak.example")
        self.assertEqual(msgs[0].ref, "<m05@tallowandteak.example>")
        self.assertEqual(cursor, self.ROOT + "/next")
        self.assertIn('outlook.body-content-type="text"', self.fake.calls[0][3].get("Prefer", ""))

    def test_a_lane_replaces_the_agent_s_category_and_keeps_a_person_s(self):
        self.box.label("AAMk1", "needs_you")
        method, url, body, _ = self.fake.calls[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(body, {"categories": ["Blue", LABELS["needs_you"]]})

    def test_a_reply_is_a_draft_in_the_thread(self):
        self.assertEqual(self.box.draft_reply("AAMk1", "Hi Clara"), "draft-1")
        self.assertEqual(self.fake.calls[-1][2], {"comment": "Hi Clara"})

    def test_nothing_is_sent_moved_or_deleted(self):
        self.box.new_messages()
        self.box.label("AAMk1", "handled")
        self.box.draft_reply("AAMk1", "Hi")
        self.assertEqual(self.fake.never("https://graph.microsoft.com/v1.0/users/orders%40wendlow.example/"), [])

    def test_a_refusal_says_what_failed(self):
        with self.assertRaises(MailError):
            GraphMailbox(Fake({}), BOX).draft_reply("nope", "Hi")

    def test_an_unknown_lane_is_refused(self):
        with self.assertRaises(ValueError):
            self.box.label("AAMk1", "archived")

    def test_an_id_with_a_slash_is_escaped_whole(self):
        fake = Fake({("POST", self.ROOT + "/messages/AA%2FB%2B%3D/createReply"): (201, {"id": "d"})})
        self.assertEqual(GraphMailbox(fake, BOX).draft_reply("AA/B+=", "Hi"), "d")


class Gmail(unittest.TestCase):
    ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"

    def setUp(self):
        full = {"id": "18c1", "threadId": "t1", "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": "Clara Voss <clara@tallowandteak.example>"},
                        {"name": "Subject", "value": "Rush: 60 bundles"}, {"name": "Date", "value": "Tue, 27 Oct 2026 07:48 -0700"},
                        {"name": "Message-ID", "value": "<m05@tallowandteak.example>"}],
            "parts": [{"mimeType": "text/plain", "body": {"data": b64("Can we get 60 bundles by Friday?")}},
                      {"mimeType": "text/html", "body": {"data": b64("<p>Can we</p>")}}]}}
        self.made = []
        self.fake = Fake({
            ("GET", self.ROOT + "/messages?"): (200, {"messages": [{"id": "18c1", "threadId": "t1"}]}),
            ("GET", self.ROOT + "/messages/18c1"): (200, full),
            ("GET", self.ROOT + "/messages/18c2"): (200, dict(full, id="18c2")),
            ("GET", self.ROOT + "/profile"): (200, {"emailAddress": BOX, "historyId": "9001"}),
            ("GET", self.ROOT + "/history"): self.history,
            ("GET", self.ROOT + "/labels"): (200, {"labels": [{"id": "INBOX", "name": "INBOX"},
                                                             {"id": "Label_7", "name": LABELS["handled"]}]}),
            ("POST", self.ROOT + "/labels"): self.make_label,
            ("POST", self.ROOT + "/messages/18c1/modify"): (200, {}),
            ("POST", self.ROOT + "/drafts"): (200, {"id": "r-1", "message": {"id": "18c9", "threadId": "t1"}}),
        })
        self.box = GmailMailbox(self.fake)

    def history(self, url, body):
        if "pageToken" in url:
            return 200, {"history": [{"messagesAdded": [{"message": {"id": "18c2"}}]}], "historyId": "9010"}
        return 200, {"history": [{"messagesAdded": [{"message": {"id": "18c1"}}]}], "historyId": "9005", "nextPageToken": "p2"}

    def make_label(self, url, body):
        self.made.append(body["name"])
        return 200, {"id": "Label_new", "name": body["name"]}

    def test_the_first_read_lists_the_inbox_and_keeps_the_history_id(self):
        msgs, cursor = self.box.new_messages()
        self.assertEqual([m.id for m in msgs], ["18c1"])
        self.assertEqual(msgs[0].sender_name, "Clara Voss")
        self.assertEqual(msgs[0].text, "Can we get 60 bundles by Friday?")
        self.assertEqual(cursor, "9001")

    def test_the_first_read_takes_the_history_id_before_it_lists(self):
        self.box.new_messages()
        order = [u.split("/users/me")[1].split("?")[0] for _, u, _, _ in self.fake.calls[:2]]
        self.assertEqual(order, ["/profile", "/messages"])

    def test_a_history_id_too_old_falls_back_to_a_full_read(self):
        self.fake.answers[("GET", self.ROOT + "/history")] = (404, {"error": {"message": "Requested entity was not found."}})
        msgs, cursor = self.box.new_messages("1")
        self.assertEqual([m.id for m in msgs], ["18c1"])
        self.assertEqual(cursor, "9001")

    def test_later_reads_follow_the_history_across_pages(self):
        msgs, cursor = self.box.new_messages("9000")
        self.assertEqual([m.id for m in msgs], ["18c1", "18c2"])
        self.assertEqual(cursor, "9010")

    def test_a_lane_label_is_made_once_and_replaces_the_others(self):
        self.box.label("18c1", "needs_you")
        self.box.label("18c1", "needs_you")
        self.assertEqual(self.made, [LABELS["needs_you"]])
        body = self.fake.calls[-1][2]
        self.assertEqual(body["addLabelIds"], ["Label_new"])
        self.assertEqual(body["removeLabelIds"], ["Label_7"])

    def test_a_reply_is_a_draft_in_the_thread_with_the_headers_that_keep_it_there(self):
        self.assertEqual(self.box.draft_reply("18c1", "Hi Clara"), "r-1")
        sent = self.fake.calls[-1][2]["message"]
        self.assertEqual(sent["threadId"], "t1")
        msg = email.message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
        self.assertEqual(msg["To"], "clara@tallowandteak.example")
        self.assertEqual(msg["Subject"], "Re: Rush: 60 bundles")
        self.assertEqual(msg["In-Reply-To"], "<m05@tallowandteak.example>")

    def test_nothing_is_sent_trashed_or_deleted(self):
        self.box.new_messages()
        self.box.label("18c1", "stopped")
        self.box.draft_reply("18c1", "Hi")
        self.assertEqual(self.fake.never(self.ROOT + "/"), [])


if __name__ == "__main__":
    unittest.main()
