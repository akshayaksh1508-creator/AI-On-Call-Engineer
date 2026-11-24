def normalize_status(status):
    # Bug: status is not normalized before comparison.
    if status == 'paid':
        return 'complete'
    return 'pending'
