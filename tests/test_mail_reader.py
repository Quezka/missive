"""The message body: pictures inside the message appear at once, pictures from the internet only when fetched,
with no cookies, a time limit and a size limit. The 'internet' here is a tiny server on this computer."""
import base64
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QBuffer, QIODevice, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage, QTextDocument  # noqa: E402

from missive.presentation.mail_reader import MailReader  # noqa: E402
from missive.presentation.qt_app import create_application  # noqa: E402
from tests.test_ui import _settle  # noqa: E402


def png(width, height, color="red") -> bytes:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class Handler(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):  # noqa: N802
        Handler.seen.append((self.path, dict(self.headers)))
        if self.path == "/slow.png":
            time.sleep(0.6)
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"just words" if self.path.startswith("/words") else png(60, 40)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Set-Cookie", "track=1")  # a tracker would like to keep this
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def web():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def app():
    return create_application(["test"])


@pytest.fixture
def reader(app):
    r = MailReader()
    r.resize(560, 400)
    r.show()
    Handler.seen.clear()
    yield r
    r.clear_mail()


def has_picture(reader, url) -> bool:
    return reader.document().resource(QTextDocument.ImageResource, QUrl(url)) is not None


def height(reader) -> int:
    reader.document().setTextWidth(500)
    return round(reader.document().size().height())


def test_a_picture_inside_the_message_is_shown_at_once_without_any_request(reader, web):
    data = "data:image/png;base64," + base64.b64encode(png(100, 80)).decode()
    reader.show_mail("<p>Hi</p>")
    without = height(reader)
    reader.show_mail(f'<p>Hi</p><img src="{data}">')
    assert height(reader) >= without + 50 and Handler.seen == []


def test_a_picture_wider_than_the_reader_is_scaled_to_fit(reader):
    data = "data:image/png;base64," + base64.b64encode(png(2000, 100)).decode()
    reader.show_mail(f'<img src="{data}">')
    name = next(n for n in reader.toHtml().split('src="')[1:2])[:60].split('"')[0]
    image = reader.document().resource(QTextDocument.ImageResource, QUrl(name))
    assert image is not None and image.width() <= reader.viewport().width()


def test_a_broken_inline_picture_does_not_crash(reader):
    reader.show_mail('<p>Hi</p><img src="data:image/png;base64,AAAA"><img src="data:image/png;base64,###">')
    assert "Hi" in reader.toPlainText()


def test_an_internet_picture_is_not_fetched_unless_the_window_passes_it(reader, web):
    reader.show_mail(f'<p>Hi</p><img src="{web}/ok.png">')  # nothing passed: the user hasn't asked
    time.sleep(0.2)
    assert Handler.seen == [] and not has_picture(reader, f"{web}/ok.png")


def test_an_internet_picture_is_fetched_without_cookies_and_then_shown(reader, web, app):
    url = f"{web}/ok.png"
    shown = []
    reader.pictures_loaded.connect(shown.append)
    reader.show_mail("<p>Hi</p>")
    without = height(reader)
    reader.show_mail(f'<p>Hi</p><img src="{url}">', (url,))
    _settle(app, lambda: shown)
    assert has_picture(reader, url) and shown == [1]
    assert height(reader) >= without + 20  # the picture is in the layout now
    path, headers = Handler.seen[0]
    assert path == "/ok.png" and "Cookie" not in headers and "Referer" not in headers
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    # the server tried to set a cookie: it must not come back on the next request
    reader.show_mail(f'<img src="{url}">', (url,))
    _settle(app, lambda: len(Handler.seen) >= 2)
    assert all("Cookie" not in h for _p, h in Handler.seen)


def test_a_picture_that_is_missing_or_not_a_picture_is_simply_skipped(reader, web, app):
    urls = (f"{web}/missing.png", f"{web}/words.png")
    reader.show_mail("<p>Hi</p>" + "".join(f'<img src="{u}">' for u in urls), urls)
    _settle(app, lambda: len(Handler.seen) == 2)
    time.sleep(0.3)
    app.processEvents()
    assert not any(has_picture(reader, u) for u in urls) and "Hi" in reader.toPlainText()


def test_a_slow_answer_for_a_message_you_left_is_ignored(reader, web, app):
    slow = f"{web}/slow.png"
    reader.show_mail(f'<img src="{slow}">', (slow,))
    reader.show_mail("<p>Another letter</p>")  # the user moved on: the request is cancelled
    end = time.time() + 1.2
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    assert not has_picture(reader, slow) and "Another letter" in reader.toPlainText()


def test_the_text_keeps_its_place_when_pictures_arrive(reader, web, app):
    url = f"{web}/ok.png"
    long_text = "".join(f"<p>line {i}</p>" for i in range(200))
    shown = []
    reader.pictures_loaded.connect(shown.append)
    reader.show_mail(long_text + f'<img src="{url}">', (url,))
    bar = reader.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    place = bar.value()
    _settle(app, lambda: shown)
    assert abs(bar.value() - place) <= 2 and place > 0
