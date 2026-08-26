import time

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get_with_retry(
    url: str, *, params=None, timeout: int = 60, max_retries: int = 5, initial_delay: float = 5.0
) -> requests.Response:
    """GET with exponential backoff, honoring Retry-After on rate limits.

    The backoff ladder must outlast source-side cooldown windows: energy-charts
    returns 429 for roughly a minute once its per-minute quota trips, so a
    2/4/8s ladder exhausts before the quota resets (INC-007).
    """
    delay = initial_delay
    last_error = None
    for attempt in range(max_retries):
        retry_after = None
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code in RETRYABLE_STATUS:
                retry_after = resp.headers.get("Retry-After")
                raise requests.HTTPError(f"HTTP {resp.status_code} from {url}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as error:
            last_error = error
            if attempt < max_retries - 1:
                time.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
    raise last_error
