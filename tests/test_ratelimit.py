"""RateLimiter: a sliding one-minute window per token. A fake clock, so nothing sleeps."""

import threading

import pytest

from posting_triage.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_requests_up_to_the_limit_are_allowed_then_refused():
    limiter = RateLimiter(3, clock=Clock())
    assert [limiter.take("t") for _ in range(3)] == [0, 0, 0]
    assert limiter.take("t") == 60


def test_retry_after_counts_down_to_the_oldest_request_leaving_the_window():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock)
    limiter.take("t")
    clock.now += 20
    limiter.take("t")
    clock.now += 15
    assert limiter.take("t") == 25  # the first request leaves the window at 60 s
    clock.now += 25
    assert limiter.take("t") == 0


def test_the_window_slides_instead_of_resetting_on_the_minute():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock)
    limiter.take("t")
    clock.now += 59
    limiter.take("t")
    clock.now += 1  # only the first request has left
    assert limiter.take("t") == 0
    assert limiter.take("t") == 59


def test_a_refused_request_does_not_use_up_a_slot():
    clock = Clock()
    limiter = RateLimiter(1, clock=clock)
    limiter.take("t")
    for _ in range(5):
        clock.now += 10
        limiter.take("t")  # refused, so it mustn't push the window later
    clock.now += 10
    assert limiter.take("t") == 0


def test_tokens_are_counted_separately():
    limiter = RateLimiter(1, clock=Clock())
    assert limiter.take("a") == 0
    assert limiter.take("b") == 0
    assert limiter.take("a") > 0


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_concurrent_requests_never_exceed_the_limit():
    limiter = RateLimiter(10, clock=Clock())
    allowed = []

    def burst():
        for _ in range(20):
            if limiter.take("t") == 0:
                allowed.append(1)

    threads = [threading.Thread(target=burst) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 10
