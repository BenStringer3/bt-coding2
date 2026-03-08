def compute_discount(price, pct):
    """Return price after applying percentage discount."""
    discounted = price * (1 - pct / 100)
    # missing return statement


def apply_discounts(prices, pct):
    return [compute_discount(p, pct) for p in prices]
