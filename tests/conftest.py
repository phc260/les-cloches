"""Suite-wide test-level validation."""

from __future__ import annotations

import pytest


LEVEL_MARKERS = ("easy", "medium", "hard")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Require every test to belong to exactly one execution-scope level."""
    invalid = []
    for item in items:
        levels = [level for level in LEVEL_MARKERS if item.get_closest_marker(level)]
        if len(levels) != 1:
            found = ", ".join(levels) if levels else "none"
            invalid.append(f"{item.nodeid} ({found})")

    if invalid:
        details = "\n".join(f"- {entry}" for entry in invalid)
        raise pytest.UsageError(
            "each test must have exactly one easy, medium, or hard marker:\n"
            f"{details}"
        )
