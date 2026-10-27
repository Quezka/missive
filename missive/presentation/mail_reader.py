"""The message body. Qt shows pictures only from files, so this reader brings in the two kinds a letter has:
pictures embedded in the message (decoded from the HTML, no network) and, only once the user has pressed Load
pictures, the ones on the internet (fetched here with no cookies, no cache and hard limits)."""
from __future__ import annotations

import base64
import re

from PySide6.QtCore import QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QTextBrowser

MAX_BYTES = 8_000_000  # one picture
MAX_PIXELS = 40_000_000
TIMEOUT_MS = 15_000
_DATA_SRC = re.compile(r"""(src\s*=\s*")(data:image/[a-z]+;base64,[A-Za-z0-9+/=\s]+)(")""", re.I)


class MailReader(QTextBrowser):
    pictures_loaded = Signal(int)  # how many remote pictures arrived (the window can say so)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._web = QNetworkAccessManager(self)
        self._replies: set[QNetworkReply] = set()
        self._generation = 0
        self._html = ""
        self._arrived = 0
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(150)  # pictures come one by one: redraw once for a few of them
        self._redraw.timeout.connect(self._draw)

    # ---- showing a message ----

    def show_mail(self, html: str, remote: tuple[str, ...] = ()):
        """Show cleaned HTML. `remote` lists the internet pictures to fetch: pass it only when the user asked."""
        self._stop()
        self._arrived = 0
        self._html = self._register_embedded(html)
        self.setHtml(self._html)
        for url in remote:
            self._fetch(url, self._generation)

    def clear_mail(self):
        self._stop()
        self._html = ""
        self.setHtml("")

    def _stop(self):
        self._generation += 1  # answers to older requests are ignored from now on
        self._redraw.stop()
        for reply in list(self._replies):
            reply.abort()
        self._replies.clear()

    def _max_width(self) -> int:
        return max(240, self.viewport().width() - 44)

    def _fit(self, image: QImage) -> QImage:
        from PySide6.QtCore import Qt
        return image.scaledToWidth(self._max_width(), Qt.SmoothTransformation) if image.width() > self._max_width() \
            else image

    def _register_embedded(self, html: str) -> str:
        """Pictures written into the HTML as data: addresses become document resources, scaled to fit."""
        counter = 0

        def swap(match):
            nonlocal counter
            try:
                raw = base64.b64decode("".join(match.group(2).split()).split(",", 1)[1])
            except (ValueError, IndexError):
                return match.group(0)
            image = QImage.fromData(raw)
            if image.isNull() or image.width() * image.height() > MAX_PIXELS:
                return match.group(0)
            counter += 1
            name = f"mail-inline-{self._generation}-{counter}"
            self.document().addResource(QTextDocument.ImageResource, QUrl(name), self._fit(image))
            return f"{match.group(1)}{name}{match.group(3)}"
        return _DATA_SRC.sub(swap, html)

    # ---- pictures from the internet ----

    def _fetch(self, url: str, generation: int):
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        request.setAttribute(QNetworkRequest.CookieLoadControlAttribute, QNetworkRequest.Manual)  # no cookies
        request.setAttribute(QNetworkRequest.CookieSaveControlAttribute, QNetworkRequest.Manual)
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
        request.setAttribute(QNetworkRequest.CacheSaveControlAttribute, False)
        request.setTransferTimeout(TIMEOUT_MS)
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0 (compatible; Missive)")
        request.setRawHeader(b"Accept", b"image/png,image/jpeg,image/gif,image/webp,image/*;q=0.8")
        reply = self._web.get(request)
        reply.setProperty("missive-url", url)
        reply.setProperty("missive-generation", generation)
        self._replies.add(reply)
        # Connected to this widget's own methods, so nothing fires into a reader that has been closed.
        reply.downloadProgress.connect(self._progress)
        reply.finished.connect(self._reply_finished)

    @Slot("qint64", "qint64")
    def _progress(self, got: int, _total: int):
        reply = self.sender()
        if got > MAX_BYTES and isinstance(reply, QNetworkReply):
            reply.abort()  # far bigger than any picture in a letter

    @Slot()
    def _reply_finished(self):
        reply = self.sender()
        if not isinstance(reply, QNetworkReply):
            return
        url, generation = reply.property("missive-url"), reply.property("missive-generation")
        self._replies.discard(reply)
        data = bytes(reply.readAll()) if reply.error() == QNetworkReply.NoError else b""
        reply.deleteLater()
        if generation != self._generation or not data or len(data) > MAX_BYTES:
            return  # another message is open now, or the picture didn't come
        image = QImage.fromData(data)
        if image.isNull() or image.width() * image.height() > MAX_PIXELS:
            return
        self.document().addResource(QTextDocument.ImageResource, QUrl(url), self._fit(image))
        self._arrived += 1
        self._redraw.start()

    def _draw(self):
        bar = self.verticalScrollBar()
        place = bar.value()
        self.setHtml(self._html)  # the pictures are resources by now; the text keeps its place
        bar.setValue(place)
        self.pictures_loaded.emit(self._arrived)
