def append_item(item, collection=[]):
    """Add item to collection and return the updated list.

    Each call with no explicit collection should start from an empty list.

    Example:
        >>> append_item("a")
        ['a']
        >>> append_item("b")
        ['b']   # <-- should be ['b'], not ['a', 'b']
    """
    # Bug: mutable default argument is shared across all calls
    collection.append(item)
    return collection
