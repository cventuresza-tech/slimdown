"""An MCP server with one tool, read_page: give an agent the web as lean Markdown. Runs locally over stdio.

    {"mcpServers": {"slimdown": {"command": "uvx", "args": ["--from", "slimdown[mcp]", "slimdown-mcp"]}}}

Set SKRYP_API_KEY in its environment to have pages that need a browser, sit behind a bot wall or must be seen from
another country read through Skryp (https://skryp.dev).
"""

from __future__ import annotations

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .core import slim

server = _Server(
    "slimdown",
    instructions=("read_page returns a web page's main content as lean Markdown: no navigation, footers, cookie banners "
                  "or ads, same-site links shortened to their path. Pass focus to get only the sections about a topic. "
                  "When a page needs a browser or is blocked, the answer says so."),
)


@server.tool()
def read_page(url: str, focus: str | None = None, links: bool = True, country: str | None = None) -> str:
    """Read a web page as lean Markdown: its main content only, in as few tokens as possible.

    url: the page (http or https).
    focus: return only the sections about this, e.g. "pricing" or "installation". Saves most of the page's tokens.
    links: false keeps link text but drops the addresses.
    country: two-letter code to read the page as seen from that country (needs SKRYP_API_KEY).
    Links to the same site are shortened to their path; resolve them against the Source line.
    """
    r = slim(url, focus=focus, links=links, country=country)
    head = [f"Source: {r.final_url or r.url}", f"Status: {r.status}" + (f" ({r.source})" if r.source != "local" else ""),
            f"Tokens: {r.tokens}" + (f", {r.sections_kept} of {r.sections_total} sections" if r.sections_total else "")]
    if r.title:
        head.insert(0, f"Title: {r.title}")
    if r.note:
        head.append(f"Note: {r.note}")
    return "\n".join(head) + ("\n\n" + r.markdown if r.markdown else "")


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
