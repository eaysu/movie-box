import unittest

from starlette.requests import Request

from app.main import _client_ip
from app.rate_limit import SlidingWindowRateLimiter


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_and_long_window_are_both_enforced(self):
        now = [0.0]
        limiter = SlidingWindowRateLimiter(
            limit=5,
            window_seconds=600,
            burst=2,
            burst_seconds=15,
            clock=lambda: now[0],
        )

        self.assertEqual(await limiter.check("ip"), (True, 0))
        self.assertEqual(await limiter.check("ip"), (True, 0))
        allowed, retry = await limiter.check("ip")
        self.assertFalse(allowed)
        self.assertEqual(retry, 15)

        for timestamp in (16.0, 32.0, 48.0):
            now[0] = timestamp
            self.assertEqual(await limiter.check("ip"), (True, 0))

        now[0] = 64.0
        allowed, retry = await limiter.check("ip")
        self.assertFalse(allowed)
        self.assertEqual(retry, 536)

    async def test_clients_have_independent_buckets(self):
        limiter = SlidingWindowRateLimiter(
            limit=1,
            window_seconds=60,
            burst=1,
            burst_seconds=10,
        )
        self.assertEqual(await limiter.check("first"), (True, 0))
        self.assertEqual(await limiter.check("second"), (True, 0))
        self.assertFalse((await limiter.check("first"))[0])


class ClientIpTests(unittest.TestCase):
    @staticmethod
    def _request(headers):
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/api/recommend",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
            "client": ("10.0.0.5", 1234),
        })

    def test_cloudflare_address_has_priority(self):
        request = self._request({
            "CF-Connecting-IP": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.2, 203.0.113.9",
        })
        self.assertEqual(_client_ip(request), "203.0.113.9")

    def test_forwarded_fallback_ignores_spoofable_left_side(self):
        request = self._request({
            "X-Forwarded-For": "1.2.3.4, 198.51.100.8",
        })
        self.assertEqual(_client_ip(request), "198.51.100.8")


if __name__ == "__main__":
    unittest.main()
