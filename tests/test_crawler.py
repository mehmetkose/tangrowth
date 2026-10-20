import asyncio
from contextlib import aclosing

import pytest
from aiohttp import web

from tangrowth import CrawlError, Page, broken_links, crawl


async def collect(start_url: str, **options) -> list[Page]:
    async with aclosing(crawl(start_url, **options)) as pages:
        return [page async for page in pages]


def by_path(pages: list[Page], site) -> dict[str, Page]:
    return {page.url.removeprefix(site.url("/")[:-1]): page for page in pages}


async def test_full_crawl_visits_every_page_once(site):
    pages = await collect(site.url("/"))
    found = by_path(pages, site)

    assert {path: page.status for path, page in found.items()} == {
        "/": 200,
        "/about": 200,
        "/old": 301,
        "/new": 200,
        "/missing": 404,
        "/error": 500,
        "/slow": 200,
        "/deep": 200,  # only reachable through the slow page: the old crawler stopped too early
        "/files/report.pdf": 200,
        "/base/": 200,
        "/docs/guide": 200,  # resolved through <base href>
    }
    assert found["/"].title == "Home"
    assert found["/"].depth == 0 and found["/about"].depth == 1 and found["/deep"].depth == 2
    assert found["/about"].referrer == site.url("/")

    # Every page was requested exactly once, and robots.txt once.
    assert all(count == 1 for count in site.hits.values()), site.hits
    # Never requested: blocked by robots.txt, linked only from a 404 body or from a PDF.
    for path in ("/private/secret", "/should-not-follow", "/from-pdf"):
        assert path not in site.hits
    # The external link is listed on the page but not followed.
    assert "http://external.invalid/page" in found["/"].links


async def test_redirect_target_keeps_its_depth(site):
    found = by_path(await collect(site.url("/")), site)
    assert found["/old"].is_redirect
    assert found["/old"].links == [site.url("/new")]
    assert found["/new"].depth == found["/old"].depth
    assert found["/new"].referrer == site.url("/old")


async def test_max_pages_is_exact(site):
    pages = await collect(site.url("/"), max_pages=3)
    assert len(pages) == 3
    assert sum(site.hits.values()) - site.hits["/robots.txt"] == 3


async def test_max_depth_zero_fetches_only_the_start_page(site):
    pages = await collect(site.url("/"), max_depth=0)
    assert [page.url for page in pages] == [site.url("/")]


async def test_timeout_is_reported_and_crawl_continues(site):
    found = by_path(await collect(site.url("/"), request_timeout=0.2), site)
    assert found["/slow"].status is None
    assert found["/slow"].error == "TimeoutError"
    assert found["/slow"].broken
    assert found["/about"].status == 200
    assert "/deep" not in found


async def test_broken_links_lists_every_referrer(site):
    broken = {page.url: referrers for page, referrers in broken_links(await collect(site.url("/")))}
    assert broken == {
        site.url("/missing"): [site.url("/"), site.url("/about")],
        site.url("/error"): [site.url("/")],
    }


async def test_stopping_early_cleans_up(site):
    in_flight = []
    async with aclosing(crawl(site.url("/"), concurrency=5)) as pages:
        async for page in pages:
            if page.depth == 1:  # the first linked page; /slow is still being fetched
                in_flight = [t for t in asyncio.all_tasks() if t.get_coro().__qualname__ == "fetch"]
                break

    assert in_flight, "test setup: expected requests to still be running when we stopped"
    assert all(task.cancelled() for task in in_flight)
    hits = sum(site.hits.values())
    await asyncio.sleep(0.4)
    assert sum(site.hits.values()) == hits  # nothing new was requested after we stopped


async def test_delay_spaces_out_requests(site):
    loop = asyncio.get_running_loop()
    started = loop.time()
    await collect(site.url("/"), max_depth=1, max_pages=4, delay=0.1)
    assert loop.time() - started >= 0.3  # 4 requests, at least 0.1s apart


async def test_missing_robots_txt_allows_everything(make_site):
    site = await make_site(robots_status=404)
    found = by_path(await collect(site.url("/")), site)
    assert found["/private/secret"].status == 200


async def test_robots_txt_server_error_blocks_the_crawl(make_site):
    site = await make_site(robots_status=503)
    with pytest.raises(CrawlError, match="robots.txt"):
        await collect(site.url("/"))
    assert set(site.hits) == {"/robots.txt"}


async def test_ignore_robots(site):
    found = by_path(await collect(site.url("/"), respect_robots=False), site)
    assert found["/private/secret"].status == 200
    assert "/robots.txt" not in site.hits


async def test_start_page_redirecting_to_another_host_moves_the_crawl(site, aiohttp_server):
    # Like http://python.org/ -> https://www.python.org/: a different "site" on paper.
    async def to_site(request):
        raise web.HTTPMovedPermanently(site.url("/about"))

    app = web.Application()
    app.router.add_get("/", to_site)
    entrance = await aiohttp_server(app)

    pages = await collect(str(entrance.make_url("/")), respect_robots=False, max_depth=1)
    urls = {page.url for page in pages}
    assert site.url("/about") in urls
    assert site.url("/") in urls  # linked from /about, on the new site


async def test_rejects_non_http_urls():
    with pytest.raises(CrawlError, match="not an http"):
        await collect("ftp://example.com/")
