from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_WRITE_BLOCKED_DETAIL = "Solicitação bloqueada. Atualize a página e tente novamente."
REQUEST_BODY_TOO_LARGE_DETAIL = "O corpo da solicitação excede o limite de 16 MiB."


class RequestBodyLimitMiddleware:
    """Limita corpos de endpoints da API, inclusive streams sem Content-Length."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_api_request = path.startswith("/api/")
        if (
            is_api_request
            and scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}
            and dict(scope.get("headers", [])).get(b"x-sophia-request") != b"1"
        ):
            await self._send_json(send, 403, API_WRITE_BLOCKED_DETAIL)
            return

        async def secured_send(message: Message) -> None:
            if is_api_request and message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in {b"cache-control", b"pragma"}
                ]
                headers.extend(((b"cache-control", b"no-store"), (b"pragma", b"no-cache")))
                message = {**message, "headers": headers}
            await send(message)

        if not is_api_request:
            await self.app(scope, receive, secured_send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                declared_length = -1
            if declared_length > self.max_bytes:
                await self._send_json(secured_send, 413, REQUEST_BODY_TOO_LARGE_DETAIL)
                return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, secured_send)
        except _RequestBodyTooLarge:
            await self._send_json(secured_send, 413, REQUEST_BODY_TOO_LARGE_DETAIL)

    @staticmethod
    async def _send_json(send: Send, status_code: int, detail: str) -> None:
        body = json.dumps(
            {"detail": detail},
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _RequestBodyTooLarge(Exception):
    pass
