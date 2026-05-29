"""Synchronous ASGI test client that avoids Starlette TestClient portal hangs."""

from __future__ import annotations

from typing import Any

import anyio
import httpx


class SyncASGITestClient:
    """Small subset of TestClient used by this test suite.

    Starlette's TestClient can hang in this local Python/anyio/httpx stack while
    waiting on its blocking portal.  This wrapper drives the ASGI app through
    httpx.ASGITransport per request and intentionally does not run lifespan.
    """

    __test__ = False

    def __init__(
        self,
        app: Any,
        *,
        base_url: str = "http://testserver",
        cookies: dict[str, str] | httpx.Cookies | None = None,
        headers: dict[str, str] | None = None,
        raise_server_exceptions: bool = True,
        follow_redirects: bool = True,
        **_: Any,
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.cookies = httpx.Cookies(cookies)
        self.headers = httpx.Headers(headers)
        self.raise_server_exceptions = raise_server_exceptions
        self.follow_redirects = follow_redirects

    def __enter__(self) -> "SyncASGITestClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(
                app=self.app,
                raise_app_exceptions=self.raise_server_exceptions,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                cookies=self.cookies,
                headers=self.headers,
                follow_redirects=self.follow_redirects,
            ) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies.update(client.cookies)
                return response

        return anyio.run(_request)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)
