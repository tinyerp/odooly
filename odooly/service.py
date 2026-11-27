import atexit
import os
from urllib.parse import urljoin

from .exceptions import ServerError
from .helpers import format_params, memoize
from .http import HTTPSession
from .models import Id1, Ids, Model

__all__ = ["WebAPI", "Service", "Json2", "LocalDatabase"]

# Web methods (not exhaustive)
_web_methods = {
    'web/database': ['backup', 'change_password', 'create',
                     'drop', 'duplicate', 'list', 'restore'],
    'web/dataset': ['call_button', 'call_kw'],
    'web/session': ['authenticate', 'check', 'destroy', 'get_lang_list', 'get_session_info'],
    'web/webclient': ['version_info'],
    'report': ['barcode', 'download', 'html', 'pdf', 'text'],
}

# RPC methods
_rpc_methods = {
    'common': ['login', 'authenticate', 'version'],
    'db': ['create_database', 'drop', 'duplicate_database', 'list'],
    'object': ['execute', 'execute_kw'],
}
# Base model
_model_methods = [
    ('action_archive', ['ids']),
    ('action_unarchive', ['ids']),
    ('copy', ['ids', 'default']),
    ('create', ['vals_list']),
    ('get_external_id', ['ids']),
    ('get_metadata', ['ids']),
    ('has_access', ['ids', 'operation']),
    ('read', ['ids', 'fields', 'load']),
    ('search', ['domain', 'offset', 'limit', 'order']),
    ('search_count', ['domain', 'limit']),
    ('search_read', ['domain', 'fields', 'offset', 'limit', 'order']),
    ('unlink', ['ids']),
    ('write', ['ids', 'vals']),
]


def get_base_method_params(client):
    method_params = [*_model_methods]
    if client.version_info < 18.0:
        assert method_params.pop(6)[0] == 'has_access'
    return method_params


def start_odoo_services(options=None, appname=None):
    """Initialize Odoo services.

    Import the ``odoo`` Python package and load the Odoo services.
    The argument `options` receives the command line arguments
    for ``odoo``.  Example:

      ``['-c', '/path/to/odoo-server.conf', '--without-demo', 'all']``.

    Return the ``odoo`` package.
    """
    import odoo
    # Odoo >= 19 does not import the sub-packages with "import odoo"
    import odoo.api
    import odoo.http
    import odoo.modules.registry
    import odoo.release
    import odoo.service.common
    import odoo.service.db
    import odoo.service.model
    import odoo.sql_db
    import odoo.tools
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
    Use ``dir(...)`` on the instance to list its methods.
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
        elif self._endpoint == '/report':
            snt = [f'GET /report/{path}']
        else:
            snt = [f'POST {self._endpoint}/{path}']
        with self._printer as log:
            log.print_sent(' '.join(snt + format_params(params or {})))
            res = self._dispatch(path, params)
            log.print_recv(repr(res))
        return res


class Service:
    """A wrapper around RPC endpoints.

    The connected endpoints are exposed on the Client instance.
    The `client` argument is the connected Client.
    The `endpoint` argument is the name of the service
    (examples: ``"object"``, ``"common"``).
    Use ``dir(...)`` on the instance to list its methods.
    """

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

        # Hide the password: master password for "db", else user password
        secret = 0 if self._endpoint == 'db' else 2

        def sanitize(args):
            if len(args) > secret:
                args = args[:secret] + ('*',) + args[secret + 1:]
            return ', '.join(repr(arg) for arg in args)

        def wrapper(self, *args):
            if not self._printer:
                return self._dispatch(name, args)
            with self._printer as log:
                log.print_sent(f"{self._endpoint}.{name}({sanitize(args)})")
                res = self._dispatch(name, args)
                log.print_recv(repr(res))
            return res
        return memoize(self, name, wrapper)



class LocalDatabase:
    """The ``web/database`` methods used by :class:`Client`, for a local server.

    They are dispatched to the ``db`` RPC service.
    """

    def __init__(self, client):
        self._db = Service(client, 'db')

    def __repr__(self):
        return f"<LocalDatabase {self._db!r}>"

    def list(self):
        return self._db.list()

    def create(self, master_pwd, name, lang, password, demo=False, login='admin',
               country_code=None, phone=None):
        args = [master_pwd, name, demo, lang, password, login, country_code, phone]
        while len(args) > 6 and not args[-1]:
            args.pop()  # Optional arguments, not supported by old versions
        return self._db.create_database(*args)

    def duplicate(self, master_pwd, name, new_name, neutralize_database=False):
        extra = [neutralize_database] if neutralize_database else []
        return self._db.duplicate_database(master_pwd, name, new_name, *extra)

    def drop(self, master_pwd, name):
        return self._db.drop(master_pwd, name)

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
        self._base_method_params = dict(get_base_method_params(client))
        self.reset()

    def doc(self, model):
        """Documentation of the `model`."""
        model_doc = self._request(f'{self._doc_endpoint}/{model}.json')
        if model not in self._method_params:
            method_params = Model._parse_doc_methods(model_doc)
            self._method_params[model] = dict(method_params)
        return model_doc

    def reset(self):
        self._method_params = {'base': self._base_method_params}

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
