"""Main application entry point."""

from utils import compute_total, format_currency


def run(prices: list[float]) -> str:
    total = compute_total(prices)
    return format_currency(total)


if __name__ == "__main__":
    result = run([10.0, 20.5, 5.75])
    print(result)
