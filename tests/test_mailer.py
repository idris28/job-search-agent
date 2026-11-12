from jobagent.mailer import build_message, save_drafts, send_messages


class FakeIMAP:
    def __init__(self, host):
        self.host, self.appended, self.logged_out = host, [], False

    def login(self, user, password):
        self.user = user

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\Drafts \\HasNoChildren) "/" "[Gmail]/Drafts"']

    def append(self, folder, flags, date, data):
        self.appended.append((folder, flags, data))
        return "OK", [b"done"]

    def logout(self):
        self.logged_out = True


def test_gmail_draft_has_link_attachment_and_is_only_saved(tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 fake")
    msg = build_message("me@gmail.com", "jobs@acme.ae", "Java Developer | 6 yrs",
                        "**Key skills:** Java\n\nBest regards,\nAlex\n[LinkedIn](https://www.linkedin.com/in/x/)",
                        '<p>Best regards,<br>Alex<br><a href="https://www.linkedin.com/in/x/">LinkedIn</a></p>',
                        cv)
    assert msg["To"] == "jobs@acme.ae" and msg["Subject"] == "Java Developer | 6 yrs"
    plain = msg.get_body(("plain",)).get_content()
    assert "LinkedIn: https://www.linkedin.com/in/x/" in plain and "[LinkedIn]" not in plain
    assert "Key skills: Java" in plain and "**" not in plain
    assert '<a href="https://www.linkedin.com/in/x/">LinkedIn</a>' in msg.get_body(("html",)).get_content()
    assert [a.get_filename() for a in msg.iter_attachments()] == ["cv.pdf"]

    made = []

    def factory(host):
        made.append(FakeIMAP(host))
        return made[-1]

    assert save_drafts("me@gmail.com", "app-pass", [msg], imap_factory=factory) == 1
    imap = made[0]
    assert imap.host == "imap.gmail.com" and imap.logged_out
    assert [(f, fl) for f, fl, _ in imap.appended] == [('"[Gmail]/Drafts"', "\\Draft")]


def test_send_goes_through_gmail_smtp():
    sent = []

    class FakeSMTP:
        def __init__(self, host, port):
            self.where = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def login(self, user, password):
            self.user = user

        def send_message(self, msg):
            sent.append((self.where, self.user, msg["To"]))

    msg = build_message("me@gmail.com", "jobs@acme.ae", "s", "body", "<p>body</p>")
    assert send_messages("me@gmail.com", "app-pass", [msg], smtp_factory=FakeSMTP) == 1
    assert sent == [(("smtp.gmail.com", 465), "me@gmail.com", "jobs@acme.ae")]
