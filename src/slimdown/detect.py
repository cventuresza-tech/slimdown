"""What a fetched response means: usable, blocked by a bot wall, missing, or an app that needs a browser to render."""

from __future__ import annotations

import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser

# Signatures of bot walls and challenge pages, matched against a lower-cased slice of the body.
_BLOCK_MARKERS = [
    ("cloudflare", ("cf-chl-", "challenge-platform", "<title>just a moment", "attention required! | cloudflare",
                    "cf-browser-verification", "cf_chl_opt")),
    ("akamai", ("errors.edgesuite.net", "<title>access denied</title>", "reference&#32;&#35;")),
    ("datadome", ("captcha-delivery.com", "geo.captcha-delivery", "datadome")),
    ("perimeterx", ("px-captcha", "_pxhd", "press &amp; hold", "press & hold", "perimeterx")),
    ("imperva", ("incapsula incident", "_incapsula_resource", "pardon our interruption")),
    ("kasada", ("kpsdk",)),
    ("aws-waf", ("awswaf", "aws-waf-token")),
    ("captcha", ("g-recaptcha", "h-captcha", "hcaptcha.com", "cf-turnstile", "are you a robot",
                 "unusual traffic from your computer", "verify you are human", "i am not a robot")),
]
_JS_MARKERS = ("enable javascript", "javascript is required", "requires javascript", "you need to enable javascript",
               "please turn on javascript", "javascript is disabled")
_ROOT_IDS = re.compile(r'<div[^>]+id=["\'](root|app|__next|__nuxt|svelte|main-app|react-root)["\'][^>]*>\s*</div>', re.I)


@dataclass
class Verdict:
    outcome: str  # ok | blocked | not_found | needs_browser | error | empty
    reason: str | None = None
    text_len: int = 0


def visible_text_length(html: str) -> int:
    try:
        tree = LexborHTMLParser(html)
    except Exception:
        return len(html)
    for sel in ("script", "style", "noscript", "template", "svg", "head"):
        for n in tree.css(sel):
            n.decompose()
    body = tree.body
    txt = body.text(separator=" ", strip=True) if body else ""
    return len(re.sub(r"\s+", " ", txt))


def classify(status: int | None, html: str, headers: dict[str, str] | None = None) -> Verdict:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    head = html[:60000].lower()
    text_len = visible_text_length(html) if html else 0

    if status in (404, 410):
        return Verdict("not_found", f"HTTP {status}", text_len)
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return Verdict("blocked", "Cloudflare challenge", text_len)
    for vendor, markers in _BLOCK_MARKERS:
        if any(m in head for m in markers):
            # a normal page can carry a captcha on a form: only a thin page or a refusing status is a wall
            if status in (401, 403, 429, 503) or text_len < 1500:
                return Verdict("blocked", vendor, text_len)
    if status == 429:
        return Verdict("blocked", "rate limited (HTTP 429)", text_len)
    if status in (401, 402, 403, 407, 451):
        return Verdict("blocked", f"HTTP {status}", text_len)
    if status is not None and status >= 400:
        return Verdict("error", f"HTTP {status}", text_len)
    if not html.strip():
        return Verdict("empty", "empty body", 0)
    script_count = head.count("<script")
    if text_len < 250 and (script_count >= 3 or _ROOT_IDS.search(html[:200000] or "")):
        return Verdict("needs_browser", "an app shell with little text: the page is built by JavaScript", text_len)
    if text_len < 600 and any(m in head for m in _JS_MARKERS):
        return Verdict("needs_browser", "the page asks for JavaScript", text_len)
    if _ROOT_IDS.search(html[:200000]) and text_len < 800:
        return Verdict("needs_browser", "an empty app root: the page is built by JavaScript", text_len)
    if text_len < 40:
        return Verdict("needs_browser", "almost no text in the HTML", text_len)
    return Verdict("ok", None, text_len)
