def parse_quantity(payload):
    # Bug: missing quantity raises KeyError.
    return int(payload['quantity'])
