import time


def fetch_with_retry(fetch, retries=3, delay=0.01, sleep=time.sleep):
    last_error = None
    for attempt in range(retries):
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries:
                raise
            sleep(delay)
            delay *= 2
    return None
