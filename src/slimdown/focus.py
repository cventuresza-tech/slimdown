"""Only the parts of a page that answer a question, without calling a model.

The Markdown is split into sections at headings (long sections are cut at paragraph breaks), ranked with BM25 against
the focus text, and the best sections come back in page order with their heading path. Ranking reads each section's own
words; link lists (navigation, "people also looked at") and few-word fragments are discounted, repeated blocks
(reviews, listings, results: three or more sections whose headings link into the same place) are lifted, and a section
whose own heading names everything asked for is lifted further.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9À-ɏ]+(?:['’][a-z]+)?", re.I)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEAD_LINK = re.compile(r"^(#{1,6})\s+\[[^\]]*\]\((?:https?://)?([^/)\s?#]*)(/[^/)\s?#]*)?")
_STOP = set("""a an and are as at be by for from has have how i if in is it its of on or that the this to was
were what when where which who why will with you your our we can do does not no yes about into more most""".split())


@dataclass
class Section:
    idx: int
    path: str
    text: str


def _stem(w: str) -> str:
    """Plural to singular, enough for "reviews" to match "review"."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _tok(s: str) -> list[str]:
    return [_stem(w.lower()) for w in _WORD.findall(_LINK.sub(r"\1", s)) if w.lower() not in _STOP]


def _shape(text: str) -> tuple[float, float]:
    """(share of the visible text that is link text, number of words) for a section."""
    plain = _LINK.sub(r"\1", text)
    link_chars = sum(len(m.group(1)) for m in _LINK.finditer(text))
    return link_chars / max(1, len(plain)), len(plain.split())


def _bm25(docs: list[list[str]], query: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avgdl = (sum(len(d) for d in docs) / n) or 1.0
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1.0) for t, c in df.items()}
    scores = []
    for d in docs:
        tf, dl = Counter(d), len(d)
        scores.append(sum(idf[q] * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * dl / avgdl)) for q in query if q in tf))
    return scores


def _families(cs: list[Section]) -> list[str | None]:
    """A key per section for repeated blocks: sections whose heading links into the same place belong together, and so
    do their continuations. Keys shared by fewer than three headed sections are dropped."""
    keys: list[str | None] = []
    by_path: dict[str, str] = {}
    for c in cs:
        m = _HEAD_LINK.match(c.text)
        key = f"{len(m.group(1))}|{m.group(2)}{m.group(3) or ''}" if m else None
        if key:
            by_path[c.path] = key
        keys.append(key or by_path.get(c.path))
    headed: Counter = Counter(k for c, k in zip(cs, keys) if k and _HEAD_LINK.match(c.text))
    return [k if k and headed[k] >= 3 else None for k in keys]


def sections(md: str, max_chars: int = 1600) -> list[Section]:
    out: list[Section] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            p = " > ".join(h for _, h in path) or "(top)"
            while len(text) > max_chars:
                cut = text.rfind("\n\n", 0, max_chars)
                cut = cut if cut > max_chars // 3 else max_chars
                out.append(Section(len(out), p, text[:cut].strip()))
                text = text[cut:].strip()
            if text:
                out.append(Section(len(out), p, text))
        buf.clear()

    fence = None  # inside a fenced code block, "# comment" lines are code, not headings
    for line in md.split("\n"):
        f = re.match(r"^\s*(```|~~~)", line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        m = None if fence or f else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = [(lv, h) for lv, h in path if lv < level] + [(level, m.group(2).strip()[:120])]
        buf.append(line)
    flush()
    return out


def focus(md: str, query: str, k: int = 6, min_share: float = 0.15) -> tuple[str, int, int]:
    """The sections of `md` that answer `query`: (markdown, sections kept, sections in the page)."""
    cs = sections(md)
    if len(cs) <= 2:
        return md, len(cs), len(cs)
    q = _tok(query)
    if not q:
        return md, len(cs), len(cs)
    fams = _families(cs)
    docs = []
    for c, fam in zip(cs, fams):
        own = (c.path.rsplit(" > ", 1)[-1] + " " if not c.text.lstrip().startswith("#") else "") + c.text
        kind = fam.split("/", 1)[1] if fam and "/" in fam else ""
        docs.append(_tok(own + " " + kind))
    raw = _bm25(docs, q)
    qset = set(q)
    scores = []
    for c, r, fam in zip(cs, raw, fams):
        link_share, words = _shape(c.text)
        named = 1.0 if qset <= set(_tok(c.path.rsplit(" > ", 1)[-1])) else 0.0  # its own heading names the question
        weight = (1 - link_share * (1 - named)) ** 2 * min(1.0, words / 12) * (1.6 if fam else 1.0) * (1 + 2 * named)
        scores.append(r * weight)
    best = max(scores) if scores else 0
    if best <= 0:
        return md, len(cs), len(cs)
    asked = {f for f in set(fams) if f and "/" in f and set(_tok(f.split("/", 1)[1])) & qset}
    members = sorted((i for i in range(len(cs)) if fams[i] in asked), key=lambda i: (-scores[i], i))
    others = sorted((i for i in range(len(cs)) if fams[i] not in asked), key=lambda i: scores[i], reverse=True)
    keep = sorted(members[:k] + [i for i in others[:max(0, k - len(members))] if scores[i] >= best * min_share])
    parts = [f"<!-- section: {cs[i].path} -->\n{cs[i].text}" for i in keep]
    note = f"\n\n<!-- slimdown focus '{query}': {len(keep)} of {len(cs)} sections -->"
    return "\n\n".join(parts) + note, len(keep), len(cs)
