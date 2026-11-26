import html
import io
import json
import os
import re
from http.cookiejar import Cookie, CookieJar
from urllib.parse import unquote, urlencode, urlsplit

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


def extract_filename(response, default=None):
    # This is RFC6266.  In practice, Odoo returns one of the two, depending on its version:
    #   Content-Disposition: attachment; filename=some_report.pdf
    #   Content-Disposition: attachment; filename*=UTF-8''some%20report.pdf
    content_disposition = response.headers.get('content-disposition', '')
    found = re.search(r"filename\*?=(?:UTF-8'')?(\S+)", content_disposition)
    return unquote(found.group(1)) if found else default


def extract_domain(url):
    host = urlsplit(url).hostname or ''
    if '.' not in host:
        host += '.local'  # Like http.cookiejar.eff_request_host
    return host


def unescape(text):
    # When /report/download hits an AccessError, it can return JSON encoded with HTML entities
    return html.unescape(text) if text[:3] == '{&#' else text


class HTTPSession:
    if requests:  # requests.Session
        def __init__(self):
            self._session = requests.Session()
            self._session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            self._cookies = self._session.cookies

        def set_auth(self, uri, username, password):
            self._session.auth = (username, password)

        def _request(self, url, method, data, json, headers, **kw):
            resp = self._session.request(method, url, data=data, json=json, headers=headers, **kw)
            return resp.raise_for_status() or resp

        def _parse_response(self, resp):
            content_type = resp.headers.get('content-type', '')
            if 'json' in content_type:
                return resp.json()
            if 'text' in content_type:
                return unescape(resp.text)
            rfile = io.BytesIO(resp.content)
            rfile.name = extract_filename(resp)
            return rfile

        def _parse_error(self, err):
            resp = err.response
            return (resp.status_code, self._parse_response(resp)) if resp is not None else (0, 0)

    else:  # urllib.request
        def __init__(self):
            self._cookies = CookieJar()
            self._session = build_opener(HTTPCookieProcessor(self._cookies),
                                         HTTPSHandler(context=http_context))
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
            content_type = resp.headers.get('content-type', '')
            if 'json' in content_type:
                return json.load(resp)
            if 'text' in content_type:
                return unescape(resp.read().decode())
            rfile = io.BytesIO(resp.read())
            rfile.name = extract_filename(resp)
            return rfile

        def _parse_error(self, err):
            return (err.code, self._parse_response(err)) if hasattr(err, 'code') else (0, 0)

    def set_cookie(self, url, name, value):
        """Set the cookie `name` for the host of `url`, or remove it if `value` is None."""
        host = extract_domain(url)
        try:
            self._cookies.clear(host, '/', name)
        except KeyError:
            pass
        if value is not None:
            self._cookies.set_cookie(Cookie(
                0, name, value, None, False, host, False, False, '/', True,
                False, None, True, None, None, {}))

    def get_cookie(self, url, name):
        """Get the cookie `name` for the host of `url`."""
        host = extract_domain(url)
        values = (ck.value for ck in self._cookies
                  if (ck.domain, ck.path, ck.name) == (host, '/', name))
        return next(values, None)

    def request(self, url, *, method='POST', data=None, json=None, headers=None):
        try:
            with self._request(url, method=method, data=data, json=json, headers=headers) as resp:
                return resp if method == 'HEAD' else self._parse_response(resp)
        except OSError as exc:
            status_code, result = self._parse_error(exc)
            if result and status_code in {401, 403, 404, 422, 500}:
                # Unauthorized, Forbidden, NotFound, UnprocessableContent, InternalServerError
                if isinstance(result, str):
                    if os.getenv('ODOO_DEBUG'):
                        print(result)
                    lines = re.findall(r'>([^\n]+)<', result) or (status_code, result)
                    result = {'name': exc.__class__.__name__, 'debug': None,
                              'arguments': (f'{lines[0]} - {lines[-1]}',)}
                raise ServerError({'code': status_code, 'data': result})
            raise
