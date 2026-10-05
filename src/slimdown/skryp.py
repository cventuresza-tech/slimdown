"""The pages slimdown cannot read by itself, read through Skryp (https://skryp.dev): pages built by JavaScript, pages
behind bot walls, and pages as seen from another country. Used only when SKRYP_API_KEY is set (or a key is passed).
Skryp returns the same lean Markdown, made by the same engine."""

from __future__ import annotations

import httpx

API = "https://api.skryp.dev/v1/scrape"
SIGNUP = "https://skryp.dev"


def scrape(url: str, key: str, *, focus: str | None = None, country: str | None = None, images: bool = False,
           main_content: bool = True, timeout: float = 120.0, transport: httpx.BaseTransport | None = None) -> dict:
    body: dict = {"url": url, "formats": ["markdown", "metadata"], "main_content": main_content,
                  "images_in_markdown": images}
    if focus:
        body["focus"] = focus
    if country:
        body["country"] = country
    with httpx.Client(timeout=timeout, transport=transport) as client:
        r = client.post(API, json=body, headers={"Authorization": f"Bearer {key}", "User-Agent": "slimdown"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 401:
        return {"status": "error", "error": "Skryp refused the API key (HTTP 401): check SKRYP_API_KEY"}
    if r.status_code == 402:
        return {"status": "error", "error": data.get("detail") or "Skryp: no credits left (HTTP 402)"}
    if r.status_code >= 400:
        return {"status": "error", "error": data.get("detail") or f"Skryp answered HTTP {r.status_code}"}
    return data
