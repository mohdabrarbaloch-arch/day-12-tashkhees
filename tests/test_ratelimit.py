"""Tests for the sliding-window rate limiter."""

from __future__ import annotations

from app.ratelimit import Limit, RateLimiter


def test_limit_parses_minute():
    lim = Limit.parse("10/minute")
    assert lim.count == 10
    assert lim.window_seconds == 60.0


def test_limit_parses_second_and_hour():
    assert Limit.parse("5/second").window_seconds == 1.0
    assert Limit.parse("100/hour").window_seconds == 3600.0


def test_limit_parse_falls_back_on_garbage():
    lim = Limit.parse("not-a-limit")
    assert lim.count == 60
    assert lim.window_seconds == 60.0


def test_limiter_allows_up_to_the_limit():
    rl = RateLimiter()
    lim = Limit(count=3, window_seconds=60)
    for i in range(3):
        allowed, _ = rl.check("k", lim, now=100.0 + i)
        assert allowed, f"request {i} should be allowed"


def test_limiter_blocks_the_next_request():
    rl = RateLimiter()
    lim = Limit(count=2, window_seconds=60)
    rl.check("k", lim, now=100.0)
    rl.check("k", lim, now=101.0)
    allowed, retry = rl.check("k", lim, now=102.0)
    assert not allowed
    assert retry > 0.0


def test_limiter_window_slides():
    rl = RateLimiter()
    lim = Limit(count=2, window_seconds=10)
    rl.check("k", lim, now=100.0)
    rl.check("k", lim, now=101.0)
    # 11 seconds later the first two have aged out.
    allowed, _ = rl.check("k", lim, now=111.5)
    assert allowed


def test_limiter_keys_are_independent():
    rl = RateLimiter()
    lim = Limit(count=1, window_seconds=60)
    assert rl.check("a", lim, now=1.0)[0]
    assert rl.check("b", lim, now=1.0)[0]
    assert not rl.check("a", lim, now=1.0)[0]


def test_limiter_reset_clears_state():
    rl = RateLimiter()
    lim = Limit(count=1, window_seconds=60)
    rl.check("k", lim, now=1.0)
    rl.reset("k")
    assert rl.check("k", lim, now=1.0)[0]


def test_limiter_reset_all():
    rl = RateLimiter()
    lim = Limit(count=1, window_seconds=60)
    rl.check("a", lim, now=1.0)
    rl.check("b", lim, now=1.0)
    rl.reset()
    assert rl.check("a", lim, now=1.0)[0]
    assert rl.check("b", lim, now=1.0)[0]
