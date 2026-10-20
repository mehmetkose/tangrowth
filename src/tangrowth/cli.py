"""Command-line interface: ``tangrowth https://example.com``.

Each page is printed to stderr as it is crawled; the final report goes to
stdout, so ``tangrowth https://example.com > report.txt`` keeps just the
report.
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from contextlib import aclosing
from dataclasses import asdict
from pathlib import Path

from ._version import __version__
from .crawler import DEFAULT_USER_AGENT, CrawlError, Page, broken_links, crawl

OUTPUT_FORMATS = (".json", ".csv")
CSV_FIELDS = [
    "url",
    "status",
    "broken",
    "error",
    "depth",
    "referrer",
    "title",
    "content_type",
    "elapsed_ms",
    "links_count",
]
MAX_REFERRERS_SHOWN = 5


def _number(kind: type, *, allow_zero: bool):
    """An argparse ``type=`` that rejects negative (and optionally zero) numbers."""

    def parse(text: str):
        value = kind(text)
        if value < 0 or (value == 0 and not allow_zero):
            raise argparse.ArgumentTypeError("must be 0 or more" if allow_zero else "must be > 0")
        return value

    parse.__name__ = kind.__name__  # so bad input reads "invalid int value"
    return parse


def _start_url(text: str) -> str:
    return text if "://" in text else f"https://{text}"


def _output_path(text: str) -> Path:
    path = Path(text)
    if path.suffix.lower() not in OUTPUT_FORMATS:
        raise argparse.ArgumentTypeError("the file name must end in .json or .csv")
    if not path.parent.is_dir():
        raise argparse.ArgumentTypeError(f"folder {path.parent} does not exist")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tangrowth",
        description="Crawl a website, list its pages and find broken links.",
        epilog="Exit status: 0 = no broken links, 1 = broken links found, 2 = error.",
    )
    parser.add_argument("url", type=_start_url, help="where to start, e.g. https://example.com")
    parser.add_argument(
        "-o",
        "--output",
        type=_output_path,
        metavar="FILE",
        help="also save every page to FILE (.json or .csv)",
    )
    parser.add_argument(
        "-n",
        "--max-pages",
        type=_number(int, allow_zero=False),
        default=100,
        metavar="N",
        help="stop after N requests (default: %(default)s)",
    )
    parser.add_argument(
        "-d",
        "--max-depth",
        type=_number(int, allow_zero=True),
        metavar="N",
        help="only follow links up to N clicks away from the start page",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=_number(int, allow_zero=False),
        default=5,
        metavar="N",
        help="requests in flight at once (default: %(default)s)",
    )
    parser.add_argument(
        "--delay",
        type=_number(float, allow_zero=True),
        default=0.0,
        metavar="SECONDS",
        help="minimum time between requests (default: %(default)s; "
        "a larger robots.txt Crawl-delay wins)",
    )
    parser.add_argument(
        "--timeout",
        type=_number(float, allow_zero=False),
        default=10.0,
        metavar="SECONDS",
        help="give up on a request after this long (default: %(default)s)",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        metavar="TEXT",
        help="User-Agent header to send (default: %(default)s)",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="don't read robots.txt (only for sites you are allowed to crawl)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="don't print each page as it is crawled"
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _pages(count: int) -> str:
    return f"{count} page" if count == 1 else f"{count} pages"


def _status(page: Page) -> str:
    return str(page.status) if page.status is not None else "ERR"


def format_page(page: Page) -> str:
    """One line per page, e.g. ``404  https://example.com/x  linked from https://example.com/``."""
    if page.error:
        note = page.error
    elif page.is_redirect:
        note = f"-> {page.links[0]}"
    elif page.broken:
        note = f"linked from {page.referrer}" if page.referrer else "(start page)"
    else:
        note = page.title or ""
    return f"{_status(page):>3}  {page.url}  {note}".rstrip()


def write_output(pages: list[Page], path: Path) -> None:
    rows = [asdict(page) | {"broken": page.broken} for page in pages]
    if path.suffix.lower() == ".json":
        text = json.dumps(rows, indent=2, ensure_ascii=False)
        path.write_text(text + "\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            row["links_count"] = len(row.pop("links"))
            writer.writerow(row)


def report(args: argparse.Namespace, pages: list[Page], elapsed: float) -> int:
    """Save the output file, print the summary, and return the exit status."""
    if args.output:
        write_output(pages, args.output)

    broken = broken_links(pages)
    ok = sum(1 for p in pages if p.status is not None and 200 <= p.status < 300)
    redirects = sum(1 for p in pages if p.is_redirect)
    print(
        f"Crawled {_pages(len(pages))} in {elapsed:.1f}s "
        f"({ok} OK, {redirects} redirects, {len(broken)} broken)."
    )
    if len(pages) >= args.max_pages:
        print(f"Stopped at the limit of {_pages(args.max_pages)}; use -n to crawl more.")

    if broken:
        print(f"\nBroken links ({len(broken)}):")
        for page, referrers in broken:
            error = f"  ({page.error})" if page.error else ""
            print(f"  {_status(page):>3}  {page.url}{error}")
            for referrer in referrers[:MAX_REFERRERS_SHOWN]:
                print(f"       linked from {referrer}")
            if len(referrers) > MAX_REFERRERS_SHOWN:
                print(f"       ...and {_pages(len(referrers) - MAX_REFERRERS_SHOWN)} more")
            if not referrers:
                print("       (the start page)")
    else:
        print("No broken links found.")

    if args.output:
        print(f"\nSaved {_pages(len(pages))} to {args.output}")
    return 1 if broken else 0


async def run(args: argparse.Namespace, pages: list[Page]) -> int:
    """Crawl as the command-line ``args`` say, collecting results into ``pages``."""
    started = time.monotonic()
    stream = crawl(
        args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        concurrency=args.concurrency,
        delay=args.delay,
        request_timeout=args.timeout,
        user_agent=args.user_agent,
        respect_robots=not args.ignore_robots,
    )
    async with aclosing(stream):
        async for page in stream:
            pages.append(page)
            if not args.quiet:
                print(format_page(page), file=sys.stderr, flush=True)
    return report(args, pages, time.monotonic() - started)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    handler = logging.StreamHandler()  # robots.txt notices etc. go to stderr
    handler.setFormatter(logging.Formatter("tangrowth: %(message)s"))
    logger = logging.getLogger("tangrowth")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    pages: list[Page] = []
    started = time.monotonic()
    try:
        return asyncio.run(run(args, pages))
    except CrawlError as exc:
        print(f"tangrowth: error: {exc}", file=sys.stderr)
        if "robots.txt" in str(exc):
            print("Use --ignore-robots if you are allowed to crawl it anyway.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Results so far:\n", file=sys.stderr)
        report(args, pages, time.monotonic() - started)
        return 130
    finally:
        logger.removeHandler(handler)


if __name__ == "__main__":
    sys.exit(main())
