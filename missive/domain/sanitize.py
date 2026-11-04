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
           "td", "th", "span", "div", "img", "sub", "sup", "s", "small", "center", "font", "tfoot", "caption",
           "big", "strike", "del", "ins", "dl", "dt", "dd", "abbr", "cite", "address", "kbd", "samp", "tt", "var", "q"}
AS_DIV = {"section", "article", "header", "footer", "main", "aside", "nav", "figure", "figcaption", "details", "summary"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "form",
                     "noscript", "svg", "math", "template"}
VOID = {"br", "hr", "img"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")
EMBEDDED_IMAGE = re.compile(r"^data:image/(png|jpeg|gif|webp|bmp);base64,[A-Za-z0-9+/=\s]+$", re.I)  # no network, no tracking
MAX_REMOTE_IMAGES = 40
# What a letter's look may set: layout and colour only. Nothing here can load anything or run anything.
_NUMBER = re.compile(r"^\d{1,4}(px|%)?$")
_COLOUR = re.compile(r"^(#[0-9a-f]{3,8}|[a-z]{3,24}|rgba?\([\d\s,.%]+\))$", re.I)
_CHOICE = {"align": {"left", "right", "center", "justify"}, "valign": {"top", "middle", "bottom", "baseline"}}
_ATTRIBUTES = {
    "table": {"width", "align", "bgcolor", "border", "cellpadding", "cellspacing"},
    "td": {"width", "height", "align", "valign", "bgcolor", "colspan", "rowspan"},
    "th": {"width", "height", "align", "valign", "bgcolor", "colspan", "rowspan"},
    "tr": {"align", "valign", "bgcolor"}, "thead": {"align", "valign", "bgcolor"},
    "tbody": {"align", "valign", "bgcolor"}, "tfoot": {"align", "valign", "bgcolor"},
    "p": {"align"}, "div": {"align"}, "h1": {"align"}, "h2": {"align"}, "h3": {"align"},
    "h4": {"align"}, "h5": {"align"}, "h6": {"align"}, "img": {"width", "height", "align"},
    "font": {"color", "size"}, "hr": {"width", "align"},
}
_CSS_COLOUR = {"color", "background-color", "border-color"}
_CSS_SIZE = {"font-size", "line-height", "width", "height", "margin", "margin-top", "margin-bottom", "margin-left",
             "margin-right", "padding", "padding-top", "padding-bottom", "padding-left", "padding-right"}
_CSS_WORDS = {"font-weight": r"(normal|bold|bolder|lighter|\d{3})", "font-style": r"(normal|italic|oblique)",
              "text-align": r"(left|right|center|justify)", "vertical-align": r"(top|middle|bottom|baseline|sub|super)",
              "text-decoration": r"(none|underline|line-through|overline)", "white-space": r"(normal|nowrap|pre|pre-wrap)",
              "font-family": r"[\w\s,'\"-]{1,120}", "border-collapse": r"(collapse|separate)"}
_CSS_LENGTH = re.compile(r"^(-?[\d.]+(px|pt|em|rem|%)?|auto)(\s+(-?[\d.]+(px|pt|em|rem|%)?|auto)){0,3}$", re.I)
_HIDDEN = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|max-height\s*:\s*0|font-size\s*:\s*0(px)?\s*(;|$)"
                     r"|opacity\s*:\s*0(\.0+)?\s*(;|$)|mso-hide\s*:\s*all)", re.I)
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


def clean_style(style: str) -> str:
    """Only the properties of a small list, with values that can't fetch or run anything (no url(), no expression)."""
    kept = []
    for declaration in style.split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().lower(), value.replace("!important", "").strip()
        if not value:
            continue
        if name == "background":  # often only a colour; anything else (a picture) is dropped
            name = "background-color"
        good = (_COLOUR.match(value) if name in _CSS_COLOUR
                else _CSS_LENGTH.match(value) if name in _CSS_SIZE
                else re.fullmatch(_CSS_WORDS[name], value, re.I) if name in _CSS_WORDS else None)
        if good:
            kept.append(f"{name}: {value}")
    return "; ".join(kept)


def _clean_attribute(name: str, value: str) -> bool:
    value = value.strip()
    if name in _CHOICE:
        return value.lower() in _CHOICE[name]
    if name in ("bgcolor", "color"):
        return bool(_COLOUR.match(value))
    if name in ("colspan", "rowspan", "border", "cellpadding", "cellspacing", "size"):
        return value.isdigit() and len(value) <= 3
    return bool(_NUMBER.match(value))  # width, height


def _look(tag: str, attrs: dict) -> str:
    """The attributes of a tag that survive, ready to write after its name."""
    out = [f' {name}="{html.escape((attrs.get(name) or "").strip(), quote=True)}"'
           for name in sorted(_ATTRIBUTES.get(tag, ())) if attrs.get(name) and _clean_attribute(name, attrs[name])]
    style = clean_style(attrs.get("style") or "")
    if style:
        out.append(f' style="{html.escape(style, quote=True)}"')
    return "".join(out)


class _Cleaner(HTMLParser):
    def __init__(self, load_images: bool):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.load_images = load_images
        self.blocked_images = 0
        self.links: list[str] = []
        self.images: list[str] = []  # remote pictures that may be fetched, if the user asks
        self.hidden_tag: str | None = None  # inside text the sender hid (a newsletter's "preheader")
        self.hidden_depth = 0
        self.hidden_text: list[str] = []  # given back if the hidden tag never closes: no text is lost to bad HTML

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.hidden_tag is not None:
            self.hidden_depth += tag == self.hidden_tag
            return
        tag = "div" if tag in AS_DIV else tag
        if self.skip or tag not in ALLOWED:
            return
        a = dict(attrs)
        if tag not in VOID and _HIDDEN.search(a.get("style") or ""):
            self.hidden_tag, self.hidden_depth = tag, 1
            return
        if tag == "a":
            href = (a.get("href") or "").strip()
            if href.lower().startswith(SAFE_SCHEMES):
                self.links.append(href)
                self.out.append(f'<a href="{html.escape(href, quote=True)}" '
                                f'title="{html.escape(href, quote=True)}"{_look(tag, a)}>')
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
            allowed = remote and remote_image_allowed(src)
            if allowed:
                self.images.append(src)
            if EMBEDDED_IMAGE.match(src) or (self.load_images and allowed):
                self.out.append(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}"'
                                f'{_look(tag, a)}>')
            else:
                if remote and not self.load_images:
                    self.blocked_images += 1  # a picture that would be fetched from the internet: the user decides
                self.out.append(f"<i>[image{': ' + html.escape(alt) if alt else ''}]</i>")
            return
        self.out.append(f"<{tag}{_look(tag, a)}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        tag = "div" if tag in AS_DIV else tag
        if self.hidden_tag is not None:
            if tag == self.hidden_tag:
                self.hidden_depth -= 1
                if not self.hidden_depth:
                    self.hidden_tag, self.hidden_text = None, []
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
            (self.out if self.hidden_tag is None else self.hidden_text).append(html.escape(data))

    def finish(self) -> str:
        self.out.extend(self.hidden_text)
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def clean_mail(source: str, load_images: bool = False) -> tuple[str, int, tuple[str, ...], tuple[str, ...]]:
    """Everything the reader needs from one pass over the HTML, which is slow on a big letter:
    (safe HTML, remote images left out, where its links go, remote images that may be fetched)."""
    cleaner = _Cleaner(load_images)
    cleaner.feed(source or "")
    cleaner.close()
    return (cleaner.finish(), cleaner.blocked_images, tuple(cleaner.links),
            tuple(dict.fromkeys(cleaner.images))[:MAX_REMOTE_IMAGES])


def clean_html(source: str, load_images: bool = False) -> tuple[str, int]:
    """(safe HTML, number of remote images left out)."""
    return clean_mail(source, load_images)[:2]


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
    return list(clean_mail(source, True)[3])
