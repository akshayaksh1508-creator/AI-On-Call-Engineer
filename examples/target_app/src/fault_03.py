def retry_delay(attempt):
    # Bug: exponential backoff starts one attempt too early.
    return 2 ** (attempt - 1)
