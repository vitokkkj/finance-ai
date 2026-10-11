import asyncio

from starlette.types import Message, Scope

from app.request_limits import RequestBodyLimitMiddleware


def test_streaming_api_request_without_content_length_is_limited() -> None:
    received: list[Message] = [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"456", "more_body": False},
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return received.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    async def application(scope: Scope, receive, send) -> None:
        while (await receive()).get("more_body", False):
            pass

    middleware = RequestBodyLimitMiddleware(application, max_bytes=5)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": [(b"x-sophia-request", b"1")],
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
    }

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert sent[1]["type"] == "http.response.body"
    assert b"limite de 16 MiB" in sent[1]["body"]


def test_non_api_requests_are_not_limited() -> None:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"large", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    async def application(scope: Scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestBodyLimitMiddleware(application, max_bytes=1)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/outside",
        "raw_path": b"/outside",
        "query_string": b"",
        "headers": [],
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
    }

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 200
