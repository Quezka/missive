"""Making HTML mail safe to show: no scripts, no remote content (tracking pixels), links that
say where they really go. Works on a small allow-list with the standard library only."""
from __future__ import annotations

import html
import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED = {"a", "b", "i", "u", "em", "strong", "p", "br", "hr", "ul", "ol", "li", "blockquote",
           "pre", "code", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr",
           "td", "th", "span", "div", "img", "sub", "sup", "s", "small", "center"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "form",
                     "noscript", "svg", "math", "template"}
VOID = {"br", "hr", "img"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")
EMBEDDED_IMAGE = re.compile(r"^data:image/(png|jpeg|gif|webp|bmp);base64,[A-Za-z0-9+/=\s]+$", re.I)  # no network, no tracking
MAX_REMOTE_IMAGES = 40
LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localdomain", ".intranet", ".corp")


def remote_image_allowed(url: str) -> bool:
    """Whether a picture may be fetched from this address. A message must not be able to make the computer
    contact the user's own network (a router's address, a printer, localhost), only the public internet."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:  # a name, not an address
        return "." in host and host != "localhost" and not host.endswith(LOCAL_SUFFIXES)
    return ip.is_global and not ip.is_multicast


class _Cleaner(HTMLParser):
    def __init__(self, load_images: bool):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.load_images = load_images
        self.blocked_images = 0
        self.links: list[str] = []
        self.images: list[str] = []  # remote pictures that were let through (only when the user asked)

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        a = dict(attrs)
        if tag == "a":
            href = (a.get("href") or "").strip()
            if href.lower().startswith(SAFE_SCHEMES):
                self.links.append(href)
                self.out.append(f'<a href="{html.escape(href, quote=True)}" '
                                f'title="{html.escape(href, quote=True)}">')
                self.open.append("a")
            else:
                self.out.append("<span>")
                self.open.append("span")
            return
        if tag == "img":
            src = " ".join((a.get("src") or "").split()) if (a.get("src") or "").lower().startswith("data:") \
                else (a.get("src") or "").strip()
            remote = src.lower().startswith(("http://", "https://"))
            alt = (a.get("alt") or "").strip()
            if EMBEDDED_IMAGE.match(src) or (self.load_images and remote and remote_image_allowed(src)):
                self.out.append(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}">')
                if remote:
                    self.images.append(src)
            else:
                if remote and not self.load_images:
                    self.blocked_images += 1  # a picture that would be fetched from the internet: the user decides
                self.out.append(f"<i>[image{': ' + html.escape(alt) if alt else ''}]</i>")
            return
        self.out.append(f"<{tag}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED or tag in VOID:
            return
        wanted = "span" if tag == "a" and "a" not in self.open else tag
        if wanted in self.open:
            while self.open:
                top = self.open.pop()
                self.out.append(f"</{top}>")
                if top == wanted:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data))

    def finish(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def clean_html(source: str, load_images: bool = False) -> tuple[str, int]:
    """(safe HTML, number of remote images left out)."""
    cleaner = _Cleaner(load_images)
    cleaner.feed(source or "")
    cleaner.close()
    return cleaner.finish(), cleaner.blocked_images


def text_of(source: str) -> str:
    """Plain text from HTML, for snippets and search."""
    class _Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in DROP_WITH_CONTENT:
                self.skip += 1
            elif tag in ("br", "p", "div", "li", "tr"):
                self.parts.append(" ")

        def handle_endtag(self, tag):
            if tag in DROP_WITH_CONTENT:
                self.skip = max(0, self.skip - 1)

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    parser = _Text()
    parser.feed(source or "")
    return " ".join("".join(parser.parts).split())


def link_targets(source: str) -> list[str]:
    cleaner = _Cleaner(False)
    cleaner.feed(source or "")
    return cleaner.links


def image_urls(source: str) -> list[str]:
    """The remote pictures of a message that may be fetched once the user asks for them (no duplicates)."""
    cleaner = _Cleaner(True)
    cleaner.feed(source or "")
    return list(dict.fromkeys(cleaner.images))[:MAX_REMOTE_IMAGES]
