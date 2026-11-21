"""A picture of a job post: its text is read by the AI model and put in the Add from a post box,
where the person checks it before the job is added."""

import base64
import json
from types import SimpleNamespace

import pytest

from jobagent import cli, db
from jobagent.config import Settings
from jobagent.llm import PICTURE_TEXT_INSTRUCTIONS, OpenAILLM, picture_kind
from jobagent.models import MatchResult, PastedJob

from conftest import TEST_DB
from test_web import Page

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
WEBP = b"RIFF\x24\0\0\0WEBPVP8 " + b"\0" * 64
POST = "We are hiring a Java Developer in Dubai.\nSend your CV to careers@acme.example"


def test_the_kinds_of_picture_that_can_be_read():
    assert [picture_kind(d) for d in (PNG, JPEG, b"GIF89a....", b"GIF87a....", WEBP)] == ["image/png", "image/jpeg", "image/gif", "image/gif", "image/webp"]
    assert picture_kind(b"%PDF-1.4") is None and picture_kind(b"We are hiring") is None and picture_kind(b"") is None
    assert picture_kind(b"RIFF\x24\0\0\0WAVEfmt ") is None  # a sound file starts with RIFF too


def test_what_is_sent_to_claude_for_a_picture():
    from test_cheaper_scoring import claude, httpx2, message

    seen, answers = [], [POST, "NO TEXT"]

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=message(answers[len(seen) - 1]))

    llm = claude(handler)
    assert llm.read_pictures([(PNG, "image/png"), (JPEG, "image/jpeg")]) == POST
    body = seen[0]
    assert body["system"] == PICTURE_TEXT_INSTRUCTIONS and "character for character" in body["system"]
    first, second, ask = body["messages"][0]["content"]
    assert first == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}}
    assert second["source"]["media_type"] == "image/jpeg"  # the pieces go in order, in one request
    assert ask == {"type": "text", "text": "Write out the text in these pictures."}
    assert llm.read_pictures([(PNG, "image/png")]) == ""  # nothing readable: nothing to fill in
    assert llm.usage["input"] == 200  # counted like any other call


def test_what_is_sent_to_openai_for_a_picture():
    sent = []
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: sent.append(kw) or SimpleNamespace(
        output_text=f" {POST} ", usage=SimpleNamespace(input_tokens=900, output_tokens=40))))
    assert OpenAILLM("key", "gpt-5.4-mini", client=client).read_pictures([(WEBP, "image/webp")]) == POST
    image, ask = sent[0]["input"][0]["content"]
    assert image == {"type": "input_image", "image_url": "data:image/webp;base64," + base64.b64encode(WEBP).decode()}
    assert ask["type"] == "input_text" and sent[0]["instructions"] == PICTURE_TEXT_INSTRUCTIONS


class Reader:
    model = "fake"

    def __init__(self, text=POST, fail=None):
        self.text, self.fail, self.asked = text, fail, []

    def read_pictures(self, pictures):
        self.asked.append(pictures)
        if self.fail:
            raise RuntimeError(self.fail)
        return self.text


def test_the_page_reads_pictures_and_stores_nothing(conn, monkeypatch):
    db.save_profile(conn, "Alex Morgan", "resume", {})
    reader = Reader()
    monkeypatch.setattr("jobagent.llm.make_llm", lambda settings: reader)
    page = Page()
    pic = lambda data: base64.b64encode(data).decode()  # noqa: E731
    try:
        code, r = page.call("/api/read-picture", {"pictures": [pic(PNG), pic(JPEG)]})
        assert code == 200 and r["text"] == POST
        assert reader.asked == [[(PNG, "image/png"), (JPEG, "image/jpeg")]]
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0  # the person adds the job, after checking

        for body, said in (({}, "Choose a picture of the post first"), ({"pictures": []}, "Choose a picture of the post first"),
                           ({"pictures": ["not base64!"]}, "could not be read. Choose it again"),
                           ({"pictures": [pic(b"%PDF-1.4 a resume")]}, "Use a PNG, JPG, WebP or GIF file"),
                           ({"pictures": [pic(PNG + b"\0" * 3_700_000)]}, "That picture is too large"),
                           ({"pictures": [pic(PNG)] * 11}, "too many pictures at once")):
            code, r = page.call("/api/read-picture", body)
            assert code == 400 and said in r["error"], (body.keys(), r)
        assert len(reader.asked) == 1  # nothing that was refused reached the model

        reader.text = ""
        assert page.call("/api/read-picture", {"pictures": [pic(PNG)]})[1]["error"] == "No text was found in that picture. Try a clearer screenshot."
        reader.fail = "overloaded\nmore detail"
        assert page.call("/api/read-picture", {"pictures": [pic(PNG)]})[1]["error"] == "The picture could not be read: overloaded"
    finally:
        page.close()


def test_the_page_says_when_no_ai_key_is_set(conn):
    page = Page(settings=Settings(database_url=TEST_DB))
    try:
        code, r = page.call("/api/read-picture", {"pictures": [base64.b64encode(PNG).decode()]})
        assert code == 400 and "ANTHROPIC_API_KEY" in r["error"]
    finally:
        page.close()


class PictureLLM(Reader):
    def read_pasted_job(self, text):
        assert text == POST
        return PastedJob(title="Java Developer", company="Acme", location="Dubai", contact_email="careers@acme.example",
                         description="We are hiring a Java Developer.")

    def score_job(self, profile, prefs, job):
        return MatchResult(score=86, verdict="strong", summary="fits", matched_skills=["Java"], missing_skills=[], red_flags=[])


def test_the_add_command_takes_a_picture_of_the_post(conn, monkeypatch, tmp_path, capsys):
    db.save_profile(conn, "Alex Morgan", "resume", {})
    llm = PictureLLM()
    monkeypatch.setattr(cli, "_llm", lambda s: llm)
    shot = tmp_path / "post.png"
    shot.write_bytes(PNG)
    args = SimpleNamespace(file=str(shot), url=None, config=str(tmp_path / "missing.yaml"))
    cli.cmd_add(args, Settings(database_url=TEST_DB))
    out = capsys.readouterr().out
    assert f"Text read from the picture (check the email address):\n{POST}" in out and "Added job #1: Java Developer at Acme" in out
    assert llm.asked == [[(PNG, "image/png")]]

    llm.text = ""
    with pytest.raises(SystemExit, match="No text was found in that picture"):
        cli.cmd_add(args, Settings(database_url=TEST_DB))
    text = tmp_path / "post.txt"
    text.write_text(POST)
    cli.cmd_add(SimpleNamespace(file=str(text), url=None, config=args.config), Settings(database_url=TEST_DB))
    assert "Text read from the picture" not in capsys.readouterr().out and len(llm.asked) == 2  # a text file is read as text
