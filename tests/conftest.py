"""A small fake website served locally, so tests never touch the real network.

/                 home: duplicate links, fragments, mailto, external, ...
/about            links back home and to /missing (a 2nd referrer for the 404)
/old              301 -> /new
/missing          404 (its HTML body has a link that must NOT be followed)
/error            500
/slow             answers after 0.3s and links to /deep
/private/secret   disallowed by robots.txt
/files/report.pdf not HTML, so the link-like text inside is ignored
/base/            uses <base href="/docs/"> so "guide" means /docs/guide
"""

import asyncio
from collections import Counter
from dataclasses import dataclass

import pytest
from aiohttp import web


def page(body: str, title: str = "", status: int = 200):
    """A request handler that returns a small HTML page."""
    text = f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"

    async def handler(request: web.Request) -> web.Response:
        return web.Response(text=text, content_type="text/html", status=status)

    return handler


HOME = """
<a href="/about">About</a>
<a href="/about#team">Team (same page)</a>
<a href="about">About again (relative)</a>
<a href="/old">Old page</a>
<a href="/missing">Missing</a>
<a href="/error">Error</a>
<a href="/slow">Slow</a>
<a href="/private/secret">Private</a>
<a href="/files/report.pdf">Report</a>
<a href="/base/">Docs</a>
<a href="http://external.invalid/page">External</a>
<a href="mailto:someone@example.com">Mail</a>
"""


async def slow(request: web.Request) -> web.Response:
    await asyncio.sleep(0.3)
    return await page('<a href="/deep">Deep</a>', "Slow")(request)


async def old(request: web.Request) -> web.Response:
    raise web.HTTPMovedPermanently("/new")


async def pdf(request: web.Request) -> web.Response:
    return web.Response(body=b'%PDF-1.7 <a href="/from-pdf">', content_type="application/pdf")


def make_app(robots_status: int = 200) -> tuple[web.Application, Counter]:
    hits: Counter = Counter()

    @web.middleware
    async def count_hits(request, handler):
        hits[request.path] += 1
        return await handler(request)

    async def robots(request: web.Request) -> web.Response:
        if robots_status != 200:
            return web.Response(status=robots_status)
        return web.Response(text="User-agent: *\nDisallow: /private\n")

    app = web.Application(middlewares=[count_hits])
    app.router.add_get("/", page(HOME, "Home"))
    app.router.add_get(
        "/about", page('<a href="/">Home</a> <a href="/missing">Missing</a>', "About")
    )
    app.router.add_get("/new", page("New content", "New"))
    app.router.add_get("/deep", page("You found me", "Deep"))
    app.router.add_get("/private/secret", page("Secret", "Secret"))
    app.router.add_get("/base/", page('<base href="/docs/"><a href="guide">Guide</a>', "Base"))
    app.router.add_get("/docs/guide", page("The guide", "Guide"))
    app.router.add_get("/missing", page('<a href="/should-not-follow">x</a>', "Not found", 404))
    app.router.add_get("/error", page("boom", "Error", 500))
    app.router.add_get("/files/report.pdf", pdf)
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/old", old)
    app.router.add_get("/slow", slow)
    return app, hits


@dataclass
class Site:
    server: object
    hits: Counter

    def url(self, path: str = "/") -> str:
        return str(self.server.make_url(path))


@pytest.fixture
def make_site(aiohttp_server):
    async def factory(**options) -> Site:
        app, hits = make_app(**options)
        return Site(await aiohttp_server(app), hits)

    return factory


@pytest.fixture
async def site(make_site) -> Site:
    return await make_site()
