import pytest

from tangrowth.links import normalize_url, parse_html, site_key

BASE = "https://example.com/dir/page"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("other", "https://example.com/dir/other"),
        ("/abs", "https://example.com/abs"),
        ("../up", "https://example.com/up"),
        ("//cdn.example.com/x", "https://cdn.example.com/x"),
        ("?q=1", "https://example.com/dir/page?q=1"),
        ("#top", "https://example.com/dir/page"),
        ("", "https://example.com/dir/page"),
        ("  /spaced \n", "https://example.com/spaced"),
        ("HTTPS://EXAMPLE.COM/CasePath", "https://example.com/CasePath"),
        ("http://example.com:80/x", "http://example.com/x"),
        ("https://example.com:443/x", "https://example.com/x"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        ("https://example.com", "https://example.com/"),
        ("http://user:secret@example.com/x", "http://example.com/x"),
        ("http://[::1]:8080/x", "http://[::1]:8080/x"),
        ("mailto:someone@example.com", None),
        ("javascript:void(0)", None),
        ("tel:+123456", None),
        ("data:text/html,hi", None),
        ("ftp://example.com/file", None),
        ("http://example.com:abc/", None),
        ("http://[::1/", None),
        ("http:///no-host", None),
    ],
)
def test_normalize_url(href, expected):
    assert normalize_url(href, BASE) == expected


def test_site_key_ignores_scheme_and_www():
    assert (
        site_key("http://python.org/") == site_key("https://www.python.org/about/") == "python.org"
    )


def test_site_key_keeps_subdomains_and_ports_apart():
    assert site_key("https://docs.python.org/") != site_key("https://python.org/")
    assert site_key("http://127.0.0.1:8080/") == "127.0.0.1:8080"
    assert site_key("http://127.0.0.1:8080/") != site_key("http://127.0.0.1:8081/")


def test_parse_html_finds_title_and_links():
    html = """
    <html><head><title>  Hello
        &amp; welcome </title>
    <link rel="stylesheet" href="/style.css"></head>
    <body>
      <a href="/one">one</a>
      <a href="/one#again">same page again</a>
      <a>no href</a>
      <a href>empty href attribute</a>
      <area href="/map-area">
      <a href="/q?a=1&amp;b=2">entity in URL</a>
      <a href="mailto:x@example.com">mail</a>
      <script>var s = '<a href="/in-script">';</script>
      <svg><title>an icon</title></svg>
    </body></html>
    """
    title, links = parse_html(html, "https://example.com/")
    assert title == "Hello & welcome"
    assert links == [
        "https://example.com/one",
        "https://example.com/map-area",
        "https://example.com/q?a=1&b=2",
    ]


def test_parse_html_uses_base_href():
    _, links = parse_html('<base href="/docs/"><a href="guide">g</a>', "https://e.com/x/y")
    assert links == ["https://e.com/docs/guide"]


def test_parse_html_relative_base_href():
    _, links = parse_html('<base href="sub/"><a href="guide">g</a>', "https://e.com/x/y")
    assert links == ["https://e.com/x/sub/guide"]


def test_parse_html_without_title_or_links():
    assert parse_html("just text", "https://e.com/") == (None, [])


def test_parse_html_survives_broken_markup():
    title, links = parse_html('<title>t</title><a href="/ok">x</a><![if broken', "https://e.com/")
    assert title == "t"
    assert links == ["https://e.com/ok"]
