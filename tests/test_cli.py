import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tangrowth import __version__
from tangrowth.cli import build_parser, main, run

EXAMPLE = Path(__file__).parent.parent / "examples" / "simple_crawler.py"


async def test_json_output_and_report(site, tmp_path, capsys):
    out = tmp_path / "pages.json"
    args = build_parser().parse_args([site.url("/"), "-o", str(out)])
    pages = []

    assert await run(args, pages) == 1  # broken links found

    rows = json.loads(out.read_text())
    assert len(rows) == len(pages) == 11
    assert {row["url"] for row in rows if row["broken"]} == {
        site.url("/missing"),
        site.url("/error"),
    }

    captured = capsys.readouterr()
    assert "Crawled 11 pages" in captured.out
    assert "Broken links (2):" in captured.out
    assert f"linked from {site.url('/about')}" in captured.out
    assert f"Saved 11 pages to {out}" in captured.out
    # Live progress goes to stderr, so stdout stays clean for the report.
    assert f"200  {site.url('/')}  Home" in captured.err


async def test_csv_output(site, tmp_path):
    out = tmp_path / "pages.csv"
    args = build_parser().parse_args([site.url("/"), "-o", str(out), "-q", "-n", "3"])
    pages = []
    await run(args, pages)

    with out.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["url"] for row in rows] == [page.url for page in pages]
    assert rows[0]["url"] == site.url("/")
    assert rows[0]["status"] == "200"
    assert int(rows[0]["links_count"]) > 5


async def test_exit_code_is_zero_without_broken_links(site, capsys):
    args = build_parser().parse_args([site.url("/new"), "-q"])
    assert await run(args, []) == 0
    assert "No broken links found." in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"tangrowth {__version__}"


def test_bad_start_url_exits_with_2():
    # Run the real command (python -m tangrowth) in its own process.
    result = subprocess.run(
        [sys.executable, "-m", "tangrowth", "ftp://example.com/"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "not an http(s) URL" in result.stderr


def test_url_without_scheme_gets_https():
    assert build_parser().parse_args(["example.com"]).url == "https://example.com"


@pytest.mark.parametrize(
    "argv",
    [
        ["example.com", "-o", "pages.txt"],
        ["example.com", "-o", "no/such/folder/pages.json"],
        ["example.com", "-n", "0"],
        ["example.com", "-c", "-1"],
        ["example.com", "--timeout", "0"],
    ],
)
def test_bad_arguments_are_rejected_before_crawling(argv):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(argv)
    assert exit_info.value.code == 2


async def test_teaching_example_crawls_the_fake_site(site, capsys):
    spec = importlib.util.spec_from_file_location("simple_crawler", EXAMPLE)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)

    seen = await example.crawl(site.url("/"))

    assert site.url("/deep") in seen  # reached through the slow page
    assert "http://external.invalid/page" not in seen
    assert "404 " + site.url("/missing") in capsys.readouterr().out
