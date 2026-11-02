"""Browser automation for prefilling application forms (never submits)."""

from functools import cache
from importlib import resources


@cache
def js(name: str) -> str:
    """Load a page-side script from this package, without its `//` comment lines."""
    source = resources.files(__name__).joinpath(name).read_text("utf-8")
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
