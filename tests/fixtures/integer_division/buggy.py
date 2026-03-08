def split_bill(total_cents, num_people):
    """Return the amount each person owes, in cents, as a float.

    The result should be a float so fractional cents are preserved for
    rounding decisions by the caller.

    Example:
        >>> split_bill(100, 3)
        33.333...
    """
    # Bug: floor division (//) discards the fractional part; should be /
    return total_cents // num_people


def percentage(part, whole):
    """Return what percentage part is of whole (0-100 scale).

    Example:
        >>> percentage(1, 3)
        33.333...
    """
    # Bug: same floor division issue
    return (part // whole) * 100
