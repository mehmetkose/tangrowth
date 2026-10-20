"""The crawler: fetch pages concurrently and hand them back as they finish.

The whole crawl is driven by a single loop in :func:`crawl`:

1. Start fetches until ``concurrency`` requests are in flight.
2. Wait until at least one of them finishes.
3. Queue the new links that finished page points to, then yield the page.

The loop ends when nothing is waiting and nothing is in flight. Only this
loop touches the crawl state (``seen``, ``frontier``), so nothing needs a
lock. ``examples/simple_crawler.py`` shows the other classic design (a
queue plus worker tasks) if you want to compare.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import aiohttp

from ._version import __version__
from .links import normalize_url, parse_html, site_key

log = logging.getLogger("tangrowth")

DEFAULT_USER_AGENT = f"tangrowth/{__version__} (+https://github.com/mehmetkose/tangrowth)"
HTML_TYPES = ("text/html", "application/xhtml+xml")
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


class CrawlError(Exception):
    """The crawl could not start: bad start URL, or blocked by robots.txt."""


@dataclass
class Page:
    """The result of requesting one URL."""

    url: str
    depth: int  # clicks away from the start page
    referrer: str | None  # the page where this URL was first found
    status: int | None = None  # HTTP status; None when the request failed
    error: str | None = None  # why the request failed
    content_type: str | None = None
    title: str | None = None
    links: list[str] = field(default_factory=list)  # for a redirect: just its target
    elapsed_ms: int = 0

    @property
    def is_redirect(self) -> bool:
        return self.status in REDIRECT_CODES and bool(self.links)

    @property
    def broken(self) -> bool:
        return self.status is None or self.status >= 400


async def fetch(session: aiohttp.ClientSession, url: str, depth: int, referrer: str | None) -> Page:
    """Request one URL. Network problems are recorded on the Page, never raised."""
    page = Page(url=url, depth=depth, referrer=referrer)
    started = time.perf_counter()
    try:
        # We follow redirects ourselves, so their targets get the same
        # same-site and robots.txt checks as every other link.
        async with session.get(url, allow_redirects=False) as resp:
            page.status = resp.status
            page.content_type = resp.content_type
            if resp.status in REDIRECT_CODES:
                target = normalize_url(resp.headers.get("Location", ""), url)
                page.links = [target] if target else []
            elif 200 <= resp.status < 300 and resp.content_type in HTML_TYPES:
                html = await resp.text(errors="replace")
                page.title, page.links = parse_html(html, url)
    except (aiohttp.ClientError, TimeoutError) as exc:
        page.error = str(exc) or type(exc).__name__  # str(TimeoutError()) is ""
    page.elapsed_ms = round((time.perf_counter() - started) * 1000)
    return page


async def fetch_robots(session: aiohttp.ClientSession, url: str) -> RobotFileParser:
    """Read the site's robots.txt, following the rules in RFC 9309.

    No robots.txt (4xx) means everything is allowed. A server error (5xx)
    means nothing is. If it can't be reached at all, we allow everything
    and let the first real request report the problem.
    """
    robots_url = urljoin(url, "/robots.txt")
    lines: list[str] = []
    try:
        async with session.get(robots_url) as resp:
            if resp.status >= 500:
                log.warning("%s returned %s, so the site is off limits", robots_url, resp.status)
                lines = ["User-agent: *", "Disallow: /"]
            elif 200 <= resp.status < 300:
                lines = (await resp.text(errors="replace")).splitlines()
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("could not read %s (%s); assuming everything is allowed", robots_url, exc)
    robots = RobotFileParser(robots_url)
    robots.parse(lines)
    return robots


async def crawl(
    start_url: str,
    *,
    max_pages: int = 100,
    max_depth: int | None = None,
    concurrency: int = 5,
    delay: float = 0.0,
    request_timeout: float = 10.0,
    user_agent: str = DEFAULT_USER_AGENT,
    respect_robots: bool = True,
) -> AsyncIterator[Page]:
    """Crawl one website, yielding each :class:`Page` as soon as it is fetched.

    Only pages on the start URL's site are requested (see
    :func:`~tangrowth.links.site_key`). Every request counts toward
    ``max_pages``, including redirects and errors. ``delay`` is the minimum
    time in seconds between starting two requests; a larger
    ``Crawl-delay`` in robots.txt wins. ``request_timeout`` is how long a
    single request may take, in seconds.

    Use it inside ``contextlib.aclosing()`` so that stopping early (with
    ``break``) cancels the in-flight requests and closes the connection
    pool right away::

        async with aclosing(crawl("https://example.com")) as pages:
            async for page in pages:
                print(page.status, page.url)
    """
    start = normalize_url(start_url, start_url)
    if start is None:
        raise CrawlError(f"not an http(s) URL: {start_url!r}")
    if max_pages < 1 or concurrency < 1:
        raise ValueError("max_pages and concurrency must be at least 1")

    session = aiohttp.ClientSession(
        headers={"User-Agent": user_agent}, timeout=aiohttp.ClientTimeout(total=request_timeout)
    )
    async with session:
        robots = await fetch_robots(session, start) if respect_robots else None
        if robots is not None:
            if not robots.can_fetch(user_agent, start):
                raise CrawlError(f"robots.txt does not allow crawling {start}")
            crawl_delay = float(robots.crawl_delay(user_agent) or 0)
            if crawl_delay > delay:
                log.info("robots.txt asks for %gs between requests", crawl_delay)
                delay = crawl_delay

        sites = {site_key(start)}
        seen = {start}  # every URL ever queued; also our max_pages counter
        frontier = deque([(start, 0, None)])  # (url, depth, referrer) waiting to be fetched
        running: set[asyncio.Task[Page]] = set()
        loop = asyncio.get_running_loop()
        next_start = loop.time()  # earliest time the next request may start

        def should_visit(url: str, depth: int) -> bool:
            return (
                url not in seen
                and len(seen) < max_pages
                and site_key(url) in sites
                and (max_depth is None or depth <= max_depth)
                and (robots is None or robots.can_fetch(user_agent, url))
            )

        try:
            while frontier or running:
                while frontier and len(running) < concurrency:
                    if delay:
                        await asyncio.sleep(max(0.0, next_start - loop.time()))
                        next_start = loop.time() + delay
                    running.add(asyncio.create_task(fetch(session, *frontier.popleft())))

                done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    page = task.result()
                    if page.is_redirect and page.depth == 0:
                        # The start page moved (e.g. http://site -> https://www.site),
                        # so the site we're crawling moves with it.
                        sites.add(site_key(page.links[0]))
                    # A redirect target is the same page, so it keeps the same depth.
                    depth = page.depth if page.is_redirect else page.depth + 1
                    for link in page.links:
                        if should_visit(link, depth):
                            seen.add(link)
                            frontier.append((link, depth, page.url))
                    yield page
        finally:
            # Runs on normal exit, on errors and when the caller stops early.
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)


def broken_links(pages: Iterable[Page]) -> list[tuple[Page, list[str]]]:
    """Pair every broken page with all the crawled pages that link to it."""
    pages = list(pages)
    linked_from: dict[str, list[str]] = {}
    for page in pages:
        for link in page.links:
            linked_from.setdefault(link, []).append(page.url)
    return [(page, linked_from.get(page.url, [])) for page in pages if page.broken]
