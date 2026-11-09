import json
import os
import re
from urllib.parse import urlencode

from . import __version__
from .exceptions import ServerError

try:
    import requests
except ImportError:
    requests = None

__all__ = ["HTTPSession"]

USER_AGENT = f'Mozilla/5.0 (X11) odooly.py/{__version__}'
http_context = None

if os.getenv('ODOOLY_SSL_UNVERIFIED'):
    import ssl

    http_context = ssl._create_unverified_context()
    requests = None

if not requests:
    from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


class HTTPSession:
    if requests:  # requests.Session
        def __init__(self):
            self._session = requests.Session()
            self._session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'application/json'})

        def set_auth(self, uri, username, password):
            self._session.auth = (username, password)

        def _request(self, url, method, data, json, headers, **kw):
            resp = self._session.request(method, url, data=data, json=json, headers=headers, **kw)
            return resp.raise_for_status() or resp

        def _parse_response(self, resp):
            is_json = 'json' in resp.headers.get('content-type', '')
            return resp.json() if is_json else resp.text

        def _parse_error(self, err):
            resp = err.response
            return (resp.status_code, self._parse_response(resp)) if resp is not None else (0, 0)

    else:  # urllib.request
        def __init__(self):
            self._session = build_opener(HTTPCookieProcessor(), HTTPSHandler(context=http_context))
            self._session.addheaders = [('User-Agent', USER_AGENT), ('Accept', 'application/json')]

        def set_auth(self, uri, username, password):
            from urllib.request import HTTPBasicAuthHandler
            auth = HTTPBasicAuthHandler()
            auth.add_password(None, uri, username, password)
            self._session.add_handler(auth)

        def _request(self, url, method, data, json, headers, _json=json, **kw):
            headers = dict(headers or ())
            if json is not None:
                headers.setdefault('Content-Type', 'application/json')
            if method == 'POST':
                data = (urlencode(data) if json is None else _json.dumps(json)).encode()
            elif data is not None:
                url, data = f'{url}?{urlencode(data)}', None
            return self._session.open(Request(url, data=data, headers=headers, method=method))

        def _parse_response(self, resp):
            is_json = 'json' in resp.headers.get('content-type', '')
            return json.load(resp) if is_json else resp.read().decode()

        def _parse_error(self, err):
            return (err.code, self._parse_response(err)) if hasattr(err, 'code') else (0, 0)

    def request(self, url, *, method='POST', data=None, json=None, headers=None):
        try:
            with self._request(url, method=method, data=data, json=json, headers=headers) as resp:
                return resp if method == 'HEAD' else self._parse_response(resp)
        except OSError as exc:
            status_code, result = self._parse_error(exc)
            if result and status_code in {401, 403, 404, 422, 500}:
                # Unauthorized, Forbidden, NotFound, UnprocessableContent, InternalServerError
                if isinstance(result, str):
                    lines = re.findall(r'>([^>\n]+)<', result) or (status_code, result)
                    result = {'name': exc.__class__.__name__, 'debug': None,
                              'arguments': (f'{lines[0]} - {lines[-1]}',)}
                raise ServerError({'code': status_code, 'data': result})
            raise
