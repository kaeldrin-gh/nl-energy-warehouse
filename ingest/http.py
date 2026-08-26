import time

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get_with_retry(
    url: str, *, params=None, timeout: int = 60, max_retries: int = 4, initial_delay: float = 2.0
) -> requests.Response:
    delay = initial_delay
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code in RETRYABLE_STATUS:
                raise requests.HTTPError(f"HTTP {resp.status_code} from {url}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as error:
            last_error = error
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
    raise last_error
