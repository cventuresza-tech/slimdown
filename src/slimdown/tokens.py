"""Token counts with OpenAI's o200k_base encoding when tiktoken is installed (pip install "slimdown[tokens]"), else an
estimate of one token per four characters."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _enc():
    try:
        import tiktoken
        return tiktoken.get_encoding("o200k_base")
    except Exception:
        return None


def count(text: str | None) -> int:
    if not text:
        return 0
    enc = _enc()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))


def exact() -> bool:
    """True when counts come from tiktoken rather than the estimate."""
    return _enc() is not None
