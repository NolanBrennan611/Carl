"""Page arithmetic shared by list views."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageWindow:
    page: int  # 1-based, clamped into range
    pages: int  # at least 1
    start: int  # slice start (inclusive)
    end: int  # slice end (exclusive)


def paginate(total: int, page: int, size: int) -> PageWindow:
    """Clamp `page` into range and return the slice bounds. An empty list is one empty page."""
    if size < 1:
        raise ValueError("size must be >= 1")
    pages = max(1, -(-total // size))
    page = min(max(page, 1), pages)
    start = (page - 1) * size
    return PageWindow(page=page, pages=pages, start=start, end=min(start + size, total))
