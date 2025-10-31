#!/usr/bin/env python
""" odooly.py -- Odoo / OpenERP client library and command line tool

Author: Florent Xicluna
"""
import _ast
import atexit
import csv
import functools
import json
import optparse
import os
import re
import shlex
import sys
import time
import traceback

from configparser import ConfigParser
from getpass import getpass
from pathlib import Path
from string import Formatter
from threading import current_thread
from urllib.parse import urlencode, urljoin
from xmlrpc.client import Fault, MININT, MAXINT, ServerProxy

try:
    import requests
except ImportError:
    requests = None

__version__ = '2.4.5'
__all__ = ['Client', 'Env', 'HTTPSession', 'WebAPI', 'Service', 'Json2',
           'Printer', 'Error', 'ServerError',
           'BaseModel', 'Model', 'BaseRecord', 'Record', 'RecordList',
           'format_exception', 'read_config', 'start_odoo_services']

CONF_FILE = Path('odooly.ini')
HIST_FILE = Path('~/.odooly_history').expanduser()
DEFAULT_URL = 'http://localhost:8069/'
ADMIN_USER = 'admin'
SYSTEM_USER = '__system__'
MAXCOL = [79, 179, 9999]    # Line length in verbose mode
USER_AGENT = 'Mozilla/5.0 (X11)'

USAGE = """\
Usage (some commands):
    env[name]                       # Return a Model instance
    env[name].keys()                # List field names of the model
    env[name].fields(names=None)    # Return details for the fields
    env[name].field(name)           # Return details for the field
    env[name].browse(ids=())
    env[name].search(domain)
    env[name].search(domain, offset=0, limit=None, order=None)
                                    # Return a RecordList

    rec = env[name].get(domain)     # Get the Record matching domain
    rec.some_field                  # Return the value of this field
    rec.read(fields=None)           # Return values for the fields

    client.login(user)              # Login with another user
    client.connect(env)             # Connect to another env.
    client.connect(server=None)     # Connect to another server
    env.models(name)                # List models matching pattern
    env.modules(name)               # List modules matching pattern
    env.install(module1, module2, ...)
    env.upgrade(module1, module2, ...)
                                    # Install or upgrade the modules
    env.upgrade_cancel()            # Reset failed upgrade/install
"""

DOMAIN_OPERATORS = frozenset('!|&')
# Supported operators are:
#   =, !=, >, >=, <, <=, like, ilike, in, not like, not ilike, not in,
#   =like, =ilike, =?, child_of, parent_of,   # parent_of: Odoo 9
#   any, not any,                             # Odoo 17
#   not =like, not =ilike,                    # Odoo 19
_term_re = re.compile(
    r'([\w._]+)\s*'   r'(=like\b|=ilike\b|=\?|[<>]=?|!?=|'
    r'\b(?:like|ilike|in|any|not (?:=?like|=?ilike|in|any)|child_of|parent_of)\b)'
    r'(?![?!=<>])\s*(.+)')

# Web methods (not exhaustive)
_web_methods = {
    'database': ['backup', 'change_password', 'create',
                 'drop', 'duplicate', 'list', 'restore'],
    'dataset': ['call_button', 'call_kw'],
    'session': ['authenticate', 'check', 'destroy', 'get_lang_list', 'get_session_info'],
    'webclient': ['version_info'],
}

# Published object methods
_rpc_methods = {
    'common': ['about', 'login', 'authenticate', 'version'],
    'db': ['create_database', 'duplicate_database', 'db_exist', 'drop', 'dump',
           'restore', 'rename', 'list', 'list_lang', 'list_countries',
           'change_admin_password', 'server_version', 'migrate_databases'],
    'object': ['execute', 'execute_kw'],
}
# New Odoo 7:       (db) duplicate_database
# New Odoo 9:       (db) list_countries
# No-op:            (common) set_loglevel
# Removed Odoo 19:  (common) version, replaced by GET /web/version

_obsolete_rpc_methods = {
    'common': [
        'check_connectivity', 'get_available_updates',
        'get_migration_scripts', 'get_os_time', 'get_stats',
        'get_server_environment', 'get_sqlcount',
        'list_http_services', 'login_message',              # Odoo < 8
        'timezone_get',                                     # Odoo < 9
    ],
    'db': ['create', 'get_progress'],                       # Odoo < 8
    'object': ['exec_workflow'],                            # Odoo < 11
    'report': ['render_report', 'report', 'report_get'],    # Odoo < 11
    'wizard': ['execute', 'create'],                        # Odoo < 7
}
_cause_message = ("\nThe above exception was the direct cause "
                  "of the following exception:\n\n")
_pending_state = ('state', 'not in',
                  ['uninstallable', 'uninstalled', 'installed'])
http_context = None

if os.getenv('ODOOLY_SSL_UNVERIFIED'):
    import ssl

    def ServerProxy(url, transport, allow_none, _ServerProxy=ServerProxy):
        return _ServerProxy(url, transport=transport, allow_none=allow_none,
                            context=ssl._create_unverified_context())
    http_context = ssl._create_unverified_context()
    requests = None

if not requests:
    from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


class HTTPSession:
    if requests:  # requests.Session
        def __init__(self):
            self._session = requests.Session()

        def request(self, url, *, method='POST', data=None, json=None, headers=None, **kw):
            resp = self._session.request(method, url, data=data, json=json, headers=headers, **kw)
            resp.raise_for_status()
            return resp if method == 'HEAD' else resp.text if json is None else resp.json()

    else:  # urllib.request
        def __init__(self):
            self._session = build_opener(HTTPCookieProcessor(), HTTPSHandler(context=http_context))

        def request(self, url, *, method='POST', data=None, json=None, headers=None, _json=json, **kw):
            headers = dict(headers or ())
            if json is not None:
                headers.setdefault('Content-Type', 'application/json')
            if method == 'POST':
                data = (urlencode(data) if json is None else _json.dumps(json)).encode()
            elif data is not None:
                url, data = f'{url}?{urlencode(data)}', None
            request = Request(url, data=data, headers=headers, method=method)
            with self._session.open(request) as resp:
                return resp if method == 'HEAD' else resp.read().decode() if json is None else _json.load(resp)


def _memoize(inst, attr, value, doc_values=None):
    if hasattr(value, '__get__') and not hasattr(value, '__self__'):
        value.__name__ = attr
        if doc_values is not None:
            value.__doc__ %= doc_values
        value = value.__get__(inst, type(inst))
    inst.__dict__[attr] = value
    return value


_ast_node_attrs = []
for (cls, attr) in [('Constant', 'value'),      # Python >= 3.7
                    ('NameConstant', 'value'),  # Python >= 3.4 (singletons)
                    ('Str', 's'),               # Python <= 3.7
                    ('Num', 'n')]:              # Python <= 3.7
    if hasattr(_ast, cls):
        _ast_node_attrs.append((getattr(_ast, cls), attr))


# Simplified ast.literal_eval which does not parse operators
def _convert(node):
    for (ast_class, node_attr) in _ast_node_attrs:
        if isinstance(node, ast_class):
            return getattr(node, node_attr)
    if isinstance(node, _ast.Tuple):
        return tuple(map(_convert, node.elts))
    if isinstance(node, _ast.List):
        return list(map(_convert, node.elts))
    if isinstance(node, _ast.Dict):
        return {_convert(k): _convert(v)
                for (k, v) in zip(node.keys, node.values)}
    if isinstance(node, _ast.UnaryOp):
        if isinstance(node.op, _ast.USub):
            return -_convert(node.operand)
        if isinstance(node.op, _ast.UAdd):
            return +_convert(node.operand)
    raise ValueError('malformed or disallowed expression')


def literal_eval(expression, _octal_digits=frozenset('01234567')):
    node = compile(expression, '<unknown>', 'eval', _ast.PyCF_ONLY_AST)
    if expression[:1] == '0' and expression[1:2] in _octal_digits:
        raise SyntaxError('unsupported octal notation')
    value = _convert(node.body)
    if isinstance(value, int) and not MININT <= value <= MAXINT:
        raise ValueError('overflow, int exceeds XML-RPC limits')
    return value


def is_list_of_dict(iterator):
    """Return True if the first non-false item is a dict."""
    for item in iterator:
        if item:
            return isinstance(item, dict)
    return False


def format_params(params, hide=('passw', 'pwd')):
    secret = {key: ... for key in params if any(sub in key for sub in hide)}
    return [f'{key}={v!r}' if v != ... else f'{key}=*'
            for (key, v) in {**params, **secret}.items()]


def format_exception(exc_type, exc, tb, limit=None, chain=True,
                     _format_exception=traceback.format_exception):
    """Format a stack trace and the exception information.

    This wrapper is a replacement of ``traceback.format_exception``
    which formats the error and traceback received by XML-RPC/JSON-RPC.
    If `chain` is True, then the original exception is printed too.
    """
    values = _format_exception(exc_type, exc, tb, limit=limit)
    server_error = None
    if issubclass(exc_type, Error):             # Client-side
        values = [f"{exc}\n"]
    elif issubclass(exc_type, OSError):         # HTTPError (requests or urllib)
        values = [f"{exc_type.__name__}: {exc}\n"]
    elif issubclass(exc_type, ServerError):     # JSON-RPC or Web API
        server_error = exc.args[0]['data']
        print_tb = not server_error.get('name', '').startswith('odoo.')
    elif (issubclass(exc_type, Fault) and       # XML-RPC
          isinstance(exc.faultCode, str)):
        (message, tb) = (exc.faultCode, exc.faultString)
        exc_name = exc_type.__name__
        print_tb = not message.startswith('warning --')
        if print_tb:       # ValidationError, DatabaseExists, etc ...
            parts = message.rsplit('\n', 1)
            if parts[-1] == 'None':
                message, print_tb = parts[0], False
            last_line = tb.rstrip().rsplit('\n', 1)[-1]
            if last_line.startswith('odoo.'):
                exc_name, print_tb = last_line.split(':', 1)[0], False
        else:
            message = re.sub(r'\((.*), None\)$',
                             lambda m: literal_eval(m.group(1)),
                             message.split(None, 2)[2])
        server_error = {'name': exc_name, 'arguments': (message,), 'debug': tb}
    if server_error:
        # Format readable XML-RPC and JSON-RPC errors
        try:
            message = str(server_error['arguments'][0])
        except Exception:
            message = str(server_error['arguments'])
        fault = f"{server_error['name']}: {message}"
        tb = print_tb and not message.startswith('FATAL:') and server_error['debug']
        if chain:
            values = [tb or fault, _cause_message] + values
            values[-1] = fault
        else:
            values = [tb or fault]
    return values


def read_config(section=None):
    """Read the environment settings from the configuration file.

    Config file ``odooly.ini`` contains a `section` for each environment.
    Each section provides parameters for the connection: ``server``,
    ``username`` and (optional) ``database``, ``password`` and ``api_key``.
    As an alternative, server can be declared with 4 parameters:
    ``scheme / host / port / protocol``.
    Default values are read from the ``[DEFAULT]`` section.  If the ``password``
    is not set or is empty, it is requested on login.
    Return tuple ``(server, db or None, user, password or None, api_key or None)``.
    Without argument, it returns the list of configured environments.
    """
    p = ConfigParser()
    with Path(Client._config_file).open() as f:
        p.read_file(f)
    if section is None:
        return p.sections()
    env = dict(p.items(section))
    scheme = env.get('scheme', 'http')
    server = env.get('server')
    if scheme == 'local':
        server = shlex.split(server or env.get('options', ''))
    elif not server:
        protocol = env.get('protocol', 'web')
        server = f"{scheme}://{env['host']}:{env['port']}/{protocol}"
    return (server, env.get('database', ''), env['username'], env.get('password'), env.get('api_key'))


def start_odoo_services(options=None, appname=None):
    """Initialize the Odoo services.

    Import the ``odoo`` Python package and load the Odoo services.
    The argument `options` receives the command line arguments
    for ``odoo``.  Example:

      ``['-c', '/path/to/odoo-server.conf', '--without-demo', 'all']``.

    Return the ``odoo`` package.
    """
    try:
        import openerp as odoo
    except ImportError:
        import odoo
    if not hasattr(odoo, "_get_pool"):
        os.putenv('TZ', 'UTC')
        if appname is not None:
            os.putenv('PGAPPNAME', appname)
        odoo.tools.config.parse_config(options or [])
        if odoo.release.version_info < (7,):
            odoo.netsvc.init_logger()
            odoo.osv.osv.start_object_proxy()
            odoo.service.web_services.start_web_services()
        elif odoo.release.version_info < (8,):
            odoo.service.start_internal()
        elif odoo.release.version_info < (15,):
            odoo.api.Environment.reset()

        try:
            manager_class = odoo.modules.registry.RegistryManager
            odoo._get_pool = manager_class.get
        except AttributeError:  # Odoo >= 10
            odoo._get_pool = manager_class = odoo.modules.registry.Registry

        def close_all():
            for db in manager_class.registries.keys():
                odoo.sql_db.close_db(db)
        atexit.register(close_all)

    return odoo


def issearchdomain(arg):
    """Check if the argument is a search domain.

    Examples:
      - ``[('name', '=', 'mushroom'), ('state', '!=', 'draft')]``
      - ``['name = mushroom', 'state != draft']``
      - ``[]``
    """
    return isinstance(arg, list) and not (arg and (
        # Not a list of ids: [1, 2, 3]
        isinstance(arg[0], int) or
        # Not a list of ids as str: ['1', '2', '3']
        (isinstance(arg[0], str) and arg[0].isdigit())))


def searchargs(params, kwargs=None):
    """Compute the 'search' parameters."""
    if not params:
        return ([],)
    domain = params[0]
    if not isinstance(domain, list):
        return params
    for (idx, term) in enumerate(domain):
        if isinstance(term, str) and term not in DOMAIN_OPERATORS:
            m = _term_re.match(term.strip())
            if not m:
                raise ValueError(f"Cannot parse term {term!r}")
            (field, operator, value) = m.groups()
            try:
                value = literal_eval(value)
            except Exception:
                # Interpret the value as a string
                pass
            domain[idx] = (field, operator, value)
    params = (domain,) + params[1:]
    if kwargs and len(params) == 1:
        args = (kwargs.pop('offset', 0),
                kwargs.pop('limit', None),
                kwargs.pop('order', None))
        if any(args):
            params += args
    return params


def readfmt(arg):
    if '}' in arg:
        fields = [re.match(r'\w+', tup[1]).group(0)
                  for tup in Formatter().parse(arg) if tup[1]]
        formatter = arg.format_map
    elif '%(' in arg:
        fields = re.findall(r'(?<!%)%\((\w+)\)', arg)
        formatter = arg.__mod__
    else:
        # transform: "zip city" --> ("zip", "city")
        fields = arg.split()
        formatter = (lambda d: d[fields[0]]) if len(fields) == 1 else None
    return fields, formatter


def parse_http_response(method, result, regex):
    if method == 'HEAD':
        return result.url
    found = re.search(regex or r'odoo._*session_info_* = (.*);', result)
    return found and (found.group(1) if regex else json.loads(found.group(1)))


class partial(functools.partial):
    __slots__ = ()

    def __repr__(self):
        # Hide arguments
        return f"{self.__class__.__name__}({self.func!r}, ...)"


class Error(Exception):
    """An Odooly error."""


class ServerError(Exception):
    """An error received from the server."""


class Printer:
    def __init__(self, verbose):
        self._maxcol = MAXCOL[min(len(MAXCOL), verbose) - 1]

    def print_sent(self, request):
        snt = str(request)
        if len(snt) > self._maxcol:
            suffix = f"... L={len(snt)}"
            snt = snt[:self._maxcol - len(suffix)] + suffix
        print(f"--> {snt}")

    def print_recv(self, result, _convert=repr):
        rcv = _convert(result)
        if len(rcv) > self._maxcol:
            suffix = f"... L={len(rcv)}"
            rcv = rcv[:self._maxcol - len(suffix)] + suffix
        print(f"<-- {rcv}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            if issubclass(exc_type, ServerError):
                exc = exc.args[0]["data"]["name"]
            self.print_recv(f"{exc_type.__name__}: {exc}", str)


class WebAPI:
    """A wrapper around Web endpoints.

    The connected endpoints are exposed on the Client instance.
    Argument `client` is the connected Client.
    Argument `endpoint` is the name of the service
    (examples: ``"database"``, ``"session"``).
    Argument `methods` is the list of methods which should be
    exposed on this endpoint.  Use ``dir(...)`` on the
    instance to list them.
    """
    _methods = ()

    def __init__(self, client, endpoint, methods):
        self._dispatch = client._proxy_web(endpoint)
        self._server = urljoin(client._server, '/')
        self._endpoint = f'/web/{endpoint}' if endpoint else '/web'
        self._methods = methods
        self._printer = client._printer

    def __repr__(self):
        return f"<WebAPI '{self._server[:-1]}{self._endpoint}'>"

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        if self._printer:
            def wrapper(self, _func=None, **params):
                method = f'{name}/{_func}' if _func else name
                snt = ' '.join(format_params(params))
                with self._printer as log:
                    log.print_sent(f"POST {self._endpoint}/{method} {snt}")
                    res = self._dispatch(method, params)
                    log.print_recv(res)
                return res
        else:
            def wrapper(self, _func=None, **params):
                return self._dispatch(f'{name}/{_func}' if _func else name, params)
        return _memoize(self, name, wrapper)


class Service:
    """A wrapper around RPC endpoints.

    The connected endpoints are exposed on the Client instance.
    The `client` argument is the connected Client.
    The `endpoint` argument is the name of the service
    (examples: ``"object"``, ``"db"``).  The `methods` is the list of methods
    which should be exposed on this endpoint.  Use ``dir(...)`` on the
    instance to list them.
    """
    _methods = ()

    def __init__(self, client, endpoint, methods):
        self._dispatch = client._proxy(endpoint)
        self._rpcpath = client._server
        self._endpoint = endpoint
        self._methods = methods
        self._printer = client._printer

    def __repr__(self):
        return f"<Service '{self._rpcpath}|{self._endpoint}'>"

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        if name not in self._methods:
            raise AttributeError(f"'Service' object has no attribute {name!r}")
        if self._printer:
            def sanitize(args):
                if self._endpoint != 'db' and len(args) > 2:
                    args = list(args)
                    args[2] = '*'
                return args

            def wrapper(self, *args):
                snt = ', '.join(repr(arg) for arg in sanitize(args))
                with self._printer as log:
                    log.print_sent(f"{self._endpoint}.{name}({snt})")
                    res = self._dispatch(name, args)
                    log.print_recv(res)
                return res
        else:
            def wrapper(self, *args):
                return self._dispatch(name, args)
        return _memoize(self, name, wrapper)


class Json2:
    """A connection to Json-2 API

    Added in Odoo 19.
    """
    _endpoint = '/json/2'
    _doc_endpoint = '/doc-bearer'

    def __init__(self, client, database, api_key):
        self._req = HTTPSession().request
        self._server = urljoin(client._server, '/')
        self._headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-Odoo-Database': database or '',
        }
        self._method_params = {}
        self._printer = client._printer

    def doc(self, model):
        """Documentation of the `model`."""
        res = self._request(f'{self._doc_endpoint}/{model}.json')
        return json.loads(res)

    def _prepare_params(self, model, method, args, kwargs):
        if not args:
            return {**kwargs}
        try:
            arg_names = self._method_params[model][method]
        except KeyError:
            methods = self.doc(model).get('methods') or {}
            self._method_params[model] = dict_methods = {}
            for key, vals in methods.items():
                arg_names = list(vals['parameters'])
                if 'model' not in vals.get('api', ()):
                    arg_names.insert(0, 'ids')
                dict_methods[key] = arg_names
            arg_names = dict_methods.setdefault(method, ())
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
            context = self._req(url, json={}, headers=self._headers)
        except (OSError, ServerError):
            return False
        return self if (not uid or uid == context['uid']) else False

    def _request(self, path, params=None):
        verb = 'GET' if params is None else 'POST'
        url = urljoin(self._server, path)

        if not self._printer:
            return self._req(url, json=params, headers=self._headers, method=verb)

        snt = ' '.join(f'{key}={v!r}' for (key, v) in (params or {}).items())
        with self._printer as log:
            log.print_sent(f"{verb} {path} {snt}".rstrip())
            res = self._req(url, json=params, headers=self._headers, method=verb)
            log.print_recv(res)
        return res


class Env:
    """An environment wraps data for Odoo models and records:

        - :attr:`db_name`, the current database;
        - :attr:`uid`, the current user id;
        - :attr:`context`, the current context dictionary.

        To retrieve an instance of ``some.model``:

        >>> env["some.model"]
    """

    name = uid = user = session_info = _api_key = _json2 = None
    _cache = {}

    def __new__(cls, client, db_name=()):
        if db_name:
            env = cls._cache.get((Env, db_name, client._server))
            if env and env.client == client:
                return env
        if not db_name or client.env.db_name:
            env = object.__new__(cls)
            env.client, env.db_name, env.context = client, db_name, {}
        else:
            env, env.db_name = client.env, db_name
        if db_name:
            env._model_names = env._cache_get('model_names', set)
            env._models = {}
        env._web = client.web
        return env

    def __contains__(self, name):
        """Test wether this model exists."""
        return name in self._model_names or name in self.models(name)

    def __getitem__(self, name):
        """Return the :class:`Model` for the given ``name``."""
        return self._get(name)

    def __iter__(self):
        """Return an iterator on model names."""
        return iter(self.models())

    def __len__(self):
        """Return the size of the model registry."""
        return len(self.models())

    def __bool__(self):
        return True

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    def __repr__(self):
        return f"<Env '{self.user.login if self.uid else ''}@{self.db_name}'>"

    def _check_user_password(self, user, password, api_key):
        if self.client._object and not self.db_name:
            raise Error('Error: Not connected')
        assert isinstance(user, str) and user
        if user == SYSTEM_USER:
            info = self.client._authenticate_system()
            return info['uid'], password, info
        # Read from cache
        auth_cache = self._cache_get('auth', dict)
        (uid, pwcache) = auth_cache.get(user) or (None, None)
        password = password or pwcache
        # Ask for password
        if not password and not api_key:
            password = getpass(f"Password for {user!r}: ")
        if not self.client._object:
            try:  # Standard Web or JSON-2 authentication
                info = self.client._authenticate(self.db_name, user, password, api_key)
                uid = info['uid']
            except Exception as exc:
                if 'does not exist' in str(exc):    # Heuristic
                    raise Error('Error: Database does not exist')
                raise
        else:  # Login through RPC Service (deprecated)
            if not uid:
                uid = self.client.common.login(self.db_name, user, api_key or password)
            if uid:
                args = self.db_name, uid, api_key or password, 'res.users', 'context_get', ()
                info = {'uid': uid, 'user_context': self.client._object.execute_kw(*args)}
        if not uid:  # Failed
            if user in auth_cache:
                del auth_cache[user]
            raise Error('Error: Invalid username or password')
        # Discovered database name
        if not self.db_name:
            self.db_name = info.get('db') or ()
            # Set the cache for authentication
            self._cache_set('auth', auth_cache)
            self.refresh()
        if not self.uid:
            # Cache the unauthenticated Env and the client
            self._cache_set(Env, self)
        # Update credentials in cache
        auth_cache[user] = uid, password
        return uid, password, info

    def set_api_key(self, api_key, store=True):
        """Configure methods to use an API key."""
        def env_auth(method):     # Authenticated endpoints
            return partial(method, self.db_name, self.uid, api_key)
        if self.client.web and self.client.version_info >= 19.0:
            self._json2 = Json2(self.client, self.db_name, api_key)._check(self.uid)
        if self.client._object:  # RPC endpoint if available
            self._execute = env_auth(self.client._object.execute)
            self._execute_kw = env_auth(self.client._object.execute_kw)
        else:  # Otherwise, use JSON-2 or WebAPI
            self._execute_kw = self._json2 or self._call_kw
        if store:
            self._api_key = api_key

        if self.client._report:   # Odoo < 11
            self.exec_workflow = env_auth(self.client._object.exec_workflow)
            self.report = env_auth(self.client._report.report)
            self.report_get = env_auth(self.client._report.report_get)
            self.render_report = env_auth(self.client._report.render_report)
        if self.client._wizard:   # OpenERP 6.1
            self.wizard_execute = env_auth(self.client._wizard.execute)
            self.wizard_create = env_auth(self.client._wizard.create)
        return api_key

    def _configure(self, uid, user, password, api_key, context, session):
        env = Env(self.client)
        (env.db_name, env.name) = (self.db_name, self.name)
        env._model_names = self._model_names
        env._models = {}

        # Setup uid and user
        if isinstance(user, Record):
            user = user.login
        env.uid = uid
        env.user = env._get('res.users', False).browse(uid)
        env.context = dict(context)
        env.session_info = session
        if user:
            assert isinstance(user, str), repr(user)
            env.user.__dict__['login'] = user

        # Set API methods
        if uid != self.uid or (api_key and api_key != self._api_key):
            env.set_api_key(api_key or password, bool(api_key))
        else:  # Copy methods
            env._execute_kw = self._execute_kw
            env._api_key, env._json2 = self._api_key, self._json2
            for key in ('_execute', 'exec_workflow',
                        'report', 'report_get', 'render_report',
                        'wizard_execute', 'wizard_create'):
                if hasattr(self, key):
                    setattr(env, key, getattr(self, key))
        return env

    @property
    def odoo_env(self):
        """Return a server Environment.

        Supported since Odoo 8.
        """
        assert self.client.version_info >= 8.0, 'Not supported'
        return self.client._server.api.Environment(self.cr, self.uid,
                                                   self.context)

    @property
    def cr(self):
        """Return a cursor on the database."""
        return self.__dict__.get('cr') or _memoize(
            self, 'cr', self.registry.db.cursor()
            if self.client.version_info < 8.0 else self.registry.cursor())

    @property
    def registry(self):
        """Return the environment's registry."""
        return self.client._server._get_pool(self.db_name)

    def __call__(self, user=None, password=None, api_key=None, context=None):
        """Return an environment based on ``self`` with modified parameters."""
        if user is not None:
            (uid, password, session) = self._check_user_password(user, password, api_key)
            if context is None:
                context = session['user_context']
        elif context is not None:
            (uid, user, session) = (self.uid, self.user, self.session_info)
        else:
            return self
        env_key = bytes.fromhex(f"{uid:08x}{hash(json.dumps(context, sort_keys=True))%2**32:08x}")
        env = self._cache_get(env_key)
        if env is None:
            env = self._configure(uid, user, password, api_key, context, session)
            self._cache_set(env_key, env)
        return env

    def sudo(self, user=None):
        """Attach to the provided user, or Superuser."""
        if user is None:
            if (self.client._object or self.client.version_info < 12.0 or
                    not self.session_info or not self.session_info.get('is_system')):
                user = ADMIN_USER
            else:
                user = SYSTEM_USER
        return self(user=user)

    def ref(self, xml_id):
        """Return the record for the given ``xml_id`` external ID."""
        (module, name) = xml_id.split('.')
        data = self['ir.model.data'].read(
            [('module', '=', module), ('name', '=', name)], 'model res_id')
        if data:
            assert len(data) == 1
            return self[data[0]['model']].browse(data[0]['res_id'])

    @property
    def lang(self):
        """Return the current language code."""
        return self.context.get('lang')

    def refresh(self):
        db_key = (self.db_name, self.client._server)
        for key in list(self._cache):
            if key[1:] == db_key and key[0] != 'auth':
                del self._cache[key]
        self._model_names = self._cache_set('model_names', set())
        self._models = {}
        if self._json2:
            self._json2._method_params = {}

    def _cache_get(self, key, func=None):
        try:
            return self._cache[key, self.db_name, self.client._server]
        except KeyError:
            pass
        if func is not None:
            return self._cache_set(key, func())

    def _cache_set(self, key, value, db_name=None):
        self._cache[key, db_name or self.db_name, self.client._server] = value
        return value

    def _is_identitycheck(self, result):
        return hasattr(result, 'items') and result.get('res_model') == 'res.users.identitycheck'

    def _identitycheck(self, result):
        assert self.client.version_info >= 14.0
        idcheck = self[result['res_model']].get(result['res_id'])
        password = self._cache_get('auth')[self.user.login][1]
        result = None
        while not result:
            try:
                password = password or getpass(f"Password for {self.user.login!r}: ")
            except (KeyboardInterrupt, EOFError):
                print()
                raise Error("Security Control - FAILED")
            if self.client.version_info < 19.0:
                idcheck.password = password
            try:
                # Odoo >= 19 read from context
                result = idcheck.with_context(password=password).run_check()
            except ServerError:
                password = None
                if not self.client._is_interactive():
                    raise
        if self.client._is_interactive():
            print("Security Control - PASSED")
        return result

    def _call_kw(self, model, method, args, kw=None):
        if self.uid != self.client._session_uid:
            if self.user.login == SYSTEM_USER:
                self.client._authenticate_system()
            else:
                password = self._cache_get('auth')[self.user.login][1]
                self.client._authenticate_session(self.db_name, self.user.login, password)
        return self.client.web_dataset.call_kw(model=model, method=method, args=args, kwargs=kw or {})

    def execute(self, obj, method, *params, **kwargs):
        """Wrapper around ``/web/dataset/call_kw`` Webclient endpoint,
        or ``/json/2`` API endpoint or ``object.execute_kw`` RPC method.

        Argument `method` is the name of a standard ``Model`` method
        or a specific method available on this `obj`.
        Method `params` are accepted.  If needed, keyword
        arguments are collected in `kwargs`.
        """
        assert self.uid, 'Not connected'
        assert isinstance(obj, str)
        assert isinstance(method, str) and method != 'browse'
        order_ids = single_id = False
        if method == 'read':
            assert params, 'Missing parameter'
            if not isinstance(params[0], list):
                single_id = True
                ids = [params[0]] if params[0] else False
            elif params[0] and issearchdomain(params[0]):
                # Combine search+read
                if self.client.version_info < 8.0:
                    search_params = searchargs(params[:1], kwargs)
                    kw = ({'context': self.context},) if self.context else ()
                    ids = self._execute_kw(obj, 'search', search_params, *kw)
                else:
                    method = 'search_read'
                    [ids] = searchargs(params[:1])
            else:
                order_ids = kwargs.pop('order', False) and params[0]
                ids = sorted(set(params[0]) - {False})
                if not ids and order_ids:
                    return [False] * len(order_ids)
            if not ids:
                return ids
            params = (ids,) + params[1:]
        elif method == 'search':
            # Accept keyword arguments for the search method
            params = searchargs(params, kwargs)
        elif method == 'search_count':
            params = searchargs(params)
        elif method == 'search_read':
            params = searchargs(params[:1]) + params[1:]
        kw = ((dict(kwargs, context=self.context),)
              if self.context else (kwargs and (kwargs,) or ()))
        res = self._execute_kw(obj, method, params, *kw)
        if self._is_identitycheck(res):
            res = self._identitycheck(res)
        if order_ids:
            # Results were not in the same order as the IDs
            # in case of missing records or duplicate ID
            resdic = {val['id']: val for val in res}
            res = [resdic.get(id_, False) for id_ in order_ids]
        return res[0] if single_id else res

    def access(self, model_name, mode="read"):
        """Check if the user has access to this model.

        Optional argument `mode` is the access mode to check.  Valid values
        are ``read``, ``write``, ``create`` and ``unlink``. If omitted,
        the ``read`` mode is checked.  Return a boolean.
        """
        try:
            self.execute('ir.model.access', 'check', model_name, mode)
            return True
        except Exception:
            return False

    def _models_get(self, name, check=False):
        if name not in self._model_names:
            if check:
                raise KeyError(name)
            self._model_names.add(name)
        try:
            return self._models[name]
        except KeyError:
            self._models[name] = Model._new(self, name)
        return self._models[name]

    def models(self, name=''):
        """Search Odoo models.

        The argument `name` is a pattern to filter the models returned.
        If omitted, all models are returned.

        The return value is a sorted list of model names.
        """
        domain = [('model', 'like', name)]
        models = self.execute('ir.model', 'read', domain, ('model',))
        names = [m['model'] for m in models]
        self._model_names.update(names)
        return sorted(names)

    def _get(self, name, check=True):
        """Return a :class:`Model` instance.

        The argument `name` is the name of the model.  If the optional
        argument `check` is :const:`False`, no validity check is done.
        """
        try:
            return self._models_get(name, check)
        except KeyError:
            model_names = self.models(name)
        if name in model_names:
            return self._models_get(name, True)
        if model_names:
            errmsg = 'Model not found.  These models exist:'
        else:
            errmsg = f'Model not found: {name}'
        raise Error('\n * '.join([errmsg] + model_names))

    def modules(self, name='', installed=None):
        """Return a dictionary of modules.

        The optional argument `name` is a pattern to filter the modules.
        If the boolean argument `installed` is :const:`True`, the modules
        which are "Not Installed" or "Not Installable" are omitted.  If
        the argument is :const:`False`, only these modules are returned.
        If argument `installed` is omitted, all modules are returned.
        The return value is a dictionary where module names are grouped in
        lists according to their ``state``.
        """
        if isinstance(name, str):
            domain = [('name', 'like', name)]
        else:
            domain = name
        if installed is not None:
            op = 'not in' if installed else 'in'
            domain.append(('state', op, ['uninstalled', 'uninstallable']))
        ir_module = self._get('ir.module.module', False)
        mods = ir_module.read(domain, 'name state')
        if mods:
            res = {}
            for mod in mods:
                if mod['state'] not in res:
                    res[mod['state']] = []
                res[mod['state']].append(mod['name'])
            return res

    def _upgrade(self, modules, button, quiet):
        # First, update the list of modules
        ir_module = self._get('ir.module.module', False)
        updated, added = ir_module.update_list()
        if added:
            print(f'{added} module(s) added to the list')
        # Find modules
        sel = modules and ir_module.search([('name', 'in', modules)])
        mods = ir_module.read([_pending_state], 'name state')
        if sel:
            # Safety check
            if any(mod['name'] not in modules for mod in mods):
                raise Error('Pending actions:\n' + '\n'.join(
                    f"  {mod['state']}\t{mod['name']}" for mod in mods))
            if button == 'button_uninstall':
                # Safety check
                names = ir_module.read([('id', 'in', sel.ids),
                                        'state != installed',
                                        'state != to upgrade',
                                        'state != to remove'], 'name')
                if names:
                    raise Error(f"Not installed: {', '.join(names)}")
                if self.client.version_info < 7.0:
                    # A trick to uninstall dependent add-ons
                    sel.write({'state': 'to remove'})
            # Click upgrade/install/uninstall button
            if button != 'cancel':
                self.execute('ir.module.module', button, sel.ids)
                mods = ir_module.read([_pending_state], 'name state')
        if not mods:
            if sel:
                print('Already up-to-date: %s' %
                      self.modules([('id', 'in', sel.ids)]))
            elif modules:
                raise Error(f"Module(s) not found: {', '.join(modules)}")
            print(f'{updated} module(s) updated')
            return
        print(f'{len(sel)} module(s) selected')
        print(f'{len(mods)} module(s) to process:')
        for mod in mods:
            print(f"  {mod['state']}\t{mod['name']}")

        # Confirm?
        if not quiet and any(mod['id'] not in sel.ids for mod in mods):
            assert self.client._is_interactive(), "Cannot continue"
            ans = input('Confirm? [y/N] ')
            if not ans or ans[:1].lower() != 'y':
                button = 'cancel'

        if button == 'cancel':
            # Reset module state
            if self.client.version_info < 19.0:
                installed = [mod['id'] for mod in mods if mod['state'] != 'to install']
                uninstalled = [mod['id'] for mod in mods if mod['state'] == 'to install']
                if uninstalled:
                    self.execute('ir.module.module', 'button_install_cancel', uninstalled)
                if installed:
                    self.execute('ir.module.module', 'button_upgrade_cancel', installed)
            else:  # Odoo >= 19
                self.execute('ir.module.module', 'button_reset_state')
        else:
            # Apply scheduled upgrades
            self.execute('base.module.upgrade', 'upgrade_module', [])
            # Empty the cache for this database
            self.refresh()

    def upgrade(self, *modules, quiet=False):
        """Press button ``Upgrade``."""
        return self._upgrade(modules, button='button_upgrade', quiet=quiet)

    def install(self, *modules, quiet=False):
        """Press button ``Install``."""
        return self._upgrade(modules, button='button_install', quiet=quiet)

    def uninstall(self, *modules, quiet=False):
        """Press button ``Uninstall``."""
        return self._upgrade(modules, button='button_uninstall', quiet=quiet)

    def upgrade_cancel(self):
        """Press button ``Cancel Upgrade/Install/Uninstall``."""
        return self._upgrade((), button='cancel', quiet=True)

    def session_authenticate(self, login=None, password=None):
        """Create a Webclient session for current user."""
        if not login:
            login = self.user.login
        params = {
            'db': self.db_name,
            'login': login,
            'password': password or getpass(f"Password for {login!r}: "),
        }
        self.session_info = self.client._authenticate_session(**params)
        # When database name is discovered, copy cached data
        if not self.db_name and (not self.uid or login == self.user.login) and self.session_info.get('db'):
            empty_db_key = (self.db_name, self.client._server)
            self.db_name = self.session_info['db']
            for key in list(self._cache):
                if key[1:] == empty_db_key:
                    self._cache_set(key[0], self._cache[key])
        print(f'Session authenticated for {login!r}' if self.session_info['uid'] else 'Failed')

    def session_destroy(self):
        """Terminate current Webclient session."""
        self.session_info = None
        self.client._session_uid = None
        try:
            return self.client.web_session.destroy()
        except ServerError as exc:
            # Ignore: odoo.http.SessionExpiredException
            if exc.args[0]['code'] != 100:
                raise

    def generate_api_key(self):
        """Generate an API Key and configure environment to use it.

        Caution: API Key is not saved. It can be set in the
        configuration: ``api_key = ...``.
        """
        assert self.client.version_info >= 14.0, 'Not supported'
        key_vals = {'name': f'Created by Odooly {__version__}'}
        wiz = self["res.users.apikeys.description"].create(key_vals)
        res = wiz.make_key()
        self.user.refresh()
        assert res['res_model'] == "res.users.apikeys.show"
        return self.set_api_key(res['context']['default_key'])


class Client:
    """Connection to an Odoo instance.

    This is the top level object.
    The `server` is the URL of the instance, like ``http://localhost:8069``.
    If `server` is an ``odoo``/``openerp`` Python package, it is used to
    connect to the local server.

    The `db` is the name of the database and the `user` should exist in the
    table ``res.users``.  If the `password` is not provided, it will be
    asked on login.
    """
    _config_file = CONF_FILE
    _saved_config = {}
    _globals = None

    def __init__(self, server, db=None, user=None, password=None,
                 api_key=None, transport=None, verbose=False):
        self._http = HTTPSession()
        self._session_uid = None

        self._set_services(server, db, transport, verbose)
        self.env = Env(self)
        if user:  # Try to login
            self.login(user, password=password, api_key=api_key, database=db)

    def _set_services(self, server, db, transport, verbose):
        if isinstance(server, list):
            appname = Path(__file__).name.rstrip('co')
            server = start_odoo_services(server, appname=appname)
        elif isinstance(server, str) and server[-1:] == '/':
            server = server.rstrip('/')
        self._printer = Printer(verbose=verbose) if verbose else None
        self._server = server
        self._verbose = verbose
        self._connections = []

        if not isinstance(server, str):
            api_v7 = server.release.version_info < (8,)
            self._proxy = self._proxy_v7 if api_v7 else self._proxy_odoo
        elif '/xmlrpc' in server:
            self._proxy = self._proxy_xmlrpc
            self._transport = transport
        elif '/jsonrpc' in server:
            self._proxy = self._proxy_jsonrpc
        else:
            if not db:
                # Resolve redirects
                __, server = self._request_parse(server, method='HEAD')
            if not server.endswith('/web'):
                server = urljoin(server, '/web')
            self._server = server
            self._proxy = self.db = self.common = None
            self._object = self._report = self._wizard = None
        assert not transport or self._proxy is self._proxy_xmlrpc, 'Not supported'

        if isinstance(server, str):

            def get_web_api(name):
                methods = list(_web_methods.get(name) or [])
                return WebAPI(self, name, methods)
            self.web = get_web_api(None)
            self.database = get_web_api('database')
            self.web_dataset = get_web_api('dataset')
            self.web_session = get_web_api('session')
            self.web_webclient = get_web_api('webclient')
        else:
            self.web = None

        # Request server version
        if self._proxy is None:
            self.server_version = self.web_webclient.version_info()["server_version"]
        else:
            self.server_version = Service(self, 'db', ['server_version']).server_version()
        major_minor = re.search(r'\d+\.?\d*', self.server_version).group()
        self.version_info = float_version = float(major_minor)
        assert float_version > 6.0, f'Not supported: {float_version}'

        # Create the RPC services
        if self._proxy is not None:

            def get_service(name):
                methods = list(_rpc_methods.get(name) or [])
                if float_version < 11.0:
                    methods += _obsolete_rpc_methods.get(name) or ()
                return Service(self, name, methods)
            self.db = get_service('db')
            self.common = get_service('common')
            self._object = get_service('object')
            self._report = get_service('report') if float_version < 11.0 else None
            self._wizard = get_service('wizard') if float_version < 7.0 else None

    def _request_parse(self, path, *, method=None, data=None, headers=None, regex=None):
        headers = {'User-Agent': USER_AGENT, **(headers or {})}
        verb = method or ('GET' if data is None else 'POST')
        url = urljoin(self._server, path)
        if not self._printer:
            res = self._http.request(url, data=data, headers=headers, method=verb)
            return res, parse_http_response(verb, res, regex)

        snt = ' '.join(format_params(data or {}))
        with self._printer as log:
            log.print_sent(f"{verb} {path} {snt}".rstrip())
            res = self._http.request(url, data=data, headers=headers, method=verb)
            parsed = parse_http_response(verb, res, regex)
            log.print_recv(parsed, str)
        return res, parsed

    def _post_jsonrpc(self, endpoint='', params=None):
        req_id = f"{os.getpid():04x}{int(time.time() * 1E6) % 2**40:010x}"
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params or {}, 'id': req_id}
        resp = self._http.request(urljoin(self._server, endpoint), json=payload)
        if resp.get('error'):
            raise ServerError(resp['error'])
        return resp.get('result')

    def _proxy_odoo(self, name):
        return partial(self._server.http.dispatch_rpc, name)

    def _proxy_v7(self, name):
        return self._server.netsvc.ExportService.getService(name).dispatch

    def _proxy_xmlrpc(self, name):
        proxy = ServerProxy(self._server + '/' + name,
                            transport=self._transport, allow_none=True)
        self._connections.append(proxy)
        return proxy._ServerProxy__request

    def _proxy_jsonrpc(self, name):
        def dispatch_jsonrpc(method, args):
            return self._post_jsonrpc(params={'service': name, 'method': method, 'args': args})
        return dispatch_jsonrpc

    def _proxy_web(self, name):
        def dispatch_web(method, params):
            if name == 'database' and method != 'list':
                return self._http.request(urljoin(self._server, f"web/{name or ''}/{method}"), data=params)
            return self._post_jsonrpc(f"web/{name or ''}/{method}", params=params)
        return dispatch_web

    def save(self, environment=None, skip=False):
        """Save environment settings with this name, or current name"""
        self.env.name = environment or self.env.name or self.env.db_name
        if not skip and self.env.uid:
            config = (self._server, self.env.db_name, self.env.user.login, None, self.env._api_key)
            self._saved_config[self.env.name] = config
        if self._globals and self._globals.get('client', self) is self:
            self._set_prompt()
        return self

    @classmethod
    def get_config(cls, environment):
        """Retrieve the settings for this environment.

        It can be in memory, if it was saved before with :meth:`Client.save`.
        If not, it will parse ``odooly.ini`` file, where it searches for the
        section ``[ <environment> ]``.

        See :func:`read_config` for details of the configuration file format.
        """
        assert environment
        if environment not in cls._saved_config:
            cls._saved_config[environment] = read_config(environment)
        return cls._saved_config[environment]

    @classmethod
    def from_config(cls, environment, user=None, verbose=False):
        """Create a connection to a defined environment.

        See :meth:`Client.get_config`
        Return a connected :class:`Client`.
        """
        (server, db, conf_user, password, api_key) = cls.get_config(environment)
        skip_save = user and user != conf_user
        if skip_save:
            password = None
        try:
            client = Env._cache[Env, db, server].client
            client.login(user or conf_user, password=password, api_key=api_key)
        except KeyError:
            client = cls(server, db, user or conf_user, password=password, api_key=api_key, verbose=verbose)
        return client.save(environment, skip=skip_save)

    def __repr__(self):
        return f"<Client '{self._server}?db={self.env.db_name or ''}'>"

    def close(self):
        for conn in self._connections:
            conn.__exit__()
        self._connections = []

    def _authenticate(self, db, login, password, api_key):
        if api_key and not password and self.version_info >= 19.0:
            json2_api = Json2(self, db, api_key)
            context = json2_api('res.users', 'context_get', ())
            info = {'uid': context['uid'], 'user_context': context, 'db': db}
        elif self.web and self.version_info >= 9.0:
            info = self._authenticate_session(db, login, password)
        else:
            raise Error("Error: Cannot authenticate")
        return info

    def _authenticate_session(self, db, login, password):
        info = {'uid': None}
        try:
            if db:
                info = self.web_session.authenticate(db=db, login=login, password=password)
                if self.version_info >= 15.0 and info['uid'] is None:  # Is it 2FA?
                    info = self._authenticate_web(db=db, login=login, password=password)
            else:
                info = self._authenticate_web(login=login, password=password)
            self._session_uid = info.get('uid')
        except TypeError:
            # Cannot extract `csrf_token` or `session_info` with Regex
            pass
        except ServerError as exc:
            # Ignore: odoo.exceptions.AccessDenied
            if exc.args[0]['code'] not in (0, 200):
                raise
        return info

    def _authenticate_web(self, **kw):
        # 1. Get CSRF token
        qs = f"?{urlencode(dict(db=kw['db']))}" if "db" in kw else ""
        __, csrf = self._request_parse('/web' + qs, regex=r'csrf_token: "(\w+)"')

        # 2. Login
        rv, session_info = self._request_parse('/web/login', data={'csrf_token': csrf, **kw})

        for retry in range(4):
            # 3. Parse 'session_info'
            if 'user_id' in session_info and 'uid' not in session_info:  # Odoo < 18
                session_info['uid'] = session_info['user_id']
            if retry and not session_info['uid']:
                print('Verification failed')
            if session_info['uid'] or 'totp_token' not in rv or retry == 3:
                break

            # 4. Ask TOTP code
            token = getpass(f"Authentication Code for {kw['login']!r} (2FA 6-digits): ")

            # 5. Submit TOTP
            params = {'csrf_token': csrf, 'totp_token': token, 'remember': 1}
            rv, session_info = self._request_parse('/web/login/totp', data=params)
        return session_info

    def _authenticate_system(self):
        __, session_info = self._request_parse('/web/become')
        self._session_uid = session_info.get('uid')
        if self._session_uid != 1:
            raise Error("Cannot become Superuser")
        return session_info

    def _select_database(self, db_list, limit=20):
        if len(db_list) == 1:
            return db_list[0]
        if not db_list or not self._is_interactive():
            return
        print('Available databases:')
        for idx, name in enumerate(db_list[:limit], start=1):
            print(f' {idx}. {name!r}')
        if len(db_list) > limit:
            print(' ...')
        print()
        while db_list:
            ans = input('Select a database: ')
            try:
                return db_list[int(ans) - 1]
            except Exception:
                pass

    def _login(self, user, password=None, database=None, api_key=None):
        """Switch `user` and (optionally) `database`.

        If the `password` is not available, it will be asked.
        """
        env = self.env
        if not env.db_name or (database and env.db_name != database):
            try:
                dbs = self.db.list() if self.db else self.database.list()
            except Exception:
                pass    # AccessDenied: simply ignore this check
            else:
                if not database:
                    # Database selector page
                    database = self._select_database(dbs)
                elif dbs and database not in dbs:
                    raise Error("Database '%s' does not exist: %s" %
                                (database, dbs))
        if database and env.db_name != database:
            env = Env(self, database)
        try:
            self.env = env(user=user, password=password, api_key=api_key)
        except Exception:
            current_thread().dbname = self.env.db_name
            raise
        # Used for logging, copied from odoo.sql_db.db_connect
        current_thread().dbname = self.env.db_name
        return self.env.uid

    def login(self, user, password=None, database=None, api_key=None):
        """Switch `user` and (optionally) `database`."""
        if not self._is_interactive():
            return self._login(user, password=password, database=database, api_key=api_key)
        try:
            self._login(user, password=password, database=database, api_key=api_key)
        except Error as exc:
            print(exc)
        else:
            # Register the new globals()
            self.connect()

    def connect(self, env_name=None, *, server=None, user=None):
        """Connect to another environment and replace the globals()."""
        assert self._is_interactive(), 'Not available'
        if env_name:
            self.from_config(env_name, user=user, verbose=self._verbose)
        elif server:
            if not user and self.env.uid:
                user = self.env.user.login
            self.__class__(server, user=user, verbose=self._verbose)
        else:
            assert not user, "Use client.login(...) instead"
            self._globals['client'] = self.env.client
            self._globals['env'] = self.env
            self._globals['self'] = self.env.user if self.env.uid else None
            self._set_prompt()
            # Logged in?
            if self.env.uid:
                print(f'Logged in as {self.env.user.login!r}')

    def _set_prompt(self):
        # Tweak prompt
        sys.ps1 = f'{self.env.name or self.env.db_name} >>> '
        sys.ps2 = '... '.rjust(len(sys.ps1))

    @classmethod
    def _set_interactive(cls, global_vars={}):
        # Don't call multiple times
        del Client._set_interactive
        assert not cls._is_interactive()

        for name in ['__name__', '__version__', '__doc__', 'Client']:
            global_vars[name] = globals()[name]
        cls._globals = global_vars
        return global_vars

    @classmethod
    def _is_interactive(cls):
        return cls._globals is not None

    def create_database(self, passwd, database, demo=False, lang='en_US',
                        user_password=ADMIN_USER, login=ADMIN_USER,
                        country_code=None):
        """Create a new database.

        The superadmin `passwd` and the `database` name are mandatory.
        By default, `demo` data are not loaded, `lang` is ``en_US``
        and no country is set into the database.
        Login if successful.
        """
        extra = (login, country_code) if login != ADMIN_USER or country_code else ()
        if extra and self.version_info < 9.0:
            raise Error("Custom 'login' and 'country_code' are not supported")
        if self.db:
            self.db.create_database(passwd, database, demo, lang,
                                    user_password, *extra)
        else:
            self.database.create(master_pwd=passwd, name=database, lang=lang,
                                 password=user_password, demo=demo, login=login,
                                 country_code=country_code, phone='')
        return self.login(login, user_password, database=database)

    def clone_database(self, passwd, database, neutralize_database=False):
        """Clone the current database.

        The superadmin `passwd` and `database` are mandatory.
        Login if successful.

        Supported since OpenERP 7.
        """
        extra = (neutralize_database,) if neutralize_database else ()
        if extra and self.version_info < 16.0:
            raise Error("Argument 'neutralize_database' is not supported")
        if self.db:
            self.db.duplicate_database(passwd, self.env.db_name, database, *extra)
        else:
            extra = {"neutralize_database": extra[0]} if extra else {}
            self.database.duplicate(master_pwd=passwd, name=self.env.db_name,
                                    new_name=database, **extra)
        # Copy the cache for authentication
        auth_cache = self.env._cache_get('auth')
        self.env._cache_set('auth', {**auth_cache}, db_name=database)

        # Login with the current user into the new database
        auth_args = {
            'password': auth_cache[self.env.user.login][1],
            'api_key': self.env._api_key,
            'database': database,
        }
        return self.login(self.env.user.login, **auth_args)

    def drop_database(self, passwd, database):
        """Drop the database.

        The superadmin `passwd` and `database` are mandatory.
        """
        if not database or database == self.env.db_name:
            raise Error("Failed - Cannot delete active database")
        if self.db:
            self.db.drop(passwd, database)
            db_list = self.db.list()
        else:
            self.database.drop(master_pwd=passwd, name=database)
            db_list = self.database.list()
        if database in db_list:
            raise Error("Failed - Database was not deleted")


class BaseModel:

    ids = ()

    def sudo(self, user=None):
        """Attach to the provided user, or Superuser."""
        return self.with_env(self.env.sudo(user=user))

    def with_context(self, *args, **kwargs):
        """Attach to an extended context."""
        context = dict(args[0] if args else self.env.context, **kwargs)
        return self.with_env(self.env(context=context))

    def with_odoo(self):
        """Attach to an ``odoo.api.Environment``.

        Use same (db_name, uid, context) as current ``Env``.
        Only available in ``local`` mode.
        """
        return self.with_env(self.env.odoo_env)


class Model(BaseModel):
    """The class for Odoo models."""

    def __new__(cls, env, name):
        return env[name]

    @classmethod
    def _new(cls, env, name):
        m = object.__new__(cls)
        (m.env, m._name) = (env, name)
        m._execute = partial(env.execute, name)
        return m

    def __repr__(self):
        return f"<Model '{self._name}'>"

    def with_env(self, env):
        """Attach to the provided environment."""
        return env[self._name]

    def keys(self):
        """Return the keys of the model."""
        return self._keys

    def fields(self, names=None, attributes=None):
        """Return a dictionary of the fields of the model.

        Optional argument `names` is a sequence of field names or
        a space separated string of these names.
        If omitted, all fields are returned.
        Optional argument `attributes` is a sequence of attributes
        or a space separated string of these attributes.
        If omitted, all attributes are returned.
        """
        if isinstance(names, str):
            names = names.split()
        if isinstance(attributes, str):
            attributes = attributes.split()
        if names is None:
            if attributes is None:
                return self._fields
            return {fld: {att: val
                          for (att, val) in vals.items() if att in attributes}
                    for (fld, vals) in self._fields.items()}
        if attributes is None:
            return {fld: vals
                    for (fld, vals) in self._fields.items() if fld in names}
        return {fld: {att: val
                      for (att, val) in vals.items() if att in attributes}
                for (fld, vals) in self._fields.items() if fld in names}

    def field(self, name):
        """Return the field properties for field `name`."""
        return self._fields[name]

    def access(self, mode="read"):
        """Check if the user has access to this model.

        Optional argument `mode` is the access mode to check.  Valid values
        are ``read``, ``write``, ``create`` and ``unlink``. If omitted,
        the ``read`` mode is checked.  Return a boolean.
        """
        return self.env.access(self._name, mode)

    def browse(self, ids=()):
        """Return a :class:`Record` or a :class:`RecordList`.

        The argument `ids` accepts a single integer ``id`` or a list of ids.
        If it is a single integer, the return value is a :class:`Record`.
        Otherwise, the return value is a :class:`RecordList`.
        """
        return BaseRecord(self, ids)

    def search(self, domain, *params, **kwargs):
        """Search for records in the `domain`."""
        reverse = kwargs.pop('reverse', False)
        ids = self._execute('search', domain, *params, **kwargs)
        return RecordList(self, ids[::-1] if reverse else ids)

    def search_count(self, domain=None):
        """Count the records in the `domain`."""
        return self._execute('search_count', domain or [])

    def get(self, domain, *args, **kwargs):
        """Return a single :class:`Record`.

        The argument `domain` accepts a single integer ``id`` or a search
        domain, or an external ID ``xml_id``.  The return value is a
        :class:`Record` or None.  If multiple records are found,
        a ``ValueError`` is raised.
        """
        if args or kwargs:
            # Passthrough for env['ir.default'].get and alike
            return self._execute('get', domain, *args, **kwargs)
        if isinstance(domain, int):   # a single id
            return Record(self, domain)
        if isinstance(domain, str):  # lookup the xml_id
            rec = self.env.ref(domain)
            if not rec:
                return None
            assert rec._model is self, f'Model mismatch {rec!r} {self!r}'
            return rec
        assert issearchdomain(domain)       # a search domain
        ids = self._execute('search', domain)
        if len(ids) > 1:
            raise ValueError(f'domain matches too many records ({len(ids)})')
        return Record(self, ids[0]) if ids else None

    def create(self, values):
        """Create one :class:`Record` or many.

        The argument `values` is a dictionary of values which are used to
        create the record.  Relationship fields `one2many` and `many2many`
        accept either a list of ids or a RecordList or the extended Odoo
        syntax.  Relationship fields `many2one` and `reference` accept
        either a Record or the Odoo syntax.
        Since Odoo 12, it can create multiple records.

        The newly created :class:`Record` is returned, or :class:`RecordList`.
        """
        if hasattr(values, "items"):
            values = self._unbrowse_values(values)
        else:  # Odoo >= 12
            values = [self._unbrowse_values(vals) for vals in values]
        new_ids = self._execute('create', values)
        return Record(self, new_ids)

    def read(self, *params, **kwargs):
        """Wrapper for ``client.execute(model, 'read', [...], ('a', 'b'))``.

        The first argument is a list of ids ``[1, 3]`` or a single id ``42``
        or a search domain.

        The second argument, `fields`, accepts:
         - a single field: ``'first_name'``
         - a tuple of fields: ``('street', 'city')``
         - a space separated list: ``'street city'``
         - a format string: ``'{street} {city}'``
         - a %-format string: ``'%(street)s %(city)s'``

        If `fields` is omitted, all fields are read.

        If `domain` is a single id, then:
         - return a single value if a single field is requested.
         - return a string if a format spec is passed in the `fields` argument.
         - else, return a dictionary.

        If `domain` is not a single id, the returned value is a list of items.
        Each item complies with the rules of the previous paragraph.

        The optional keyword arguments `offset`, `limit` and `order` are
        used to restrict the search.
        """
        fmt = None
        if len(params) > 1 and isinstance(params[1], str):
            fields, fmt = readfmt(params[1])
            params = (params[0], fields) + params[2:]
        res = self._execute('read', *params, **kwargs)
        if not fmt or not res:
            return res
        return [(d and fmt(d)) for d in res] if isinstance(res, list) else fmt(res)

    def _browse_values(self, values):
        """Wrap the values of a Record.

        The argument `values` is a dictionary of values read from a Record.
        When the field type is relational (many2one, one2many or many2many),
        the value is wrapped in a Record or a RecordList.
        Return a dictionary with the same keys as the `values` argument.
        """
        for (key, value) in values.items():
            if key == 'id' or value is False or hasattr(value, 'id'):
                continue
            field = self._fields[key]
            if field['type'] == 'reference':
                (res_model, res_id) = value.split(',')
                value = int(res_id)
            elif 'relation' in field:
                res_model = field['relation']
            else:
                continue
            rel_model = self.env._get(res_model, False)
            values[key] = BaseRecord(rel_model, value)
        return values

    def _unbrowse_values(self, values):
        """Unwrap the id of Record and RecordList."""
        new_values = values.copy()
        for (key, value) in values.items():
            field_type = self._fields[key]['type']
            if hasattr(value, 'id'):
                if field_type == 'reference':
                    new_values[key] = f'{value._name},{value.id}'
                else:
                    new_values[key] = value = value.id
            if field_type in ('one2many', 'many2many'):
                if not value:
                    new_values[key] = [(6, 0, [])]
                elif isinstance(value[0], int):
                    new_values[key] = [(6, 0, value)]
        return new_values

    def _get_external_ids(self, ids=None):
        """Retrieve the External IDs of the records.

        Return a dictionary with keys being the fully qualified
        External IDs, and values the ``Record`` entries.
        """
        search_domain = [('model', '=', self._name)]
        if ids is not None:
            search_domain.append(('res_id', 'in', ids))
        existing = self.env['ir.model.data'].read(search_domain,
                                                  ['module', 'name', 'res_id'])
        res = {}
        for rec in existing:
            res[f"{rec['module']}.{rec['name']}"] = self.get(rec['res_id'])
        return res

    def __getattr__(self, attr):
        if attr == '_fields':
            vals = self.env._cache_get((attr, self._name))
            if vals is None:
                vals = self._execute('fields_get')
                self.env._cache_set((attr, self._name), vals)
            return _memoize(self, attr, vals)
        if attr == '_keys':
            return _memoize(self, attr, sorted(self._fields))
        if attr.startswith('_'):
            raise AttributeError(f"'Model' object has no attribute {attr!r}")

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute(%r, %r, *params, **kwargs)."""
            return self._execute(attr, *params, **kwargs)
        return _memoize(self, attr, wrapper, (self._name, attr))


class BaseRecord(BaseModel):

    def __new__(cls, res_model, arg):
        if isinstance(arg, int):
            inst = object.__new__(Record)
            name = None
            idnames = [arg]
            ids = [arg]
        elif len(arg) == 2 and isinstance(arg[1], str):
            inst = object.__new__(Record)
            (arg, name) = arg
            idnames = [(arg, name)]
            ids = [arg]
        else:
            inst = object.__new__(RecordList)
            idnames = arg or ()
            ids = list(idnames)
            for index, id_ in enumerate(arg):
                if isinstance(id_, (list, tuple)):
                    ids[index] = id_ = id_[0]
                assert isinstance(id_, int), repr(id_)
            arg = ids
        attrs = {
            'id': arg,
            'ids': ids,
            'env': res_model.env,
            '_name': res_model._name,
            '_model': res_model,
            '_idnames': idnames,
            '_execute': res_model._execute,
        }
        if isinstance(inst, Record):
            attrs['_cached_keys'] = set()
            if name is not None:
                attrs['_Record__name'] = attrs['display_name'] = name
        # Bypass the __setattr__ method
        inst.__dict__.update(attrs)
        return inst

    def __repr__(self):
        if len(self.ids) > 16:
            ids = f'length={len(self.ids)}'
        else:
            ids = self.id
        return f"<{self.__class__.__name__} '{self._name},{ids}'>"

    def __dir__(self):
        attrs = set(self.__dict__) | set(self._model._keys)
        return sorted(attrs)

    def __bool__(self):
        return bool(self.ids)

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, key):
        idname = self._idnames[key]
        if idname is False and not isinstance(key, slice):
            return False
        return BaseRecord(self._model, idname)

    def __iter__(self):
        for idname in self._idnames:
            yield BaseRecord(self._model, idname)

    def __contains__(self, item):
        if isinstance(item, BaseRecord):
            item._check_model(self, 'in')
            return len(item) == 1 and item.ids[0] in self.ids

    def __add__(self, other):
        return self.concat(other)

    def __sub__(self, other):
        self._check_model(other, '-')
        other_ids = set(other.ids)
        ids = [idn for (id_, idn) in zip(self.ids, self._idnames)
               if id_ not in other_ids]
        return BaseRecord(self._model, ids)

    def __and__(self, other):
        self._check_model(other, '&')
        other_ids = set(other.ids)
        self_set = self.union()
        ids = [idn for (id_, idn) in zip(self_set.ids, self_set._idnames)
               if id_ in other_ids]
        return BaseRecord(self._model, ids)

    def __or__(self, other):
        return self.union(other)

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.ids == other.ids and self._model is other._model)

    def __ne__(self, other):
        return not self == other

    def __lt__(self, other):
        self._check_model(other, '<')
        return set(self.ids) < set(other.ids)

    def __le__(self, other):
        self._check_model(other, '<=')
        return set(self.ids).issubset(other.ids)

    def __gt__(self, other):
        self._check_model(other, '>')
        return set(self.ids) > set(other.ids)

    def __ge__(self, other):
        self._check_model(other, '>=')
        return set(self.ids).issuperset(other.ids)

    def __int__(self):
        return self.ensure_one().id

    @property
    def _keys(self):
        return self._model._keys

    @property
    def _fields(self):
        return self._model._fields

    def refresh(self):
        pass

    def ensure_one(self):
        """Return the single record in this recordset.

        Raise a ValueError it recordset has more records or is empty.
        """
        if self.id and not isinstance(self.id, list):
            return self
        recs = self.union()
        if len(recs.id) == 1:
            return recs[0]
        raise ValueError(f"Expected singleton: {self}")

    def exists(self):
        """Return a subset of records that exist."""
        if self.env.client.version_info < 19.0:
            method, arg = 'exists', self.union().ids
        else:
            # Beware that it might be wrong, if `search` method is overloaded.
            # This is the case for 'ir.attachment' for example.
            method, arg = 'search', [('id', 'in', self.union().ids)]
        ids = self.ids and self._execute(method, arg, context={'active_test': False})
        if ids and not isinstance(self.id, list):
            ids = ids[0]
        return BaseRecord(self._model, ids)

    def get_metadata(self):
        """Read the metadata of the record(s)

        Return a dictionary of values.
        """
        if self.env.client.version_info < 8.0:
            rv = self._execute('perm_read', self.ids)
            return rv[0] if (rv and self.id != self.ids) else (rv or None)
        return self._execute('get_metadata', self.ids)

    def with_env(self, env):
        return env[self._name].browse(self.id)

    def _check_model(self, other, oper):
        if not (isinstance(other, BaseRecord) and
                self._model is other._model):
            raise TypeError("Mixing apples and oranges: %s %s %s" %
                            (self, oper, other))

    def _concat_ids(self, args):
        ids = list(self._idnames)
        for other in args:
            self._check_model(other, '+')
            ids.extend(other._idnames)
        return ids

    def concat(self, *args):
        """Return the concatenation of all records."""
        ids = self._concat_ids(args)
        return BaseRecord(self._model, ids)

    def union(self, *args):
        """Return the union of all records.

        Preserve first occurence order.
        """
        ids = self._concat_ids(args)
        if len(ids) > 1:
            seen = set()
            uniqids = []
            for idn in ids:
                id_, name = idn if isinstance(idn, (list, tuple)) else (idn, None)
                if id_ not in seen and not seen.add(id_) and id_:
                    uniqids.append((id_, name) if name else id_)
            ids = uniqids
        return BaseRecord(self._model, ids)

    @classmethod
    def _union(cls, args):
        if hasattr(args, 'union'):
            return args.union()
        if args and isinstance(args, list) and hasattr(args[0], 'union'):
            return cls.union(*args)
        return args

    def _filter(self, attrs):
        ids, rels = [], []
        for (rec, rel) in zip(self, self.read(attrs.pop(0))):
            if rel and (not hasattr(rel, 'ids') or rel.id):
                ids.append(rec._idnames[0])
                rels.append(rel)
        if ids and attrs:
            relids = {idn[0] for idn in BaseRecord.union(*rels)._filter(attrs)}
            ids = [rec_id for (rec_id, rel) in zip(ids, rels)
                   if any(rel_id in relids for rel_id in rel.ids)]
        return ids

    def mapped(self, func):
        """Apply ``func`` on all records."""
        if callable(func):
            return self._union([func(rec) for rec in self])
        # func is a path
        vals = self[:]
        for name in func.split('.'):
            vals = self._union(vals.read(name))
        return vals

    def filtered(self, func):
        """Select the records such that ``func(rec)`` is true.

        As an alternative ``func`` can be a search domain (list)
        to search among the records.
        """
        if callable(func):
            ids = [rec._idnames[0] for rec in self if func(rec)]
        elif isinstance(func, list):
            return self & self._model.search([('id', 'in', self.ids)] + func)
        else:
            ids = self[:]._filter(func.split('.')) if func else self._idnames
        return BaseRecord(self._model, ids)

    def sorted(self, key=None, reverse=False):
        """Return the records sorted by ``key``."""
        recs = self.union()
        if len(recs.ids) < 2:
            return recs
        if key is None:
            idnames = dict(zip(recs.ids, recs._idnames))
            recs = self._model.search([('id', 'in', recs.ids)],
                                      reverse=reverse)
            ids = [idnames[id_] for id_ in recs.ids]
        elif isinstance(key, str):
            vals = sorted(zip(recs.read(key), recs._idnames), reverse=reverse)
            ids = [idn for (__, idn) in vals]
        else:
            ids = [rec._idnames[0]
                   for rec in sorted(recs, key=key, reverse=reverse)]
        return BaseRecord(self._model, ids)

    def write(self, values):
        """Write the `values` in the record(s).

        `values` is a dictionary of values.
        See :meth:`Model.create` for details.
        """
        if not self.id:
            return True
        values = self._model._unbrowse_values(values)
        rv = self._execute('write', self.ids, values)
        self.refresh()
        return rv

    def unlink(self):
        """Delete the record(s) from the database."""
        if not self.id:
            return True
        rv = self._execute('unlink', self.ids)
        self.refresh()
        return rv


class RecordList(BaseRecord):
    """A sequence of Odoo :class:`Record`.

    It has a similar API as the :class:`Record` class, but for a list of
    records.  The attributes of the ``RecordList`` are read-only, and they
    return list of attribute values in the same order.  The ``many2one``,
    ``one2many`` and ``many2many`` attributes are wrapped in ``RecordList``
    and list of ``RecordList`` objects.  Use the method ``RecordList.write``
    to assign a single value to all the selected records.
    """

    def read(self, fields=None):
        """Read the `fields` of the :class:`RecordList`.

        The argument `fields` accepts different kinds of values.
        See :meth:`Model.read` for details.
        """
        if self.id:
            values = self._model.read(self.id, fields, order=True)
            if is_list_of_dict(values):
                browse_values = self._model._browse_values
                return [v and browse_values(v) for v in values]
        else:
            values = []

        if isinstance(fields, str):
            field = self._model._fields.get(fields)
            if field:
                if 'relation' in field:
                    rel_model = self.env._get(field['relation'], False)
                    if not values or field['type'] == 'many2one':
                        return RecordList(rel_model, values)
                    return [RecordList(rel_model, v) for v in values]
                if field['type'] == 'reference':
                    records = []
                    for value in values:
                        if value:
                            (res_model, res_id) = value.split(',')
                            rel_model = self.env._get(res_model, False)
                            value = Record(rel_model, int(res_id))
                        records.append(value)
                    return records
        return values

    def copy(self, default=None):
        """Copy records and return :class:`RecordList`.

        The optional argument `default` is a mapping which overrides some
        values of the new records.

        Supported since Odoo 18.
        """
        if default:
            default = self._model._unbrowse_values(default)
        new_ids = self._execute('copy', self.ids, default)
        return RecordList(self._model, new_ids)

    @property
    def _external_id(self):
        """Retrieve the External IDs of the :class:`RecordList`.

        Return the fully qualified External IDs with default value
        False if there's none.  If multiple IDs exist for a record,
        only one of them is returned (randomly).
        """
        xml_ids = {r.id: xml_id for (xml_id, r) in
                   self._model._get_external_ids(self.id).items()}
        return [xml_ids.get(res_id, False) for res_id in self.id]

    def __getattr__(self, attr):
        if attr in self._model._keys:
            return self.read(attr)
        if attr.startswith('_'):
            errmsg = f"'RecordList' object has no attribute {attr!r}"
            raise AttributeError(errmsg)

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute(%r, %r, [...], *params, **kwargs)."""
            return self._execute(attr, self.id, *params, **kwargs)
        return _memoize(self, attr, wrapper, (self._name, attr))

    def __setattr__(self, attr, value):
        if attr in self._model._keys or attr == 'id':
            msg = f"attribute {attr!r} is read-only; use 'RecordList.write' instead."
        else:
            msg = f"has no attribute {attr!r}"
        raise AttributeError("'RecordList' object " + msg)


class Record(BaseRecord):
    """A class for all Odoo records.

    It maps any Odoo object.
    The fields can be accessed through attributes.  The changes are immediately
    sent to the server.
    The ``many2one``, ``one2many`` and ``many2many`` attributes are wrapped in
    ``Record`` and ``RecordList`` objects.  These attributes support writing
    too.
    The attributes are evaluated lazily, and they are cached in the record.
    The Record's cache is invalidated if any attribute is changed.
    """

    def __str__(self):
        return self.__name if self.id else 'False'

    def _get_name(self):
        try:
            if self.env.client.version_info < 8.0:
                [(id_, name)] = self._execute('name_get', [self.id])
            else:
                name = self.display_name
        except Exception:
            name = f'{self._name},{self.id}'
        self.__dict__['_idnames'] = [(self.id, str(name))]
        return _memoize(self, '_Record__name', str(name))

    def refresh(self):
        """Force refreshing the record's data."""
        self._cached_keys.discard('id')
        for key in self._cached_keys:
            delattr(self, key)
        self._cached_keys.clear()

    def _update(self, values):
        new_values = self._model._browse_values(values)
        self.__dict__.update(new_values)
        self._cached_keys.update(new_values)
        return new_values

    def read(self, fields=None):
        """Read the `fields` of the :class:`Record`.

        The argument `fields` accepts different kinds of values.
        See :meth:`Model.read` for details.
        """
        rv = self._model.read(self.id, fields)
        if isinstance(rv, dict):
            return self._update(rv)
        if isinstance(fields, str) and fields in self._model._keys:
            return self._update({fields: rv})[fields]
        return rv

    def copy(self, default=None):
        """Copy a record and return the new :class:`Record`.

        The optional argument `default` is a mapping which overrides some
        values of the new record.
        """
        if default:
            default = self._model._unbrowse_values(default)
        new_id = self._execute('copy', self.id, default)
        if isinstance(new_id, list):
            [new_id] = new_id or [False]
        return Record(self._model, new_id)

    def _send(self, signal):
        """Trigger workflow `signal` for this :class:`Record`."""
        assert self.env.client.version_info < 11.0, 'Not supported'
        self.refresh()
        return self.env.exec_workflow(self._name, signal, self.id)

    @property
    def _external_id(self):
        """Retrieve the External ID of the :class:`Record`.

        Return the fully qualified External ID of the :class:`Record`,
        with default value False if there's none.  If multiple IDs
        exist, only one of them is returned (randomly).
        """
        xml_ids = self._model._get_external_ids([self.id])
        return list(xml_ids)[0] if xml_ids else False

    def _set_external_id(self, xml_id):
        """Set the External ID of this record."""
        (mod, name) = xml_id.split('.')
        domain = ['|', '&', ('module', '=', mod), ('name', '=', name),
                  '&', ('model', '=', self._name), ('res_id', '=', self.id)]
        if self.env['ir.model.data'].search(domain):
            raise ValueError(f'ID {xml_id!r} collides with another entry')
        values = {'model': self._name, 'res_id': self.id, 'module': mod, 'name': name}
        self.env['ir.model.data'].create(values)

    def __getattr__(self, attr):
        if attr in self._model._keys:
            return self.read(attr)
        if attr == '_Record__name':
            return self._get_name()
        if attr.startswith('_'):
            raise AttributeError(f"'Record' object has no attribute {attr!r}")

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute(%r, %r, %d, *params, **kwargs)."""
            res = self._execute(attr, [self.id], *params, **kwargs)
            self.refresh()
            if isinstance(res, list) and len(res) == 1:
                return res[0]
            return res
        return _memoize(self, attr, wrapper, (self._name, attr, self.id))

    def __setattr__(self, attr, value):
        if attr == '_external_id':
            return self._set_external_id(value)
        if attr not in self._model._keys:
            raise AttributeError(f"'Record' object has no attribute {attr!r}")
        if attr == 'id':
            raise AttributeError("'Record' object attribute 'id' is read-only")
        self.write({attr: value})


def _interact(global_vars, use_pprint=True, usage=USAGE):
    import builtins
    import code
    import pprint

    if use_pprint:
        def displayhook(value, _printer=pprint.pprint, _builtins=builtins):
            # Pretty-format the output
            if value is not None:
                _printer(value)
                _builtins._ = value
        sys.displayhook = displayhook

    def excepthook(exc_type, exc, tb):
        # Print readable 'Fault' errors
        msg = ''.join(format_exception(exc_type, exc, tb, chain=False))
        print(msg.strip())
    sys.excepthook = excepthook

    class Usage:
        def __call__(self):
            print(usage)
        __repr__ = lambda s: usage
    builtins.usage = Usage()

    try:
        import readline as rl
        import rlcompleter
        rl.parse_and_bind('tab: complete')
        # IOError if file missing, or broken Apple readline
        rl.read_history_file(HIST_FILE)
    except Exception:
        pass
    else:
        if rl.get_history_length() < 0:
            rl.set_history_length(int(os.getenv('HISTSIZE', 500)))
        # better append instead of replace?
        atexit.register(rl.write_history_file, HIST_FILE)

    # Key UP to avoid an empty line
    code.InteractiveConsole(global_vars).interact('\033[A', '')


def main(interact=_interact):
    description = ('Inspect data on Odoo objects.  Use interactively '
                   'or query a model (-m) and pass search terms or '
                   'ids as positional parameters after the options.')
    parser = optparse.OptionParser(
        usage='%prog [options] [search_term_or_id [search_term_or_id ...]]',
        version=__version__,
        description=description)
    parser.add_option(
        '-l', '--list', action='store_true', dest='list_env',
        help='list sections of the configuration')
    parser.add_option(
        '--env',
        help='read connection settings from the given section')
    parser.add_option(
        '-c', '--config', default=None,
        help=f'specify alternate config file (default: {CONF_FILE})')
    parser.add_option(
        '--server', default=None,
        help=f'full URL of the server (default: {DEFAULT_URL})')
    parser.add_option('-d', '--db', default=None, help='database')
    parser.add_option('-u', '--user', default=None, help='username')
    parser.add_option(
        '-p', '--password', default=None,
        help='password, or it will be requested on login')
    parser.add_option(
        '--api-key', dest='api_key', default=None,
        help='API Key for JSON2 or JSON-RPC/XML-RPC')
    parser.add_option(
        '-m', '--model',
        help='the type of object to find')
    parser.add_option(
        '-f', '--fields', action='append',
        help='restrict the output to certain fields (multiple allowed)')
    parser.add_option(
        '-i', '--interact', action='store_true',
        help='use interactively; default when no model is queried')
    parser.add_option(
        '-v', '--verbose', default=0, action='count',
        help='verbose')

    (args, domain) = parser.parse_args()

    Client._config_file = Path.cwd() / (args.config or CONF_FILE)
    if args.list_env:
        print('Available settings:  ' + ' '.join(read_config()))
        return

    if args.interact or not args.model:
        global_vars = Client._set_interactive()
        print(USAGE)

    if args.env:
        client = Client.from_config(args.env,
                                    user=args.user, verbose=args.verbose)
    else:
        if not args.server:
            args.server = ['-c', args.config] if args.config else DEFAULT_URL
            if domain and not args.model:
                args.server = args.server + domain if args.config else domain
        if not args.user:
            args.user = ADMIN_USER
        client = Client(args.server, args.db, args.user, password=args.password,
                        api_key=args.api_key, verbose=args.verbose)

    if args.model and client.env.uid:
        if not issearchdomain(domain):
            domain = [int(res_id) for res_id in domain]
        data = client.env.execute(args.model, 'read', domain, args.fields)
        if data and not args.fields:
            args.fields = ['id'] + [fld for fld in data[0] if fld != 'id']
        writer = csv.DictWriter(sys.stdout, args.fields or (), "", "ignore",
                                quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(data or ())

    if client._is_interactive():
        if not client.env.uid:
            client.connect()
        return interact(global_vars) if interact else global_vars


if __name__ == '__main__':
    main()
