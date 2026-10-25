"""Decision 8: at most `limit` requests per token per minute, kept in memory.

A sliding window: each token keeps the times of its allowed requests from the last
`window_s` seconds. In memory is enough for one container. With several, each would count
on its own (three containers allow 3 × the limit), and the counts would need a shared
store such as Redis.

Count only requests that already passed the token check. Counting before it would let
anyone fill memory with made-up tokens.
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit, window_s=60, clock=time.monotonic):
        if limit < 1:
            raise ValueError("the rate limit must be at least 1 request")
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._times = defaultdict(deque)
        self._lock = threading.Lock()  # the API serves requests from several threads

    def take(self, key):
        """Count one request for `key`. Returns 0 if it's allowed, else the seconds until it
        would be (for the 429's Retry-After header); a refused request isn't counted."""
        with self._lock:
            now = self.clock()
            times = self._times[key]
            while times and times[0] <= now - self.window_s:
                times.popleft()
            if len(times) < self.limit:
                times.append(now)
                return 0
            return times[0] + self.window_s - now
