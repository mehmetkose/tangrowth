"""Finding links in HTML and deciding which URLs belong to the same site.

Nothing in this module touches the network, so it is easy to test and reuse.
"""

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(href: str, base: str) -> str | None:
    """Turn a link found on page ``base`` into a canonical absolute URL.

    The same page can be written many ways (``/about``, ``about``,
    ``/about#team``, ``HTTPS://Example.com:443/about``). Normalizing them
    to one spelling is what lets the crawler visit each page only once.

    Returns None for links a crawler can't follow (``mailto:``,
    ``javascript:``, ...) and for malformed URLs.
    """
    try:
        parts = urlsplit(urljoin(base, href.strip()))
        scheme = parts.scheme.lower()
        host = parts.hostname  # urlsplit lowercases it for us
        port = parts.port  # raises ValueError for ports like ":abc"
    except ValueError:  # also raised for broken IPv6 hosts like "[::1"
        return None
    if scheme not in DEFAULT_PORTS or not host:
        return None
    if ":" in host:  # an IPv6 address needs its brackets back
        host = f"[{host}]"
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    # Drop the #fragment (it never reaches the server) and any user:password@.
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def site_key(url: str) -> str:
    """Name the site a URL belongs to, used to decide what is "the same site".

    ``http://python.org/`` and ``https://www.python.org/about`` both give
    ``"python.org"``: the scheme and a leading ``www.`` are ignored. Other
    subdomains (``docs.python.org``) and non-default ports count as
    different sites.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    if parts.port in (None, DEFAULT_PORTS.get(parts.scheme)):
        return host
    return f"{host}:{parts.port}"


class _LinkParser(HTMLParser):
    """Collects the page title, every <a>/<area> href and the <base> href."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # turns &amp; into & for us
        self.title: str | None = None
        self.base_href: str | None = None
        self.hrefs: list[str] = []
        self._title_text: list[str] | None = None  # not None while inside <title>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag in ("a", "area") and href is not None:
            self.hrefs.append(href)
        elif tag == "base" and href and self.base_href is None:
            self.base_href = href.strip()
        elif tag == "title" and self.title is None:
            self._title_text = []

    def handle_data(self, data: str) -> None:
        if self._title_text is not None:
            self._title_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_text is not None:
            # Collapse whitespace: titles often span several lines.
            self.title = " ".join("".join(self._title_text).split()) or None
            self._title_text = None


def parse_html(html: str, url: str) -> tuple[str | None, list[str]]:
    """Return the ``<title>`` of a page and the normalized links on it.

    Links are resolved against ``<base href>`` when the page has one, and
    each link appears once, in the order it was first found.
    """
    parser = _LinkParser()
    try:
        parser.feed(html)
        parser.close()
    except AssertionError:
        pass  # HTMLParser gives up on some broken markup; keep what we found
    base = urljoin(url, parser.base_href) if parser.base_href else url
    links: dict[str, None] = {}  # a dict keeps insertion order, unlike a set
    for href in parser.hrefs:
        if link := normalize_url(href, base):
            links[link] = None
    return parser.title, list(links)
