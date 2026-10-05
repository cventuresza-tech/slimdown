"""slim(url) and html_to_markdown(html): the two things slimdown does."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

import httpx

from . import skryp
from .clean import clean_html, lean_markdown, title as page_title, to_markdown, visible_chars
from .detect import classify
from .fetch import FetchError, fetch
from .focus import focus as focus_sections
from .tokens import count


@dataclass
class Result:
    url: str
    status: str  # ok | needs_browser | blocked | not_found | unsupported | error
    markdown: str = ""
    title: str | None = None
    final_url: str | None = None
    tokens: int = 0
    source: str = "local"  # local | skryp
    note: str | None = None
    sections_kept: int | None = None
    sections_total: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return asdict(self)


def html_to_markdown(html: str, url: str | None = None, *, main_content: bool = True, links: bool = True,
                     images: bool = False, short_links: bool = True) -> str:
    """Lean Markdown from HTML you already have (from a headless browser, a crawler or a file). With `url`, links are
    made absolute, and links to the same site keep only their path unless short_links=False."""
    base = url or ""
    md = lean_markdown(to_markdown(clean_html(html, base, main_content=main_content)), images=images, links=links,
                       base=url if (url and short_links) else None)
    if main_content:
        # main-content mode can miss on unusual layouts: fall back to the whole page when it kept almost nothing
        full = lean_markdown(to_markdown(clean_html(html, base, main_content=False)), images=images, links=links,
                             base=url if (url and short_links) else None)
        if visible_chars(md) < 200 and visible_chars(full) > 3 * max(1, visible_chars(md)):
            return full
    return md


def _finish(r: Result, focus: str | None) -> Result:
    if focus and r.markdown and r.source == "local":
        r.markdown, r.sections_kept, r.sections_total = focus_sections(r.markdown, focus)
    r.tokens = count(r.markdown)
    return r


def _via_skryp(url: str, key: str, why: str, *, focus: str | None, country: str | None, images: bool,
               main_content: bool, transport: httpx.BaseTransport | None) -> Result:
    d = skryp.scrape(url, key, focus=focus, country=country, images=images, main_content=main_content,
                     transport=transport)
    md = d.get("markdown") or ""
    receipt = d.get("receipt") or {}
    status = {"ok": "ok", "not_found": "not_found", "blocked": "blocked"}.get(d.get("status") or "", "error")
    note = f"{why}; read through Skryp ({receipt.get('route') or 'route not reported'}, {receipt.get('credits', '?')} credits)"
    if status != "ok":
        note = f"{why}; Skryp: {d.get('error') or d.get('status') or 'no result'}"
    return _finish(Result(url=url, status=status, markdown=md, title=(d.get("metadata") or {}).get("title"),
                          final_url=(d.get("metadata") or {}).get("url") or url, source="skryp", note=note), None)


def _needs_skryp(why: str) -> str:
    return (f"{why}. slimdown reads plain HTML only. Set SKRYP_API_KEY to read it through Skryp "
            f"(a real browser, unblocking, any country; free credits at {skryp.SIGNUP}), or render it yourself and "
            "pass the HTML to slimdown.html_to_markdown().")


def slim(url: str, *, focus: str | None = None, links: bool = True, images: bool = False, main_content: bool = True,
         country: str | None = None, skryp_api_key: str | None = None, timeout: float = 20.0,
         allow_private: bool = False, transport: httpx.BaseTransport | None = None) -> Result:
    """Read a web page as lean Markdown.

    focus: return only the sections about this ("pricing", "installation", "refund policy").
    links=False keeps link text only; images=True keeps image embeds; main_content=False keeps the whole page.
    country / skryp_api_key: pages that need a browser, are behind a bot wall, or must be seen from another country are
    read through Skryp when a key is given or SKRYP_API_KEY is set; otherwise the result says what is needed.
    """
    key = skryp_api_key if skryp_api_key is not None else os.environ.get("SKRYP_API_KEY", "").strip()
    escalate = dict(focus=focus, country=country, images=images, main_content=main_content, transport=transport)
    if country:
        if key:
            return _via_skryp(url, key, f"seen from {country.upper()}", **escalate)
        return Result(url=url, status="unsupported", note=_needs_skryp(f"Reading a page as seen from {country.upper()} needs an exit in that country"))
    try:
        f = fetch(url, timeout=timeout, allow_private=allow_private, transport=transport)
    except FetchError as e:
        return Result(url=url, status="error", note=str(e))
    ctype = f.content_type.split(";", 1)[0].strip().lower()
    if ctype in ("text/plain", "text/markdown", "text/x-markdown"):
        return _finish(Result(url=url, status="ok", markdown=f.text.strip(), final_url=f.final_url), focus)
    if ctype in ("application/json", "application/ld+json") or ctype.endswith("+json"):
        try:
            body = json.dumps(json.loads(f.text), indent=1, ensure_ascii=False)
        except ValueError:
            body = f.text
        return _finish(Result(url=url, status="ok", markdown=f"```json\n{body.strip()}\n```", final_url=f.final_url), None)
    if ctype and ctype not in ("text/html", "application/xhtml+xml") and not ctype.startswith("text/"):
        why = f"{url} is {ctype}, not a web page"
        if key:
            return _via_skryp(url, key, why, **escalate)
        return Result(url=url, status="unsupported", final_url=f.final_url, note=_needs_skryp(why))
    v = classify(f.status, f.text, f.headers)
    if v.outcome in ("blocked", "needs_browser"):
        why = f"{url}: {'blocked' if v.outcome == 'blocked' else 'needs a browser'} ({v.reason})"
        if key:
            return _via_skryp(url, key, why, **escalate)
        return Result(url=url, status=v.outcome, final_url=f.final_url, title=page_title(f.text), note=_needs_skryp(why))
    if v.outcome == "not_found":
        return Result(url=url, status="not_found", final_url=f.final_url, note=v.reason)
    if v.outcome in ("error", "empty"):
        return Result(url=url, status="error", final_url=f.final_url, note=v.reason)
    md = html_to_markdown(f.text, f.final_url, main_content=main_content, links=links, images=images)
    note = "the page was larger than 10 MB and was cut" if f.truncated else None
    return _finish(Result(url=url, status="ok", markdown=md, title=page_title(f.text), final_url=f.final_url, note=note), focus)
