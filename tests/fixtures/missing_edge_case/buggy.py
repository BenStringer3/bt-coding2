def average(numbers):
    """Return the arithmetic mean of a list of numbers.

    Raises ZeroDivisionError if numbers is empty.
    Should return 0.0 for an empty list instead.
    """
    # Bug: no guard for empty list
    return sum(numbers) / len(numbers)


def median(numbers):
    """Return the median of a sorted list."""
    if not numbers:
        return None
    mid = len(numbers) // 2
    if len(numbers) % 2 == 0:
        return (numbers[mid - 1] + numbers[mid]) / 2
    return numbers[mid]
