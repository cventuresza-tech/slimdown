"""Benchmark: tokens per page and content kept, slimdown against MarkItDown, Trafilatura, Crawl4AI, Jina Reader and
Firecrawl.

Every local converter gets the same HTML, fetched once over plain HTTP and cached in bench/html/. Pages that plain HTTP
cannot read (bot walls, JavaScript-only apps) are listed and left out. Jina Reader and Firecrawl are hosted services:
they fetch each page themselves.

Content kept is measured against consensus, not against any one tool: a sentence of eight or more words counts as
content when a majority of six independent tools' outputs contain it (slimdown, MarkItDown, Trafilatura with links,
Crawl4AI fit, Jina Reader, Firecrawl). A tool's score is the share of those sentences its output contains.

    uv run --group bench python bench/run.py            # cached HTML and outputs are reused
    uv run --group bench python bench/run.py --refresh  # fetch and convert everything again
Firecrawl needs FIRECRAWL_API_KEY (skipped without it). Jina Reader is called without a key (rate limited).
Raw pages and outputs stay in bench/html and bench/out (not committed: they are other people's content).
"""

from __future__ import annotations

import io
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from slimdown import html_to_markdown  # noqa: E402
from slimdown.detect import classify  # noqa: E402
from slimdown.fetch import FetchError, fetch  # noqa: E402
from slimdown.tokens import count, exact  # noqa: E402

HERE = Path(__file__).resolve().parent
HTML, OUT = HERE / "html", HERE / "out"
REFRESH = "--refresh" in sys.argv
VOTERS = ["slimdown", "MarkItDown", "Trafilatura (links)", "Crawl4AI (fit)", "Jina Reader", "Firecrawl"]


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1]).strip("-")[:90]


def pages() -> list[str]:
    return [l.strip() for l in (HERE / "pages.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]


# ---------------------------------------------------------------- converters

def c_slimdown(url, html):
    return html_to_markdown(html, url)


def c_slimdown_nolinks(url, html):
    return html_to_markdown(html, url, links=False)


def c_markitdown(url, html):
    from markitdown import MarkItDown
    return MarkItDown().convert_stream(io.BytesIO(html.encode("utf-8")), file_extension=".html", url=url).text_content


def c_trafilatura_links(url, html):
    import trafilatura
    return trafilatura.extract(html, url=url, output_format="markdown", include_links=True, include_tables=True,
                               include_formatting=True) or ""


def c_trafilatura(url, html):
    import trafilatura
    return trafilatura.extract(html, url=url, output_format="markdown") or ""


def _crawl4ai(url, html):
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    scraped = LXMLWebScrapingStrategy().scrap(url, html)
    cleaned = getattr(scraped, "cleaned_html", None) or (scraped.get("cleaned_html") if isinstance(scraped, dict) else html)
    return DefaultMarkdownGenerator(content_filter=PruningContentFilter()).generate_markdown(cleaned, base_url=url)


def c_crawl4ai_raw(url, html):
    return _crawl4ai(url, html).raw_markdown


def c_crawl4ai_fit(url, html):
    return _crawl4ai(url, html).fit_markdown


def h_jina(url, _html):
    for attempt in range(3):
        r = httpx.get("https://r.jina.ai/" + url, timeout=90, headers={"User-Agent": "slimdown-bench"})
        if r.status_code == 429:
            time.sleep(30)
            continue
        r.raise_for_status()
        time.sleep(3.5)  # keyless limit: 20 requests a minute
        return r.text
    raise RuntimeError("Jina Reader kept answering 429")


def h_firecrawl(url, _html):
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        raise RuntimeError("no FIRECRAWL_API_KEY")
    r = httpx.post("https://api.firecrawl.dev/v2/scrape", timeout=120, headers={"Authorization": f"Bearer {key}"},
                   json={"url": url, "formats": ["markdown"], "onlyMainContent": True})
    r.raise_for_status()
    return (r.json().get("data") or {}).get("markdown") or ""


LOCAL = {"slimdown": c_slimdown, "slimdown (no links)": c_slimdown_nolinks, "MarkItDown": c_markitdown,
         "Trafilatura (links)": c_trafilatura_links, "Trafilatura": c_trafilatura,
         "Crawl4AI (raw)": c_crawl4ai_raw, "Crawl4AI (fit)": c_crawl4ai_fit}
HOSTED = {"Jina Reader": h_jina, "Firecrawl": h_firecrawl}


# ---------------------------------------------------------------- content measure

def norm(md: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", t)
    t = re.sub(r"⟨\d+⟩", " ", t)  # Crawl4AI citation marks
    t = re.sub(r"[¶§]", " ", t)  # heading permalink marks: some tools keep them, some drop them
    t = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", t)
    t = re.sub(r"[*_`#>|~]", " ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def sentences(text: str) -> set[str]:
    return {s.strip(" -:;,") for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 8}


# ---------------------------------------------------------------- run

def main() -> None:
    HTML.mkdir(exist_ok=True)
    readable, skipped = [], []
    for url in pages():
        f_html, f_meta = HTML / f"{slug(url)}.html", HTML / f"{slug(url)}.json"
        if f_html.exists() and f_meta.exists() and not REFRESH:
            meta = json.loads(f_meta.read_text())
        else:
            try:
                r = fetch(url, timeout=30)
                v = classify(r.status, r.text, r.headers)
                meta = {"url": url, "final_url": r.final_url, "status": r.status, "verdict": v.outcome, "reason": v.reason}
                f_html.write_text(r.text)
            except FetchError as e:
                meta = {"url": url, "verdict": "error", "reason": str(e)}
            f_meta.write_text(json.dumps(meta))
        (readable if meta.get("verdict") == "ok" else skipped).append(meta)
    print(f"{len(readable)} pages readable over plain HTTP; {len(skipped)} left out", flush=True)

    outputs: dict[str, dict[str, str | None]] = {t: {} for t in [*LOCAL, *HOSTED]}

    def run(tool, fn, meta):
        out = OUT / slug(tool) / f"{slug(meta['url'])}.md"
        if out.exists() and not REFRESH:
            return tool, meta["url"], out.read_text()
        html = (HTML / f"{slug(meta['url'])}.html").read_text()
        target = meta["final_url"] if tool in LOCAL else meta["url"]
        try:
            md = fn(target, html)
        except Exception as e:  # noqa: BLE001
            print(f"  {tool} failed on {meta['url']}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return tool, meta["url"], None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md or "")
        return tool, meta["url"], md or ""

    for tool, fn in LOCAL.items():
        for meta in readable:
            t, u, md = run(tool, fn, meta)
            outputs[t][u] = md
        print(f"  {tool}: done", flush=True)
    with ThreadPoolExecutor(3) as ex:  # Firecrawl a few at a time
        for t, u, md in ex.map(lambda m: run("Firecrawl", h_firecrawl, m), readable):
            outputs[t][u] = md
    print("  Firecrawl: done", flush=True)
    for meta in readable:  # Jina one at a time (keyless rate limit)
        t, u, md = run("Jina Reader", h_jina, meta)
        outputs[t][u] = md
    print("  Jina Reader: done", flush=True)

    # consensus content per page, then each tool's tokens and share of it
    per_page, per_tool = [], {t: {"tokens": [], "kept": [], "failed": 0} for t in outputs}
    for meta in readable:
        u = meta["url"]
        texts = {t: norm(outputs[t].get(u) or "") for t in outputs if outputs[t].get(u)}
        voters = [t for t in VOTERS if t in texts]
        cands = set().union(*(sentences(texts[t]) for t in voters)) if voters else set()
        need = len(voters) // 2 + 1
        ref = {s for s in cands if sum(s in texts[t] for t in voters) >= need} if len(voters) >= 4 else set()
        row = {"url": u, "consensus_sentences": len(ref), "voters": len(voters), "tools": {}}
        for t in outputs:
            md = outputs[t].get(u)
            if md is None:
                per_tool[t]["failed"] += 1
                continue
            tok = count(md)
            kept = (sum(s in texts.get(t, "") for s in ref) / len(ref)) if ref else None
            row["tools"][t] = {"tokens": tok, "kept": None if kept is None else round(kept, 3)}
            per_tool[t]["tokens"].append(tok)
            if kept is not None:
                per_tool[t]["kept"].append(kept)
        per_page.append(row)

    summary = []
    for t, d in per_tool.items():
        if not d["tokens"]:
            continue
        summary.append({"tool": t, "pages": len(d["tokens"]), "failed": d["failed"], "total_tokens": sum(d["tokens"]),
                        "median_tokens": int(statistics.median(d["tokens"])),
                        "content_kept": round(statistics.mean(d["kept"]), 3) if d["kept"] else None})
    summary.sort(key=lambda s: s["total_tokens"])
    result = {"date": time.strftime("%Y-%m-%d"), "token_counter": "o200k_base" if exact() else "estimate",
              "pages_compared": len(readable), "pages_left_out": skipped, "summary": summary, "pages": per_page}
    (HERE / "results.json").write_text(json.dumps(result, indent=1))

    base = next((s for s in summary if s["tool"] == "slimdown"), None)
    lines = [f"Benchmark run {result['date']}: {len(readable)} pages, tokens counted with {result['token_counter']}.", "",
             "| Tool | Total tokens | Median per page | Content kept | Failed |", "|---|---:|---:|---:|---:|"]
    for s in summary:
        kept = f"{s['content_kept'] * 100:.1f}%" if s["content_kept"] is not None else "-"
        lines.append(f"| {s['tool']} | {s['total_tokens']:,} | {s['median_tokens']:,} | {kept} | {s['failed']} |")
    if base:
        lines += ["", "slimdown's total compared with each tool's:"]
        for s in summary:
            if s["tool"] != "slimdown":
                lines.append(f"- {s['tool']}: {100 * (1 - base['total_tokens'] / s['total_tokens']):+.0f}% fewer tokens"
                             if s["total_tokens"] else f"- {s['tool']}: n/a")
    lines += ["", "Left out (plain HTTP could not read them):"] + [f"- {m['url']}: {m.get('reason') or m.get('verdict')}" for m in skipped]
    (HERE / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
