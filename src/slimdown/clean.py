"""HTML to lean Markdown: the page's main content, without the furniture around it, in as few tokens as it can.

This is the engine Skryp (https://skryp.dev) uses for its own Markdown output, published on its own.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import html_to_markdown as h2m
from selectolax.lexbor import LexborHTMLParser

# Elements that are never content.
_ALWAYS_DROP = ("script", "style", "noscript", "template", "iframe", "object", "embed", "canvas", "svg",
                "link", "meta", "base", "dialog")
# Page furniture dropped in main-content mode (tag level).
_FURNITURE_TAGS = ("header", "footer", "nav", "aside", "form")
_FURNITURE_ROLES = ("navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alertdialog")
# Whole class/id names that mark page furniture. Matched against complete names only: splitting on "-"
# would drop content like "product-header" or "match-header".
_FURNITURE_NAMES = {
    "header", "footer", "nav", "navbar", "navigation", "menu", "megamenu", "mega-menu", "sidebar", "site-header",
    "site-footer", "global-header", "global-footer", "page-footer", "main-nav", "site-nav", "top-nav", "topbar",
    "top-bar", "toolbar", "breadcrumb", "breadcrumbs", "skip-link", "skiplink", "share", "sharing", "social",
    "social-links", "social-share", "share-buttons", "newsletter", "subscribe", "popup", "modal", "overlay",
    "advert", "advertisement", "ads", "adsbygoogle", "sponsored", "related-posts", "comments", "comment-list",
    "announcement", "announcement-bar", "promo-bar", "cookie", "cookies", "consent",
}
_FURNITURE_PREFIX = ("cookie-", "cookie_", "consent-", "gdpr", "newsletter-", "advert-", "ad-slot", "ad-container",
                     "social-share", "share-bar", "onetrust", "cky-", "cmp-", "didomi")
_ZERO_WIDTH = re.compile("[​‌‍﻿]")
_CARD_PARTS = "div,p,h1,h2,h3,h4,h5,h6,li,ul,ol,section,article,figure,figcaption,time"
_CONSOLE_TAGS = re.compile(r"</?(?:font|span|b|u)\b[^>]*>")
# feature tables draw yes and no as icons (<i class="icon-tick02">, <svg aria-label="Included">), which Markdown drops:
# ScrapingBee's plan matrix came out as feature names with no values (customer-test agent, 5 Oct 2026)
_ICON_YES = {"tick", "check", "checkmark", "included", "yes"}
_ICON_NO = {"cross", "times", "xmark", "close", "no", "excluded", "unavailable"}  # not "x": inset-x-0
_CELLS = {"td", "th", "li", "div", "p", "dd", "dt"}
_BLOCKS = set(_CARD_PARTS.split(","))


def _names(value: str | None) -> set[str]:
    return {p for p in re.split(r"\s+", (value or "").lower()) if p}


def _is_furniture(names: set[str]) -> bool:
    return bool(names & _FURNITURE_NAMES) or any(n.startswith(_FURNITURE_PREFIX) for n in names)


def _icon_mark(node) -> str | None:
    """✓ or ✗ for an empty icon that is the whole content of its cell, by its class, label or title; else None.
    Icons inside links and buttons (menus, close buttons) are left alone."""
    if node.text(strip=True) and node.tag != "svg":
        return None
    a = node.attributes
    words: set[str] = set()
    for v in (a.get("class"), a.get("aria-label"), a.get("title"), a.get("data-icon")):
        words.update(re.sub(r"\d+$", "", w) for w in re.split(r"[\s_-]+", (v or "").lower()) if w)
    if node.tag == "svg" and (t := node.css_first("title")):
        words.update(re.split(r"\W+", t.text().lower()))
    yes, no = words & _ICON_YES, words & _ICON_NO
    mark = "✗" if no or (yes and words & {"not", "without"}) else "✓" if yes else None  # "Not included" is a no
    if not mark:
        return None
    cell = node.parent
    while cell is not None and cell.tag not in _CELLS:
        if cell.tag in ("a", "button", "label", "summary"):
            return None
        cell = cell.parent
    return mark if cell is not None and not cell.text(strip=True) else None


def _abs(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None
    try:
        u = urljoin(base, href) if base else href
    except ValueError:
        return None
    return u.split("#", 1)[0] if u.startswith(("http://", "https://")) else None


def title(html: str) -> str | None:
    t = LexborHTMLParser(html).css_first("title")
    return re.sub(r"\s+", " ", t.text(strip=True)) if t else None


def _main_root(tree: LexborHTMLParser):
    """Pick <main>/<article>/[role=main] when it clearly holds the content, else <body>."""
    body = tree.body
    if body is None:
        return None
    body_len = len(body.text(strip=True))
    for sel in ("main", '[role="main"]', "#main-content", "#content", "article"):
        nodes = tree.css(sel)
        if len(nodes) == 1:
            n = nodes[0]
            if len(n.text(strip=True)) >= max(300, 0.35 * body_len):
                return n
    return body


def clean_html(html: str, base: str = "", *, main_content: bool = True) -> str:
    """The HTML that holds the content: no scripts or styles, and in main-content mode no navigation, headers, footers,
    cookie banners, share bars or ads. Links and images are made absolute."""
    tree = LexborHTMLParser(html)
    for n in tree.css("i, svg, span[class], em[class]"):
        if (mark := _icon_mark(n)):
            n.replace_with(mark)
    for n in tree.css("td, th, div, span, p, li"):
        c = n.child  # a cell that is only "-" (not included) became an empty list item, which is dropped
        if c is not None and c.next is None and c.tag == "-text" and (c.text_content or "").strip() in ("-", "–"):
            c.replace_with("—")
    for sel in _ALWAYS_DROP:
        for n in tree.css(sel):
            n.decompose()
    root = tree.body
    if main_content:
        root = _main_root(tree)
        if root is None:
            return ""
        for n in root.css(",".join(_FURNITURE_TAGS)):
            # keep a <header>/<footer> that sits inside an article (it often holds the title or byline)
            if n.tag in ("header", "footer") and n.parent is not None and n.parent.tag in ("article",):
                continue
            n.decompose()
        for role in _FURNITURE_ROLES:
            for n in root.css(f'[role="{role}"]'):
                n.decompose()
        for n in root.css("[id],[class]"):
            names = _names(n.attributes.get("id")) | _names(n.attributes.get("class"))
            if _is_furniture(names) and n.tag not in ("main", "article", "body", "html"):
                if len((n.text(strip=True) or "")) < 4000:
                    n.decompose()
        for n in root.css('[aria-hidden="true"], [hidden]'):
            n.decompose()
    if root is None:
        return ""
    # code keeps only its text: highlighters wrap commands in <span>/<font>, which leaked into Markdown code blocks
    # ("<font color=...>uv run fastapi</font> dev", customer-test agent, 5 Oct 2026)
    for el in (root.css("pre *") if root else []):
        if el.tag != "code":
            el.unwrap()
    # terminal demos drawn by termynal (FastAPI, Typer and SQLModel docs) keep their colours as tags written into the
    # code's text for a script to draw: "<font color=...>uv run fastapi</font> dev". The command is shown without them.
    for code in (root.css(".termy pre, [data-termynal] pre") if root else []):
        text = code.text(deep=True)
        plain = _CONSOLE_TAGS.sub("", text)
        if plain != text:
            for child in list(code.iter(include_text=True)):
                child.decompose()
            code.insert_child(plain)
    # a link around a whole card (headline, summary, time, section) would come out as one glued word-run
    # ("housing protestsPedro Sanchez…ago UK"): separate the card's parts
    for a in root.css("a"):
        if a.css_first(_CARD_PARTS):
            for el in a.css("*"):
                el.insert_after(" ")
    # a table cell with a label and a description in separate blocks came out glued ("Standard requestOur own network"):
    # separate them, including spans styled as blocks (class "block", "d-block")
    for cell in root.css("td, th"):
        for el in cell.css("*"):
            if el.tag in _BLOCKS or _names(el.attributes.get("class")) & {"block", "d-block", "flex", "grid"}:
                el.insert_before(" ")
                el.insert_after(" ")
    for a in root.css("a[href]"):
        u = _abs(base, a.attributes.get("href"))
        if u:
            a.attrs["href"] = u
        else:
            del a.attrs["href"]
    for img in root.css("img"):
        a = img.attributes
        u = _abs(base, a.get("src") or a.get("data-src") or a.get("data-lazy-src"))
        if u:
            img.attrs["src"] = u
        else:
            img.decompose()
    return root.html or ""


_MD_OPTS = h2m.ConversionOptions(extract_metadata=False, heading_style="atx", code_block_style="backticks",
                                 wrap=False, escape_asterisks=False, escape_underscores=False, escape_misc=False)


def to_markdown(clean: str) -> str:
    if not clean.strip():
        return ""
    md = h2m.convert(clean, _MD_OPTS)
    md = getattr(md, "content", md)  # html-to-markdown 3 returns a result object; 2 returned a string
    md = _ZERO_WIDTH.sub("", md)
    md = re.sub(r"!\[[^\]]*\]\(data:[^)]*\)", "", md)  # inline base64 images
    md = re.sub(r"(?<!!)\[\s*\]\([^)]*\)", "", md)  # empty links
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


_TRACKING = re.compile(r"([?&])(utm_[a-z]+|fbclid|gclid|gbraid|wbraid|mc_cid|mc_eid|_hsenc|_hsmi|mkt_tok|yclid|igshid|ref_src)=[^&#)\s]*", re.I)
# an address may hold one level of brackets (Wikipedia's File:Drakensberg_(16261357780).jpg): stopping at the first
# ")" left ".jpg)" lines behind when images were dropped (customer test, 5 Oct 2026)
_URL = r"(?:[^()\s]|\([^()\s]*\))"
_LINKED_IMG = re.compile(r"\[((?:\s*!\[[^\]]*\]\(" + _URL + r"*\)\s*(?:\\\\)?\s*)+)\]\((" + _URL + r"+)(?:\s+\"[^\"]*\")?\)")  # a link around images
_IMG = re.compile(r"!\[([^\]]*)\]\(" + _URL + r"*(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((" + _URL + r"+)(?:\s+\"[^\"]*\")?\)")


def _strip_tracking(md: str) -> str:
    def fix(m: re.Match) -> str:
        return m.group(1) if m.group(1) == "?" else ""
    out = _TRACKING.sub(fix, md)
    return re.sub(r"\?&", "?", re.sub(r"\?(?=[)\s])", "", out))


def _linked_images(m: re.Match) -> str:
    """A link around images becomes a link labelled with the first image's alt text (nothing when none has one)."""
    alts = [a.strip() for a in re.findall(r"!\[([^\]]*)\]", m.group(1)) if a.strip()]
    return f"[{alts[0]}]({m.group(2)})" if alts else ""


def _host(u: str) -> str:
    h = (urlsplit(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def shorten_links(md: str, base: str) -> str:
    """Links to the page's own site keep only their path ("/docs/install"): the same information in fewer tokens,
    resolvable against the page's address."""
    site = _host(base)
    if not site:
        return md

    def fix(m: re.Match) -> str:
        url = m.group(2)
        if _host(url) != site:
            return m.group(0)
        p = urlsplit(url)
        short = (p.path or "/") + (f"?{p.query}" if p.query else "")
        return f"[{m.group(1)}]({short})"
    return _LINK.sub(fix, md)


def _collapse_spaces(md: str) -> str:
    """Runs of spaces between words (left by separated card parts) become one; indentation and code stay as they are."""
    out, fence = [], None
    for line in md.split("\n"):
        f = re.match(r"^\s*(```|~~~)", line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        out.append(line if fence or f else re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line))
    return "\n".join(out)


def dedupe_blocks(md: str, min_chars: int = 40) -> str:
    """Drop a block (paragraph, list, table) that repeats an earlier one word for word. Responsive pages often render the
    same sidebar or menu twice (one copy for phones, hidden by CSS that a converter cannot see). Code is never touched."""
    blocks, buf, fence = [], [], None
    for line in md.split("\n"):
        f = re.match(r"^\s*(```|~~~)", line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        if not line.strip() and fence is None:
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    seen, out = set(), []
    for b in blocks:
        key = re.sub(r"\s+", " ", b).strip()
        if len(key) >= min_chars and not key.startswith(("```", "~~~")):
            if key in seen:
                continue
            seen.add(key)
        out.append(b)
    return "\n\n".join(out)


def lean_markdown(md: str, *, images: bool = False, links: bool = True, base: str | None = None) -> str:
    """Agent-lean output: image embeds dropped (their addresses are long and rarely useful; linked images keep their
    alt text), tracking parameters and heading permalink marks stripped, same-site links shortened to their path.
    links=False keeps only the link text."""
    if not images:
        md = _LINKED_IMG.sub(_linked_images, md)
        md = _IMG.sub("", md)
    md = re.sub(r"\[((.{4,120}?)\2+)\]\(", r"[\2](", md)  # a link around several images repeats their alt text: keep one
    md = re.sub(r"\[(?:¶|#|§|🔗)\]\([^)]*\)", "", md)
    md = md.replace("¶", "")
    md = _strip_tracking(md)
    if not links:
        md = _LINK.sub(r"\1", md)
    elif base:
        md = shorten_links(md, base)
    md = re.sub(r"^\s*[-*]\s*$", "", md, flags=re.M)
    md = _collapse_spaces(md)
    md = dedupe_blocks(md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def visible_chars(md: str) -> int:
    return len(re.sub(r"\s+", "", _LINK.sub(r"\1", md)))
