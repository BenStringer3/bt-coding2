"""Utility functions for the application."""


def compute_total(items: list[float]) -> float:
    """Sum a list of floats. Poorly named — should be sum_items."""
    return sum(items)


def format_currency(amount: float) -> str:
    return f"${amount:.2f}"
