def total_price(cart):
    """Return the total price of all items in cart.

    cart is a list of dicts with keys 'name', 'price', and 'qty'.

    Example:
        >>> total_price([{'name': 'apple', 'price': 1.5, 'qty': 4}])
        6.0
    """
    total = 0.0
    for item in cart:
        # Bug: accumulates item['qty'] instead of item['price'] * item['qty']
        total += item["qty"]
    return total
