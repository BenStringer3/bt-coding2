def top_scores(scores, n=3):
    """Return the top-n scores in descending order (highest first).

    Example:
        >>> top_scores([40, 10, 90, 55, 70], 3)
        [90, 70, 55]
    """
    # Bug: sorted ascending, should be descending (reverse=True)
    return sorted(scores)[:n]
