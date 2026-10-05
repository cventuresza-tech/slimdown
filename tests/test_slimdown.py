import json
import subprocess
import sys

import httpx
import pytest

from slimdown import focus, html_to_markdown, slim
from slimdown.detect import classify
from slimdown.fetch import FetchError, check_address

ARTICLE = """<html><head><title>How refunds work | Shop</title></head><body>
<div class="cookie-banner">We use cookies. <a href="/privacy">Accept</a></div>
<header><nav><a href="/">Home</a> <a href="/shop">Shop</a> <a href="/blog">Blog</a></nav></header>
<main>
  <h1>How refunds work</h1>
  <p>You can ask for a refund within <strong>30 days</strong> of delivery. Read the
  <a href="https://shop.example.com/terms?utm_source=newsletter&amp;utm_medium=email">full terms</a> or
  <a href="https://other.example.org/guide?id=7&amp;utm_campaign=x">this outside guide</a>.</p>
  <img src="/img/hero.jpg" alt="A happy customer">
  <h2>Shipping costs</h2>
  <p>Return shipping is free for orders over R500. Below that, a flat fee of R60 applies to every return.</p>
  <h2>Store credit</h2>
  <p>Store credit never expires and can be used on any product in the shop, including sale items.</p>
  <div class="share-buttons"><a href="https://twitter.com/share">Tweet</a></div>
</main>
<footer>© 2026 Shop · <a href="/careers">Careers</a></footer>
</body></html>"""

SHELL = """<html><head><title>App</title><script src="/a.js"></script><script src="/b.js"></script>
<script src="/c.js"></script></head><body><div id="root"></div></body></html>"""


def md_of(html=ARTICLE, **kw):
    return html_to_markdown(html, "https://shop.example.com/help/refunds", **kw)


def test_main_content_without_furniture():
    md = md_of()
    assert "# How refunds work" in md and "30 days" in md and "Store credit never expires" in md
    for furniture in ("We use cookies", "Careers", "Tweet", "[Home]", "© 2026"):
        assert furniture not in md


def test_links_are_lean():
    md = md_of()
    assert "[full terms](/terms)" in md  # same site: path only, tracking parameters gone
    assert "[this outside guide](https://other.example.org/guide?id=7)" in md  # other sites stay absolute
    assert "utm_" not in md
    assert "hero.jpg" not in md  # image embeds dropped by default


def test_link_and_image_options():
    assert "](" not in md_of(links=False) and "full terms" in md_of(links=False)
    assert "](https://shop.example.com/img/hero.jpg)" in md_of(images=True)
    assert "[full terms](https://shop.example.com/terms)" in md_of(short_links=False)


def test_card_links_keep_spaces_between_their_parts():
    card = ('<main><h1>News</h1>' + '<p>Front page of today with stories from around the world and more.</p>' * 3 +
            '<a href="/news/1"><div><span>LIVE</span><h2>Election called</h2><p>The vote is in May.</p>'
            '<span>2 hrs ago</span><span>Politics</span></div></a></main>')
    md = html_to_markdown(card, "https://news.example.com/")
    assert "LIVE Election called The vote is in May. 2 hrs ago Politics" in md


def test_repeated_blocks_are_dropped_but_code_is_kept():
    side = "<div class='side'><h2>Project links</h2><p>Homepage, documentation and source code for this project.</p></div>"
    code = "<pre><code>def f():\n    return 1\n\n\ndef f():\n    return 1</code></pre>"
    md = html_to_markdown(f"<main><h1>Pkg</h1><p>{'About this package and what it does. ' * 10}</p>{side}{code}{side}</main>")
    assert md.count("Homepage, documentation and source code") == 1
    assert md.count("    return 1") == 2  # code indentation and repeats untouched


def test_full_page_mode_keeps_navigation():
    assert "Careers" in md_of(main_content=False)


def test_classify():
    assert classify(200, ARTICLE).outcome == "ok"
    assert classify(200, SHELL).outcome == "needs_browser"
    assert classify(404, "<html>gone</html>").outcome == "not_found"
    wall = "<html><head><title>Just a moment...</title></head><body>cf-chl- checking your browser</body></html>"
    assert classify(403, wall) .outcome == "blocked"
    assert classify(200, "<p>hi</p>", {"cf-mitigated": "challenge"}).outcome == "blocked"


def test_focus_returns_the_section_asked_for():
    md = md_of()
    out, kept, total = focus(md, "shipping fee for returns")
    assert "R60" in out and kept < total


def test_focus_ignores_comments_in_code():
    md = "# Guide\n\nIntro text here for the guide.\n\n## Install\n\nRun this:\n\n```\n# not a heading\npip install x\n```\n\n## Use\n\nCall the thing with care and patience.\n\n## Other\n\nMore words about other stuff here."
    out, kept, total = focus(md, "install")
    assert total == 4 and "pip install x" in out


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://10.0.0.5/x", "http://169.254.169.254/latest/meta-data/",
                                 "http://[::1]/", "file:///etc/passwd"])
def test_private_and_odd_addresses_are_refused(url):
    with pytest.raises(FetchError):
        check_address(url)


def test_private_addresses_can_be_allowed():
    check_address("http://127.0.0.1/", allow_private=True)


def transport(routes):
    def handle(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response(request) if callable(response) else response
        return httpx.Response(404, text="no route")
    return httpx.MockTransport(handle)


def test_slim_reads_a_page():
    t = transport({"https://shop.example.com/": httpx.Response(200, html=ARTICLE)})
    r = slim("https://shop.example.com/help/refunds", transport=t, allow_private=True, skryp_api_key="")
    assert r.ok and r.title == "How refunds work | Shop" and r.tokens > 20 and "R60" in r.markdown


def test_slim_follows_redirects_and_focuses():
    t = transport({"https://shop.example.com/old": httpx.Response(301, headers={"location": "/help/refunds"}),
                   "https://shop.example.com/help/refunds": httpx.Response(200, html=ARTICLE)})
    r = slim("https://shop.example.com/old", focus="store credit", transport=t, allow_private=True, skryp_api_key="")
    assert r.final_url == "https://shop.example.com/help/refunds" and "never expires" in r.markdown
    assert r.sections_kept and r.sections_kept < r.sections_total


def test_slim_says_what_an_app_shell_needs():
    t = transport({"https://app.example.com/": httpx.Response(200, html=SHELL)})
    r = slim("https://app.example.com/", transport=t, allow_private=True, skryp_api_key="")
    assert r.status == "needs_browser" and "SKRYP_API_KEY" in r.note and not r.markdown


def test_slim_hands_hard_pages_to_skryp():
    seen = {}

    def skryp(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok", "markdown": "# Rendered\n\nBuilt by JavaScript, read by Skryp.",
                                         "metadata": {"title": "App", "url": "https://app.example.com/"},
                                         "receipt": {"route": "browser:direct", "credits": 1}})
    t = transport({"https://app.example.com/": httpx.Response(200, html=SHELL), "https://api.skryp.dev/v1/scrape": skryp})
    r = slim("https://app.example.com/", transport=t, allow_private=True, skryp_api_key="sk_test", focus="pricing")
    assert r.ok and r.source == "skryp" and "read by Skryp" in r.markdown and "browser:direct" in r.note
    assert seen["auth"] == "Bearer sk_test" and seen["body"]["focus"] == "pricing"


def test_country_needs_skryp():
    r = slim("https://shop.example.com/", country="de", skryp_api_key="")
    assert r.status == "unsupported" and "DE" in r.note


def test_json_and_text_responses():
    t = transport({"https://api.example.com/x.json": httpx.Response(200, json={"a": 1}),
                   "https://api.example.com/x.txt": httpx.Response(200, text="plain words", headers={"content-type": "text/plain"})})
    assert slim("https://api.example.com/x.json", transport=t, allow_private=True).markdown.startswith("```json")
    assert slim("https://api.example.com/x.txt", transport=t, allow_private=True).markdown == "plain words"


def test_cli_on_a_file(tmp_path):
    f = tmp_path / "page.html"
    f.write_text(ARTICLE)
    out = subprocess.run([sys.executable, "-m", "slimdown.cli", str(f), "--url", "https://shop.example.com/help/refunds",
                          "--json"], capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r["status"] == "ok" and "[full terms](/terms)" in r["markdown"] and r["tokens"] > 0


def test_mcp_server_has_read_page():
    from slimdown import mcp_server
    assert callable(mcp_server.read_page) and callable(mcp_server.main)


def test_code_blocks_keep_only_text():
    html = ('<main><h1>Run</h1><p>' + 'Start the server with this command. ' * 10 +
            '</p><pre><code><font color="#4E9A06">uv run fastapi</font> <span style="color:red">dev</span></code></pre></main>')
    md = html_to_markdown(html)
    assert "uv run fastapi dev" in md and "<font" not in md


def test_terminal_demos_lose_the_colour_tags_written_into_their_text():
    html = ('<main><h1>Run</h1><p>' + 'Start the server with this command. ' * 10 + '</p><div class="termy"><pre><code>'
            '$ &lt;font color=&quot;#4E9A06&quot;&gt;uv run fastapi&lt;/font&gt; dev</code></pre></div>'
            '<pre><code>&lt;span class="x"&gt;HTML a tutorial shows&lt;/span&gt;</code></pre></main>')
    md = html_to_markdown(html)
    assert "$ uv run fastapi dev" in md and '<span class="x">HTML a tutorial shows</span>' in md


def test_plan_matrix_icons_dashes_and_cells():
    intro = "<h1>Pricing</h1><p>" + "Compare what each plan includes for your team and your agents. " * 8 + "</p>"
    cell = '<div class="row"><span>{}</span></div>'
    html = (f"<main>{intro}<div><strong>Hobby</strong>" + cell.format('<i class="icon-tick02"></i>') +
            cell.format('<svg aria-label="Not included"><path d="M0"/></svg>') + cell.format("-") + "</div>"
            '<a href="/x"><i class="icon-check"></i></a><div><span class="absolute inset-x-0"></span></div>'
            '<table><tr><th><span>Standard request</span><span class="block">Our own network</span></th><td>1</td></tr></table></main>')
    md = html_to_markdown(html)
    assert md.count("✓") == 1 and md.count("✗") == 1 and "—" in md
    assert "Standard request Our own network" in md
