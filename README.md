# Tangrowth

[![CI](https://github.com/mehmetkose/tangrowth/actions/workflows/ci.yml/badge.svg)](https://github.com/mehmetkose/tangrowth/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](https://github.com/mehmetkose/tangrowth/issues)

A small, polite website crawler and broken-link checker built on `asyncio` and `aiohttp`, and a readable example of how to write one.

- **Crawls one site.** It follows links on the same site (`python.org` and `www.python.org` count as one) and leaves everything else alone.
- **Finds broken links.** It reports 404s, 500s and timeouts, together with every page that links to them.
- **Exports results.** Every page can be saved to JSON or CSV.
- **Polite by default.** It honors `robots.txt` and `Crawl-delay`, sends an honest User-Agent, and stops after 100 pages unless you ask for more.
- **Use it as a command or a Python library.** Its only dependency is `aiohttp`.

## Quick start

With [uv](https://docs.astral.sh/uv/) (nothing to install first):

```bash
uvx --from git+https://github.com/mehmetkose/tangrowth tangrowth https://quotes.toscrape.com
```

With pip:

```bash
pip install git+https://github.com/mehmetkose/tangrowth
tangrowth https://quotes.toscrape.com
```

Each page is printed as it's crawled, followed by a summary:

```
$ tangrowth example.com -n 200
200  https://example.com/  Example Site
200  https://example.com/about  About us
301  https://example.com/blog  -> https://example.com/blog/
404  https://example.com/old-pricing  linked from https://example.com/about
...
Crawled 200 pages in 6.4s (194 OK, 3 redirects, 3 broken).
Stopped at the limit of 200 pages; use -n to crawl more.

Broken links (3):
  404  https://example.com/old-pricing
       linked from https://example.com/about
       linked from https://example.com/blog/launch
  500  https://example.com/search
       linked from https://example.com/
  ERR  https://example.com/reports/big  (TimeoutError)
       linked from https://example.com/reports/
```

The per-page lines go to stderr and the summary to stdout, so `tangrowth example.com > report.txt` keeps just the summary.

## Usage

```bash
# Save every page to a spreadsheet (or use pages.json)
tangrowth https://example.com -o pages.csv

# A bigger site, gently: up to 2,000 pages, 2 at a time, half a second apart
tangrowth https://example.com -n 2000 -c 2 --delay 0.5

# Only the start page and the pages it links to directly
tangrowth https://example.com -d 1

# Just the summary
tangrowth https://example.com -q
```

| Option | Default | What it does |
| --- | --- | --- |
| `-o`, `--output FILE` | | Also save every page to `FILE` (`.json` or `.csv`) |
| `-n`, `--max-pages N` | 100 | Stop after `N` requests (redirects and errors count too) |
| `-d`, `--max-depth N` | no limit | Only follow links up to `N` clicks from the start page |
| `-c`, `--concurrency N` | 5 | How many requests run at the same time |
| `--delay SECONDS` | 0 | Minimum time between requests; a larger `Crawl-delay` in robots.txt wins |
| `--timeout SECONDS` | 10 | Give up on a request after this long |
| `--user-agent TEXT` | `tangrowth/2.0.0 (+https://github.com/mehmetkose/tangrowth)` | The User-Agent header to send |
| `--ignore-robots` | off | Don't read robots.txt. Only use this on sites you're allowed to crawl |
| `-q`, `--quiet` | off | Don't print each page as it's crawled |

If you leave out `https://`, it's added for you.

**Exit status:** `0` no broken links · `1` broken links found · `2` error (bad URL, blocked by robots.txt) · `130` stopped with Ctrl-C. When you press Ctrl-C, the pages crawled so far are still reported and saved.

**Output file:** every page has `url`, `status`, `broken`, `error`, `depth`, `referrer` (the page where the URL was first found), `title`, `content_type` and `elapsed_ms`. JSON also includes the full list of `links`; CSV has `links_count` instead.

### Check your site for broken links every week

Tangrowth exits with status 1 when it finds broken links, so it works as a CI check:

```yaml
# .github/workflows/links.yml
name: Broken links
on:
  schedule:
    - cron: "0 6 * * 1" # every Monday at 06:00 UTC
  workflow_dispatch:
jobs:
  links:
    runs-on: ubuntu-latest
    steps:
      - uses: astral-sh/setup-uv@v10
      - run: uvx --from git+https://github.com/mehmetkose/tangrowth tangrowth https://your-site.example -n 1000
```

## Use it from Python

```python
import asyncio
from contextlib import aclosing

from tangrowth import broken_links, crawl


async def main():
    pages = []
    async with aclosing(crawl("https://quotes.toscrape.com", max_pages=50)) as stream:
        async for page in stream:  # pages arrive as soon as they're fetched
            print(page.status, page.url, page.title)
            pages.append(page)

    for page, linked_from in broken_links(pages):
        print("broken:", page.url, "linked from", linked_from)


asyncio.run(main())
```

`crawl()` takes the same options as the command: `max_pages`, `max_depth`, `concurrency`, `delay`, `request_timeout`, `user_agent` and `respect_robots`. Wrapping it in `aclosing()` means that if you `break` out of the loop early, requests still in flight are cancelled and connections are closed straight away.

## What it does and doesn't do

- **One site.** The site is the start URL's host, ignoring `http`/`https` and a leading `www.`. If the start page redirects somewhere else (say, to a new domain), the crawl moves there with it. Other subdomains such as `docs.example.com` count as different sites. Links to other sites are recorded in each page's `links` but never requested.
- **Each URL once.** URLs are normalized (`#fragments` dropped, host lowercased, default ports removed), so `/about` and `/about#team` are the same page. Query strings are kept, so `/list?page=2` is a page of its own.
- **Redirects** are followed one hop at a time, so each one shows up in the results and its target gets the same checks as any other link.
- **HTML only.** Links are read from `<a href>` and `<area href>` in HTML pages, honoring `<base href>`. PDFs, images and error pages are requested (so broken ones are reported) but not read. Stylesheets, scripts and images that pages use are not checked.
- **No JavaScript.** Sites that build their links in the browser will look nearly empty. For those you need a headless browser such as Playwright.
- **robots.txt** is read once, from the start site, following [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309): if there's no robots.txt, everything is allowed; if it returns a server error, the crawl doesn't start.

Crawling someone else's site costs them bandwidth. The defaults are gentle, but for big crawls of sites you don't own, lower `-c` and add a `--delay`.

## How it works

Someone once asked "[how it works?](https://github.com/mehmetkose/tangrowth/issues/2)", so here it is. There are two classic ways to write an async crawler, and this repo has both.

### 1. A queue and some workers: [`examples/simple_crawler.py`](examples/simple_crawler.py)

This is the textbook pattern in about 100 lines, many of them comments, and it needs nothing but aiohttp:

```
            ┌────────────── new links from each page ────────────────┐
            ▼                                                        │
     asyncio.Queue ──► worker 1 ──┐                                  │
       (to visit)  ──► worker 2 ──┼──► fetch the page ──► find links ┘
                   ──► worker 3 ──┘
     main: await queue.join()  ──►  cancel the workers  ──►  done
```

- A few worker tasks loop forever. Each one takes a URL from the queue, fetches it, finds the links, and puts new same-site links back on the queue.
- `queue.join()` returns once every URL that was ever queued has been marked with `task_done()`. That's how the crawl knows it's finished. The key detail is to call `task_done()` only *after* the new links are queued.
- A `seen` set, updated whenever a URL is queued, makes sure no page is fetched twice.

```bash
uv run --with aiohttp examples/simple_crawler.py https://quotes.toscrape.com
```

### 2. One scheduler loop: [`src/tangrowth/crawler.py`](src/tangrowth/crawler.py)

The package uses a single loop that owns all the crawl state:

```python
while frontier or running:
    while frontier and len(running) < concurrency:            # 1. fill the free slots
        running.add(asyncio.create_task(fetch(session, *frontier.popleft())))
    done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
    for task in done:                                          # 2. handle finished pages
        page = task.result()
        for link in page.links:                                # 3. queue the new links
            if should_visit(link, page.depth + 1):
                seen.add(link)
                frontier.append((link, page.depth + 1, page.url))
        yield page                                             # 4. hand the page to the caller
```

Why not workers? Because `crawl()` is an *async generator*, and this shape fits it well:

- It stops exactly when nothing is waiting and nothing is running. There is no `join()` that can hang.
- A bug in `fetch()` shows up as a normal exception, not as a worker that dies silently.
- Only this one loop changes `seen` and `frontier`, so there are no races.
- When the caller stops early, a `finally:` block cancels the requests still in flight.

Everything else is small. [`links.py`](src/tangrowth/links.py) finds links and normalizes URLs; it's all pure functions with no network access. [`cli.py`](src/tangrowth/cli.py) is the command.

## What was wrong with the 2016 version

The [original script](https://github.com/mehmetkose/tangrowth/blob/a02980d/async_crawler.py) was a popular asyncio example, but it no longer runs on modern Python, and its bugs are worth learning from:

| 2016 code | Problem | Now |
| --- | --- | --- |
| `asyncio.wait([coroutines])` | Passing coroutines to `asyncio.wait()` raises `TypeError` since Python 3.11 | Create tasks first (`asyncio.create_task`) |
| `loop = asyncio.get_event_loop()` ... `run_until_complete()` | Deprecated way to start asyncio | `asyncio.run(main())` |
| `with async_timeout.timeout(10):` | Must be `async with`; aiohttp has timeouts built in | `aiohttp.ClientTimeout` |
| `while not work_queue.empty():` | Workers quit when the queue is *briefly* empty, even though other workers are about to add links, so the crawl stops early | `queue.join()`, or the scheduler loop |
| A new `ClientSession()` per request | No connection reuse: slow and wasteful | One session for the whole crawl |
| `html.split('href="')` | Misses `href='...'` and `href=x`, and picks up text inside scripts and comments | `html.parser.HTMLParser` |
| `if root_url in new_url:` | `http://python.org/` is not inside `https://www.python.org/...`, so after python.org's redirect almost nothing was crawled. Meanwhile `http://evil.com/?http://python.org/` passed the check | Compare hosts (`site_key()`) |
| `"%s/sitemap.xml" % root_url` | Produces a double slash: `http://python.org//sitemap.xml` | `urljoin()` |
| `crawled_urls` as a list, filled when a URL is fetched | Slow membership checks, and the same URL could pile up in the queue many times | A `set`, filled when a URL is queued |
| A fake Opera User-Agent, no robots.txt | Impolite | An honest User-Agent and robots.txt support |

## Development

```bash
git clone https://github.com/mehmetkose/tangrowth
cd tangrowth
uv sync                            # creates .venv with the dev tools
uv run pytest                      # tests use a local fake site; no internet needed
uv run ruff check . && uv run ruff format .
uv run tangrowth https://quotes.toscrape.com
```

To publish a release: bump `src/tangrowth/_version.py`, then `uv build && uv publish`.

Issues and pull requests are welcome.

## License

[MIT](LICENSE). Named after Tangrowth, the vine Pokémon, because its vines keep spreading in every direction.
