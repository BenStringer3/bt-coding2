def clamp(value, lo, hi):
    """Return value clamped to the inclusive range [lo, hi]."""
    if value > hi:
        return hi
    if value < lo:
        return lo
    return value


def is_valid_age(age):
    """Return True if age is in the valid range 0-120 inclusive."""
    # Bug: should be >= 0, not > 0 — age of 0 is rejected incorrectly
    if age > 0 and age <= 120:
        return True
    return False
