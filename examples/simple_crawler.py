"""A minimal async web crawler: the classic asyncio.Queue + workers pattern.

This is the teaching version of Tangrowth. It only needs aiohttp:

    uv run --with aiohttp examples/simple_crawler.py https://quotes.toscrape.com
    # or: pip install aiohttp && python examples/simple_crawler.py

It crawls one site, prints each URL as it is fetched, and stops after
MAX_PAGES. The real package (src/tangrowth) adds robots.txt support,
careful redirect handling, broken-link reports and JSON/CSV export.
"""

import asyncio
import sys
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

import aiohttp

MAX_PAGES = 50
WORKERS = 5


class LinkParser(HTMLParser):
    """Collects the href of every <a> tag. Much safer than a regex."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href")
        if tag == "a" and href:
            self.links.append(href)


def extract_links(html: str, base: str) -> set[str]:
    parser = LinkParser()
    parser.feed(html)
    # Make links absolute and drop "#fragments", so /page and /page#top are one URL.
    return {urldefrag(urljoin(base, href.strip())).url for href in parser.links}


def site(url: str) -> str:
    # Treat example.com and www.example.com as the same site.
    return (urlsplit(url).hostname or "").removeprefix("www.")


async def worker(session, queue, seen, home, max_pages):
    while True:
        url = await queue.get()  # sleeps here until there is work (or we're cancelled)
        try:
            async with session.get(url) as resp:  # follows redirects automatically
                print(resp.status, url)
                if resp.content_type != "text/html":
                    continue  # images, PDFs... have no links for us (finally still runs)
                html = await resp.text(errors="replace")
                base = str(resp.url)  # the URL we ended up at, after any redirects
            for link in extract_links(html, base):
                # Mark a URL as seen *when we queue it*, not when we fetch it,
                # so two workers can never queue the same page twice.
                if site(link) == home and link not in seen and len(seen) < max_pages:
                    seen.add(link)
                    queue.put_nowait(link)
        except Exception as exc:
            # Never let one bad page kill a worker: if every worker died,
            # nobody would finish the queue and queue.join() would wait forever.
            print("ERR", url, repr(exc))
        finally:
            # Called *after* the new links are queued. If we said "done"
            # first, join() could see an empty queue and stop the crawl early,
            # which is exactly the bug the 2016 version of this file had.
            queue.task_done()


async def crawl(start_url: str, max_pages: int = MAX_PAGES, workers: int = WORKERS) -> set[str]:
    seen = {start_url}
    # Unbounded on purpose: workers put() into the queue they read from, so a
    # size limit could leave every worker blocked on put() forever.
    queue: asyncio.Queue[str] = asyncio.Queue()
    queue.put_nowait(start_url)

    # One session for the whole crawl, so connections are reused.
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            asyncio.create_task(worker(session, queue, seen, site(start_url), max_pages))
            for _ in range(workers)
        ]
        await queue.join()  # returns once every queued URL has been processed
        for task in tasks:
            task.cancel()  # the workers are idle in queue.get(); stop them
        await asyncio.gather(*tasks, return_exceptions=True)
        # On Python 3.13+ you could call queue.shutdown() instead of cancelling.
    return seen


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "https://quotes.toscrape.com/"
    pages = asyncio.run(crawl(start))
    print(f"\nCrawled {len(pages)} pages.")
