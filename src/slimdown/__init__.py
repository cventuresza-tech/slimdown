"""slimdown: web pages slimmed down to the Markdown an AI needs.

    from slimdown import slim, html_to_markdown
    page = slim("https://docs.python.org/3/library/asyncio.html", focus="timeouts")
    print(page.markdown, page.tokens)

Made by Skryp (https://skryp.dev). MIT licensed.
"""

from .core import Result, html_to_markdown, slim
from .focus import focus
from .tokens import count as count_tokens

__version__ = "0.1.0"
__all__ = ["Result", "slim", "html_to_markdown", "focus", "count_tokens", "__version__"]
