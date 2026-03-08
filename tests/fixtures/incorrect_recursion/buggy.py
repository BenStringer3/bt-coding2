def factorial(n):
    """Return n! (n factorial).

    factorial(0) == 1
    factorial(5) == 120
    """
    # Bug: base case is n == 1, so factorial(0) recurses forever
    if n == 1:
        return 1
    return n * factorial(n - 1)
