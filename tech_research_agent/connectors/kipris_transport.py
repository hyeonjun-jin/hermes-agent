"""Attach the service key below HTTPX's URL logging layer, without global log filters."""
import httpx


class CredentialTransport(httpx.BaseTransport):
    def __init__(self, api_key, transport=None):
        self._key = api_key
        self._transport = transport or httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        authenticated = httpx.Request(request.method, request.url.copy_add_param('ServiceKey', self._key),
                                      headers=request.headers, stream=request.stream, extensions=request.extensions)
        return self._transport.handle_request(authenticated)

    def close(self):
        self._transport.close()
