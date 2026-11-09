import atexit
import os
from urllib.parse import urljoin

from .exceptions import ServerError
from .helpers import base_method_params, format_params, memoize
from .http import HTTPSession
from .models import Id1, Ids, Model

__all__ = ["WebAPI", "Service", "Json2"]

# Web methods (not exhaustive)
_web_methods = {
    'web/database': ['backup', 'change_password', 'create',
                     'drop', 'duplicate', 'list', 'restore'],
    'web/dataset': ['call_button', 'call_kw'],
    'web/session': ['authenticate', 'check', 'destroy', 'get_lang_list', 'get_session_info'],
    'web/webclient': ['version_info'],
}

# RPC methods
_rpc_methods = {
    'common': ['login', 'authenticate', 'version'],
    'object': ['execute', 'execute_kw'],
}


def start_odoo_services(options=None, appname=None):
    """Initialize Odoo services.

    Import the ``odoo`` Python package and load the Odoo services.
    The argument `options` receives the command line arguments
    for ``odoo``.  Example:

      ``['-c', '/path/to/odoo-server.conf', '--without-demo', 'all']``.

    Return the ``odoo`` package.
    """
    import odoo
    if not hasattr(odoo, "_get_pool"):
        os.putenv('TZ', 'UTC')
        if appname is not None:
            os.putenv('PGAPPNAME', appname)
        odoo.tools.config.parse_config(options or [])
        if odoo.release.version_info < (15,):
            odoo.api.Environment.reset()
        elif odoo.release.version_info > (19, 2):
            import odoo.http.router
            odoo.http.dispatch_rpc = odoo.http.router.dispatch_rpc

        odoo._get_pool = odoo.modules.registry.Registry

        def close_all():
            for db in odoo._get_pool.registries.keys():
                odoo.sql_db.close_db(db)
        atexit.register(close_all)

    return odoo


class WebAPI:
    """A wrapper around Web endpoints.

    The connected endpoints are exposed on the Client instance.
    Argument `client` is the connected Client.
    Argument `endpoint` is the name of the service
    (examples: ``"web/database"``, ``"web/session"``).
    Argument `methods` is the list of methods which should be
    exposed on this endpoint.  Use ``dir(...)`` on the
    instance to list them.
    """
    _methods = ()

    def __init__(self, client, endpoint):
        self._dispatch = client._proxy_web(endpoint)
        self._server = urljoin(client._server, '/')
        self._endpoint = f'/{endpoint}'
        self._methods = [*_web_methods[endpoint]] if endpoint in _web_methods else []
        self._printer = client._printer

    def __repr__(self):
        return f"<WebAPI '{self._server[:-1]}{self._endpoint}'>"

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        def wrapper(self, _func=None, **params):
            return self._request(f'{name}/{_func}' if _func else name, params)
        return memoize(self, name, wrapper)

    def _request(self, path, params=None):
        if not self._printer:
            return self._dispatch(path, params)
        if self._endpoint == '/doc':
            snt = [f'GET /doc/{path}.json']
        else:
            snt = [f'POST {self._endpoint}/{path}'] + format_params(params)
        with self._printer as log:
            log.print_sent(' '.join(snt))
            log.print_recv(repr(res := self._dispatch(path, params)))
        return res


class Service:
    """A wrapper around RPC endpoints.

    The connected endpoints are exposed on the Client instance.
    The `client` argument is the connected Client.
    The `endpoint` argument is the name of the service
    (examples: ``"object"``, ``"common"``).  The `methods` is the list of methods
    which should be exposed on this endpoint.  Use ``dir(...)`` on the
    instance to list them.
    """
    _methods = ()

    def __init__(self, client, endpoint):
        self._dispatch = client._proxy(endpoint)
        self._rpcpath = client._server
        self._endpoint = endpoint
        self._methods = _rpc_methods[endpoint]
        self._printer = client._printer

    def __repr__(self):
        return f"<Service '{self._rpcpath}|{self._endpoint}'>"

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        if name not in self._methods:
            raise AttributeError(f"'Service' object has no attribute {name!r}")

        def sanitize(args):
            if len(args) > 2:
                args = args[:2] + ('*',) + args[3:]
            return ', '.join(repr(arg) for arg in args)

        def wrapper(self, *args):
            if not self._printer:
                return self._dispatch(name, args)
            with self._printer as log:
                log.print_sent(f"{self._endpoint}.{name}({sanitize(args)})")
                log.print_recv(repr(res := self._dispatch(name, args)))
            return res
        return memoize(self, name, wrapper)


class Json2:
    """A connection to Json-2 API

    Added in Odoo 19.
    """
    _protocol_name = 'JSON-2'
    _endpoint = '/json/2'
    _doc_endpoint = '/doc-bearer'

    def __init__(self, client, database, api_key):
        self._http = HTTPSession()
        self._server = urljoin(client._server, '/')
        self._headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-Odoo-Database': database or '',
        }
        self._printer = client._printer
        self.reset()

    def doc(self, model):
        """Documentation of the `model`."""
        model_doc = self._request(f'{self._doc_endpoint}/{model}.json')
        if model not in self._method_params:
            method_params = Model._parse_doc_methods(model_doc)
            self._method_params[model] = dict(method_params)
        return model_doc

    def reset(self):
        self._method_params = {'base': dict(base_method_params)}

    def _methods(self, model):
        if model not in self._method_params:
            self.doc(model)
        return self._method_params[model]

    def _prepare_params(self, model, method, args, kwargs):
        if not args:
            return {**kwargs}
        if len(args) == 1 and args[0].__class__ in {Ids, Id1}:
            return {'ids': args[0], **kwargs}
        if not (arg_names := self._method_params['base'].get(method)):
            arg_names = self._methods(model).setdefault(method, ())
        params = dict(zip(arg_names, args))
        params.update(kwargs)
        if len(args) > len(arg_names) and self._printer:
            print(f"Method {method!r} on {model!r} called with extra args: {args[len(arg_names):]}")
        return params

    def __call__(self, model, method, args, kw=None):
        """Execute API call on the `model`."""
        params = self._prepare_params(model, method, args, kw or {})
        return self._request(f'{self._endpoint}/{model}/{method}', params)

    def __repr__(self):
        return f"<Json2 '{self._server[:-1]}{self._endpoint}'>"

    def _check(self, uid=None):
        url = urljoin(self._server, f'{self._endpoint}/res.users/context_get')
        try:
            context = self._http.request(url, json={}, headers=self._headers)
        except ServerError:
            return False
        return self if (not uid or uid == context['uid']) else False

    def _request(self, path, params=None):
        url = urljoin(self._server, path)
        verb = 'GET' if params is None else 'POST'
        if not self._printer:
            return self._http.request(url, method=verb, json=params, headers=self._headers)
        with self._printer as log:
            log.print_sent(' '.join([verb, path] + format_params(params or {})))
            res = self._http.request(url, method=verb, json=params, headers=self._headers)
            log.print_recv(repr(res))
        return res
