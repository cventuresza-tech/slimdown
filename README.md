# slimdown

**Web pages slimmed down to the Markdown an AI needs.**

slimdown reads a web page and returns its main content as Markdown, in as few tokens as it can. It drops navigation, footers, cookie banners, share bars, ads, image embeds and tracking parameters. It shortens links to the same site to their path. Ask for a topic with `focus` and you get only the sections about it.

It comes as a Python library, a CLI and an MCP server. It runs locally and needs no account or key. MIT licensed.

```bash
pip install "slimdown @ git+https://github.com/cventuresza-tech/slimdown"
slimdown https://docs.python.org/3/library/asyncio-task.html --focus "timeouts" --tokens
```

## Benchmark

These are 39 public pages: docs, Wikipedia, essays, blogs, news front pages, government and health pages, package and repository pages, a shop page and marketing pages. Tokens were counted with OpenAI's `o200k_base`.

**Content kept** compares tools without letting any one of them define the content. A sentence of eight or more words counts as content when most of six tools' outputs contain it. The score is the share of those sentences a tool's output contains.

| Tool | Total tokens | Median per page | Content kept |
|---|---:|---:|---:|
| **slimdown** | **236,550** | **3,191** | **95.0%** |
| Crawl4AI (`fit_markdown`, pruning filter) | 267,213 | 3,665 | 92.9% |
| Jina Reader (`r.jina.ai`) | 286,319 | 4,539 | 88.5% |
| Firecrawl (`onlyMainContent`) | 421,856 | 5,536 | 90.1% |
| MarkItDown | 515,967 | 9,100 | 99.5% |
| Crawl4AI (`raw_markdown`) | 559,391 | 9,451 | 97.3% |
| Trafilatura (markdown, links on) | 219,496 | 2,257 | 87.8% |

What this shows:

- **slimdown keeps the most content of the main-content tools.** It uses 44% fewer tokens than Firecrawl, 17% fewer than Jina Reader and 11% fewer than Crawl4AI's filtered output.
- **MarkItDown and Crawl4AI's raw output keep almost everything because they keep everything.** That includes menus and footers, at more than twice the tokens.
- **Trafilatura is the leanest that keeps links, 8% under slimdown, but drops the most content.** Without links, Trafilatura uses 161,631 tokens and keeps 88.1%; `slimdown --no-links` uses 178,964 and keeps 95.0%.

Run 5 Oct 2026. Every local tool converted the same HTML, fetched once. Jina Reader and Firecrawl fetch pages themselves; Jina failed on 3 pages and Firecrawl on 1. Three pages that block plain HTTP (Stack Overflow, timeanddate, IMDb) were left out, because every HTML converter fails on them equally.

Reproduce it with `uv run --group bench python bench/run.py`. The script and page list are in [`bench/`](bench), and per-page numbers are in [`bench/results.json`](bench/results.json).

## Install

Not on PyPI yet: install from GitHub.

```bash
pip install "slimdown @ git+https://github.com/cventuresza-tech/slimdown"            # library and CLI
pip install "slimdown[tokens] @ git+https://github.com/cventuresza-tech/slimdown"    # exact token counts (tiktoken); otherwise estimated
pip install "slimdown[mcp] @ git+https://github.com/cventuresza-tech/slimdown"       # the MCP server
uvx --from git+https://github.com/cventuresza-tech/slimdown slimdown https://example.com   # or run it without installing
```

Python 3.10+.

## CLI

```bash
slimdown https://en.wikipedia.org/wiki/Markdown                 # Markdown on stdout
slimdown https://stripe.com/blog/idempotency -f "retries" -t     # only the sections about retries, token count on stderr
slimdown https://example.com/page --no-links                     # link text only, no addresses
slimdown page.html --url https://example.com/page                # HTML you already have
curl -s https://example.com | slimdown - --url https://example.com
slimdown https://example.com --json                              # status, title, tokens, sections kept
```

## Python

```python
from slimdown import slim, html_to_markdown

page = slim("https://fastapi.tiangolo.com/tutorial/first-steps/", focus="run the server")
page.status      # "ok", "needs_browser", "blocked", "not_found", "unsupported" or "error"
page.markdown    # the sections about running the server
page.tokens      # how many tokens that is
page.note        # what happened, when something did

# HTML from your own headless browser or crawler:
md = html_to_markdown(html, url="https://example.com/article")
```

## MCP server

Give any MCP client, such as Claude Code, Claude Desktop, Cursor or Codex, a `read_page` tool:

```json
{
  "mcpServers": {
    "slimdown": { "command": "uvx", "args": ["--from", "slimdown[mcp] @ git+https://github.com/cventuresza-tech/slimdown", "slimdown-mcp"] }
  }
}
```

For Claude Code: `claude mcp add slimdown -- uvx --from "slimdown[mcp] @ git+https://github.com/cventuresza-tech/slimdown" slimdown-mcp`.

`read_page(url, focus?, links?, country?)` returns the page's lean Markdown under a short header: source, status and token count.

## What it does to a page

1. **Finds the main content.** It uses `<main>`, `<article>` or `[role=main]` when they hold the page's text, and otherwise the body without its furniture: headers, footers, navigation, asides, cookie and consent banners, share bars, newsletter boxes, ads and modals.
2. **Writes lean Markdown.** It keeps headings, lists, tables, code blocks and links, and drops image embeds (a linked image keeps its alt text). It also strips tracking parameters (`utm_*`, `fbclid`, `gclid`…) and permalink marks.
3. **Shortens same-site links to their path** (`/docs/install`). That's the same information in fewer tokens, resolvable against the page's address.
4. **Drops blocks that repeat word for word.** Responsive pages often render a sidebar twice, one copy hidden by CSS.
5. **Focus, without a model.** It splits the page at headings, ranks the sections against your question with BM25, and returns the best ones in page order. It discounts link lists and lifts repeated items such as reviews or results.

## Pages that need more than plain HTTP

slimdown reads what a plain HTTP request gets. Three kinds of page need more:

- apps that build their content with JavaScript;
- sites behind a bot wall;
- pages that differ by country.

slimdown says which, and stops:

```text
$ slimdown https://excalidraw.com/
slimdown: needs_browser · 0 tokens
https://excalidraw.com/: needs a browser (an app shell with little text: the page is built by JavaScript). slimdown
reads plain HTML only. Set SKRYP_API_KEY to read it through Skryp (a real browser, unblocking, any country; free
credits at https://skryp.dev), or render it yourself and pass the HTML to slimdown.html_to_markdown().
```

Set `SKRYP_API_KEY` and those pages are read through [Skryp](https://skryp.dev) instead: a real browser, unblocking, and exits in many countries. The Markdown comes back from the same engine. A free account includes 1,000 credits a month.

```bash
export SKRYP_API_KEY=sk_...
slimdown https://www.example-shop.com/product/123 --country de
```

## Safety

slimdown refuses addresses that resolve to private, loopback or link-local networks at every redirect, unless you pass `allow_private=True` or `--allow-private`. An AI agent reading pages for someone can be talked into requesting `http://169.254.169.254/` or a router's admin page. Responses are capped at 10 MB.

## Licence

MIT. Made by [Skryp](https://skryp.dev), which runs the same engine as a hosted API and MCP server for the pages plain HTTP cannot reach.
