def calculate_total(items):
    # Bug: the last item is omitted.
    return sum(items[:-1])
