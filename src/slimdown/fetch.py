"""Fetch one page over plain HTTP, the way a browser asks for it, without running its JavaScript.

Addresses that resolve to private, loopback or link-local networks are refused unless allow_private=True, at every
redirect: an agent reading pages on someone's behalf can be talked into asking for http://169.254.169.254/ or a router.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT,
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
MAX_BYTES = 10_000_000
MAX_REDIRECTS = 10


class FetchError(Exception):
    pass


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False


def check_address(url: str, allow_private: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"only http and https addresses can be read, not {parts.scheme or 'this'}: {url}")
    host = parts.hostname
    if not host:
        raise FetchError(f"no host in {url}")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise FetchError(f"{host} does not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise FetchError(f"{host} points to a private address ({ip}); pass allow_private=True to read it")


def _decode(content: bytes, content_type: str) -> str:
    m = re.search(r"charset=[\"']?([\w.:-]+)", content_type or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        head = content[:4096].decode("ascii", "ignore")
        m2 = re.search(r"<meta[^>]+charset=[\"']?([\w.:-]+)", head, re.I)
        enc = m2.group(1) if m2 else "utf-8"
    try:
        return content.decode(enc, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def fetch(url: str, *, timeout: float = 20.0, allow_private: bool = False, headers: dict[str, str] | None = None,
          transport: httpx.BaseTransport | None = None) -> Fetched:
    """GET a page, following redirects (each one checked), reading at most MAX_BYTES."""
    hdrs = {**HEADERS, **(headers or {})}
    current = url
    with httpx.Client(headers=hdrs, timeout=timeout, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_address(current, allow_private)
            try:
                with client.stream("GET", current) as r:
                    if r.is_redirect and r.headers.get("location"):
                        current = urljoin(current, r.headers["location"])
                        continue
                    chunks, size, truncated = [], 0, False
                    for chunk in r.iter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= MAX_BYTES:
                            truncated = True
                            break
                    body = b"".join(chunks)[:MAX_BYTES]
                    ctype = r.headers.get("content-type", "")
                    return Fetched(url=url, final_url=str(r.url), status=r.status_code, content_type=ctype,
                                   text=_decode(body, ctype), headers=dict(r.headers), truncated=truncated)
            except httpx.HTTPError as e:
                raise FetchError(f"could not fetch {current}: {type(e).__name__}: {e}") from e
    raise FetchError(f"more than {MAX_REDIRECTS} redirects from {url}")
