from __future__ import annotations

from math import ceil
from .config import RuleConfig


def estimate_parts(page_count: int, size_bytes: int, rule: RuleConfig) -> int:
    rule = rule.normalized()
    by_pages = max(1, ceil(page_count / rule.max_pages))
    by_size = max(1, ceil(size_bytes / rule.max_size_bytes))
    if rule.strategy == "page_first":
        return by_pages
    if rule.strategy == "size_first":
        return max(by_size, 1)
    return max(by_pages, by_size)


def chunk_ranges_by_pages(page_count: int, pages_per_chunk: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= page_count:
        end = min(page_count, start + pages_per_chunk - 1)
        ranges.append((start, end))
        start = end + 1
    return ranges


def initial_pages_per_part(page_count: int, size_bytes: int, rule: RuleConfig) -> int:
    rule = rule.normalized()
    if rule.strategy == "page_first":
        return min(rule.max_pages, page_count)
    if rule.strategy == "size_first":
        avg = max(1, size_bytes / max(1, page_count))
        by_size = max(1, int(rule.max_size_bytes / avg))
        return max(1, min(rule.max_pages, by_size, page_count))
    # both: choose conservative page count using both page and size estimate
    avg = max(1, size_bytes / max(1, page_count))
    by_size = max(1, int(rule.max_size_bytes / avg))
    return max(1, min(rule.max_pages, by_size, page_count))
