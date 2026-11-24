def is_success(status_code):
    # Bug: redirects are incorrectly treated as failures.
    return 200 <= status_code < 300
