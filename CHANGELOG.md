# Changelog

## 2.0.0 (2026-10-20)

A complete rewrite: the 2016 script no longer ran on current Python.

- Installable package with a `tangrowth` command and a Python API (`tangrowth.crawl`).
- Broken-link report that lists every page linking to each broken URL. The command exits with status 1 when it finds broken links, so it can be used in CI.
- JSON and CSV export (`-o pages.json`, `-o pages.csv`).
- Polite by default: honors robots.txt and `Crawl-delay`, sends an honest User-Agent, has page and depth limits (`-n`, `-d`) and an optional delay between requests (`--delay`).
- Redirects are followed one hop at a time and checked like any other link. `www.` and `http`/`https` variants count as the same site.
- New teaching example: `examples/simple_crawler.py`.
- Tests run against a local fake site; CI covers Python 3.11 to 3.14.
- Requires Python 3.11+ and aiohttp 3.11+.

## Before 2.0.0 (2016–2017)

A single, unversioned example script, `async_crawler.py`. See [commit a02980d](https://github.com/mehmetkose/tangrowth/tree/a02980d).
