"""Bound request bytes before the framework parses JSON, including chunked bodies."""

from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, maximum=65_536):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]
        invalid = len(lengths) > 1 or (
            lengths and (not lengths[0].isdigit() or len(lengths[0]) > 20)
        )
        if invalid:
            return await JSONResponse({"detail": "Invalid request length."}, status_code=400)(
                scope, receive, send
            )
        if lengths and int(lengths[0]) > self.maximum:
            return await JSONResponse({"detail": "Request is too large."}, status_code=413)(
                scope, receive, send
            )
        chunks, size = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body = event.get("body", b"")
            size += len(body)
            if size > self.maximum:
                return await JSONResponse({"detail": "Request is too large."}, status_code=413)(
                    scope, receive, send
                )
            if body:
                chunks.append(body)
            if not event.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
