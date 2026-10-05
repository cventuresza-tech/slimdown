"""slimdown URL | FILE | -   (lean Markdown on stdout)"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import Result, html_to_markdown, slim
from .focus import focus as focus_sections
from .tokens import count, exact


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="slimdown", description="Web pages slimmed down to the Markdown an AI needs.")
    p.add_argument("source", help="a URL, an .html file, or - for HTML on stdin")
    p.add_argument("-f", "--focus", help='only the sections about this, e.g. "pricing"')
    p.add_argument("--no-links", action="store_true", help="keep link text, drop the addresses")
    p.add_argument("--images", action="store_true", help="keep image embeds")
    p.add_argument("--full-page", action="store_true", help="keep navigation, headers and footers too")
    p.add_argument("--long-links", action="store_true", help="keep same-site links as full addresses")
    p.add_argument("--url", help="the page's address, for an .html file or stdin (makes links absolute)")
    p.add_argument("--country", help="read the page as seen from this country (two-letter code; needs SKRYP_API_KEY)")
    p.add_argument("-t", "--tokens", action="store_true", help="print the token count to stderr")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--allow-private", action="store_true", help="allow addresses on private networks")
    p.add_argument("--version", action="version", version=f"slimdown {__version__}")
    a = p.parse_args(argv)

    if a.source == "-" or Path(a.source).is_file():
        html = sys.stdin.read() if a.source == "-" else Path(a.source).read_text(encoding="utf-8", errors="replace")
        md = html_to_markdown(html, a.url, main_content=not a.full_page, links=not a.no_links, images=a.images,
                              short_links=not a.long_links)
        r = Result(url=a.url or a.source, status="ok", markdown=md)
        if a.focus:
            r.markdown, r.sections_kept, r.sections_total = focus_sections(md, a.focus)
        r.tokens = count(r.markdown)
    else:
        r = slim(a.source, focus=a.focus, links=not a.no_links, images=a.images, main_content=not a.full_page,
                 country=a.country, timeout=a.timeout, allow_private=a.allow_private)

    if a.json:
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=1))
    elif r.ok:
        print(r.markdown)
    if a.tokens or not r.ok:
        bits = [f"{r.tokens} tokens{'' if exact() else ' (estimated; pip install slimdown[tokens] for exact counts)'}"]
        if r.sections_total:
            bits.append(f"{r.sections_kept} of {r.sections_total} sections")
        if r.source != "local":
            bits.append(f"via {r.source}")
        print(f"slimdown: {r.status} · " + " · ".join(bits) + (f"\n{r.note}" if r.note else ""), file=sys.stderr)
    return 0 if r.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
