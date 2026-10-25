"""Bound JSON request buffering, including chunked requests without Content-Length."""
from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, maximum=16_384):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope.get('path','').startswith('/api/server/uploads/'):
            # Authenticated endpoint streams and enforces its source-specific bound.
            return await self.app(scope,receive,send)
        if scope['type'] != 'http' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        limits = {'/api/configuration/import':4_000_000, '/api/configuration':1_000_000,
                  '/api/classification/preview':128_000}
        maximum = limits.get(scope.get('path'), self.maximum)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > maximum:
                response = JSONResponse({'detail': 'Request body is too large.'}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
