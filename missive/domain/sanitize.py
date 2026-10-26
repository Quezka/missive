"""Making HTML mail safe to show: no scripts, no remote content (tracking pixels), links that
say where they really go. Works on a small allow-list with the standard library only."""
from __future__ import annotations

import html
from html.parser import HTMLParser

ALLOWED = {"a", "b", "i", "u", "em", "strong", "p", "br", "hr", "ul", "ol", "li", "blockquote",
           "pre", "code", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr",
           "td", "th", "span", "div", "img", "sub", "sup", "s", "small", "center"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "form",
                     "noscript", "svg", "math", "template"}
VOID = {"br", "hr", "img"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")


class _Cleaner(HTMLParser):
    def __init__(self, load_images: bool):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.load_images = load_images
        self.blocked_images = 0
        self.links: list[str] = []

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
            src = (a.get("src") or "").strip()
            if self.load_images and src.lower().startswith(("http://", "https://", "cid:", "data:image/")):
                self.out.append(f'<img src="{html.escape(src, quote=True)}" '
                                f'alt="{html.escape(a.get("alt") or "", quote=True)}">')
            else:
                self.blocked_images += 1
                alt = (a.get("alt") or "").strip()
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
