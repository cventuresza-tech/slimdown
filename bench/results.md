Benchmark run 2026-10-05: 39 pages, tokens counted with o200k_base.

| Tool | Total tokens | Median per page | Content kept | Failed |
|---|---:|---:|---:|---:|
| Trafilatura | 161,631 | 2,257 | 88.1% | 0 |
| slimdown (no links) | 178,964 | 2,803 | 95.0% | 0 |
| Trafilatura (links) | 219,496 | 2,257 | 87.8% | 0 |
| slimdown | 236,550 | 3,191 | 95.0% | 0 |
| Crawl4AI (fit) | 267,213 | 3,665 | 92.9% | 0 |
| Jina Reader | 286,319 | 4,539 | 88.5% | 3 |
| Firecrawl | 421,856 | 5,536 | 90.1% | 1 |
| MarkItDown | 515,967 | 9,100 | 99.5% | 0 |
| Crawl4AI (raw) | 559,391 | 9,451 | 97.3% | 0 |

slimdown's total compared with each tool's:
- Trafilatura: -46% fewer tokens
- slimdown (no links): -32% fewer tokens
- Trafilatura (links): -8% fewer tokens
- Crawl4AI (fit): +11% fewer tokens
- Jina Reader: +17% fewer tokens
- Firecrawl: +44% fewer tokens
- MarkItDown: +54% fewer tokens
- Crawl4AI (raw): +58% fewer tokens

Left out (plain HTTP could not read them):
- https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python: Cloudflare challenge
- https://www.timeanddate.com/worldclock/south-africa/johannesburg: Cloudflare challenge
- https://www.imdb.com/title/tt0111161/: aws-waf
