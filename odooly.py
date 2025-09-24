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
from threading import current_thread
from urllib.request import Request, urlopen
from xmlrpc.client import Fault, ServerProxy, MININT, MAXINT

try:
    import requests
except ImportError:
    requests = None

__version__ = '2.2.0'
__all__ = ['Client', 'Env', 'Service', 'BaseModel', 'Model',
           'BaseRecord', 'Record', 'RecordList',
           'format_exception', 'read_config', 'start_odoo_services']

CONF_FILE = 'odooly.ini'
HIST_FILE = os.path.expanduser('~/.odooly_history')
DEFAULT_URL = 'http://localhost:8069/xmlrpc'
DEFAULT_DB = 'odoo'
DEFAULT_USER = 'admin'
SUPERUSER_ID = 1
MAXCOL = [79, 179, 9999]    # Line length in verbose mode

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
    env.models(name)                # List models matching pattern
    env.modules(name)               # List modules matching pattern
    env.install(module1, module2, ...)
    env.upgrade(module1, module2, ...)
                                    # Install or upgrade the modules
"""

DOMAIN_OPERATORS = frozenset('!|&')
# Supported operators are:
#   =, !=, >, >=, <, <=, like, ilike, in, not like, not ilike, not in,
#   child_of, parent_of, =like, =ilike, =?, any, not any
_term_re = re.compile(
    r'([\w._]+)\s*'   r'(=(?:like|ilike|\?)|[<>]=?|!?=(?!=)'
    r'|\b(?:like|ilike|not like|not ilike|in|not in|any|not any|child_of|parent_of)\b)'
    r'\s*(.*)')
_fields_re = re.compile(r'(?:[^%]|^)%\(([^)]+)\)')

# Published object methods
_methods = {
    'common': ['about', 'login', 'authenticate', 'version'],
    'db': ['create_database', 'duplicate_database', 'db_exist', 'drop', 'dump',
           'restore', 'rename', 'list', 'list_lang', 'list_countries',
           'change_admin_password', 'server_version', 'migrate_databases'],
    'object': ['execute', 'execute_kw'],
}
# New 6.1: (db) create_database db_exist,
#          (common) authenticate version set_loglevel
#          (object) execute_kw,  (report) render_report
# New 7.0: (db) duplicate_database
# New 9.0: (db) list_countries
# No-op:   (common) set_loglevel
# Remove 19.0: (common) version
# replaced by: GET /web/version (or (db) server_version)

_obsolete_methods = {
    'common': [
        'check_connectivity', 'get_available_updates',
        'get_migration_scripts', 'get_os_time', 'get_stats',
        'get_server_environment', 'get_sqlcount',
        'list_http_services', 'login_message',              # < 8.0
        'timezone_get',                                     # < 9.0
    ],
    'db': ['create', 'get_progress'],                       # < 8.0
    'object': ['exec_workflow'],                            # < 11.0
    'report': ['render_report', 'report', 'report_get'],    # < 11.0
    'wizard': ['execute', 'create'],                        # < 7.0
}
_cause_message = ("\nThe above exception was the direct cause "
                  "of the following exception:\n\n")
_pending_state = ('state', 'not in',
                  ['uninstallable', 'uninstalled', 'installed'])
seq_types = (list, tuple)


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
        values = [str(exc) + '\n']
    elif issubclass(exc_type, ServerError):     # JSON-RPC
        server_error = exc.args[0]['data']
    elif (issubclass(exc_type, Fault) and       # XML-RPC
          isinstance(exc.faultCode, str)):
        (message, tb) = (exc.faultCode, exc.faultString)
        exc_name = exc_type.__name__
        warning = message.startswith('warning --')
        if warning:
            message = re.sub(r'\((.*), None\)$',
                             lambda m: literal_eval(m.group(1)),
                             message.split(None, 2)[2])
        else:       # ValidationError, DatabaseExists, etc ...
            parts = message.rsplit('\n', 1)
            if parts[-1] == 'None':
                warning, message = True, parts[0]
            last_line = tb.rstrip().rsplit('\n', 1)[-1]
            if last_line.startswith('odoo.'):
                warning, exc_name = True, last_line.split(':', 1)[0]
        server_error = {
            'exception_type': 'warning' if warning else 'internal_error',
            'name': exc_name,
            'arguments': (message,),
            'debug': tb,
        }
    if server_error:
        # Format readable XML-RPC and JSON-RPC errors
        try:
            message = str(server_error['arguments'][0])
        except Exception:
            message = str(server_error['arguments'])
        fault = '%s: %s' % (server_error['name'], message)
        exc_type = server_error.get('exception_type', 'internal_error')
        if exc_type != 'internal_error' or message.startswith('FATAL:'):
            server_tb = None
        else:
            server_tb = server_error['debug']
        if chain:
            values = [server_tb or fault, _cause_message] + values
            values[-1] = fault
        else:
            values = [server_tb or fault]
    return values


def read_config(section=None):
    """Read the environment settings from the configuration file.

    The config file ``odooly.ini`` contains a `section` for each environment.
    Each section provides parameters for the connection: ``host``, ``port``,
    ``database``, ``username`` and (optional) ``password``.  Default values
    are read from the ``[DEFAULT]`` section.  If the ``password`` is not in
    the configuration file, it is requested on login.
    Return a tuple ``(server, db, user, password or None)``.
    Without argument, it returns the list of configured environments.
    """
    p = ConfigParser()
    with open(Client._config_file) as f:
        p.read_file(f)
    if section is None:
        return p.sections()
    env = dict(p.items(section))
    scheme = env.get('scheme', 'http')
    if scheme == 'local':
        server = shlex.split(env.get('options', ''))
    else:
        protocol = env.get('protocol', 'xmlrpc')
        server = '%s://%s:%s/%s' % (scheme, env['host'], env['port'], protocol)
    return (server, env['database'], env['username'], env.get('password'))


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
                raise ValueError('Cannot parse term %r' % term)
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


if os.getenv('ODOOLY_SSL_UNVERIFIED'):
    import ssl

    def urlopen(url, _urlopen=urlopen):
        return _urlopen(url, context=ssl._create_unverified_context())

    def ServerProxy(url, transport, allow_none, _ServerProxy=ServerProxy):
        return _ServerProxy(url, transport=transport, allow_none=allow_none,
                            context=ssl._create_unverified_context())
    requests = False

if requests:
    def http_post(url, data, headers={'Content-Type': 'application/json'}):
        resp = requests.post(url, data=data, headers=headers)
        return resp.json()
else:
    def http_post(url, data, headers={'Content-Type': 'application/json'}):
        request = Request(url, data=data, headers=headers)
        resp = urlopen(request)
        return json.load(resp)


def dispatch_jsonrpc(url, service_name, method, args):
    data = {
        'jsonrpc': '2.0',
        'method': 'call',
        'params': {'service': service_name, 'method': method, 'args': args},
        'id': '%04x%010x' % (os.getpid(), (int(time.time() * 1E6) % 2**40)),
    }
    resp = http_post(url, json.dumps(data).encode('ascii'))
    if resp.get('error'):
        raise ServerError(resp['error'])
    return resp.get('result')


class partial(functools.partial):
    __slots__ = ()

    def __repr__(self):
        # Hide arguments
        return '%s(%r, ...)' % (self.__class__.__name__, self.func)


class Error(Exception):
    """An Odooly error."""


class ServerError(Exception):
    """An error received from the server."""


class Service(object):
    """A wrapper around XML-RPC endpoints.

    The connected endpoints are exposed on the Client instance.
    The `server` argument is the URL of the server (scheme+host+port).
    If `server` is an ``odoo`` Python package, it is used to connect to the
    local server.  The `endpoint` argument is the name of the service
    (examples: ``"object"``, ``"db"``).  The `methods` is the list of methods
    which should be exposed on this endpoint.  Use ``dir(...)`` on the
    instance to list them.
    """
    _methods = ()

    def __init__(self, client, endpoint, methods, verbose=False):
        self._dispatch = client._proxy(endpoint)
        self._rpcpath = client._server
        self._endpoint = endpoint
        self._methods = methods
        self._verbose = verbose

    def __repr__(self):
        return "<Service '%s|%s'>" % (self._rpcpath, self._endpoint)
    __str__ = __repr__

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        if name not in self._methods:
            raise AttributeError("'Service' object has no attribute %r" % name)
        if self._verbose:
            def sanitize(args):
                if self._endpoint != 'db' and len(args) > 2:
                    args = list(args)
                    args[2] = '*'
                return args
            maxcol = MAXCOL[min(len(MAXCOL), self._verbose) - 1]

            def wrapper(self, *args):
                snt = ', '.join([repr(arg) for arg in sanitize(args)])
                snt = '%s.%s(%s)' % (self._endpoint, name, snt)
                if len(snt) > maxcol:
                    suffix = '... L=%s' % len(snt)
                    snt = snt[:maxcol - len(suffix)] + suffix
                print('--> ' + snt)
                res = self._dispatch(name, args)
                rcv = str(res)
                if len(rcv) > maxcol:
                    suffix = '... L=%s' % len(rcv)
                    rcv = rcv[:maxcol - len(suffix)] + suffix
                print('<-- ' + rcv)
                return res
        else:
            wrapper = lambda s, *args: s._dispatch(name, args)
        return _memoize(self, name, wrapper)


class Env(object):
    """An environment wraps data for Odoo models and records:

        - :attr:`db_name`, the current database;
        - :attr:`uid`, the current user id;
        - :attr:`context`, the current context dictionary.

        To retrieve an instance of ``some.model``:

        >>> env["some.model"]
    """

    name = uid = user = None
    _cache = {}

    def __new__(cls, client, db_name=()):
        if not db_name or client.env.db_name:
            env = object.__new__(cls)
            env.client, env.db_name, env.context = client, db_name, {}
        else:
            env, env.db_name = client.env, db_name
        if db_name:
            env._model_names = env._cache_get('model_names', set)
            env._models = {}
        return env

    def __contains__(self, name):
        """Test wether the given model exists."""
        return name in self._model_names or name in self.models(name)

    def __getitem__(self, name):
        """Return the given :class:`Model`."""
        return self._get(name)

    def __iter__(self):
        """Return an iterator on model names."""
        return iter(self.models())

    def __len__(self):
        """Return the size of the model registry."""
        return len(self.models())

    def __bool__(self):
        return True
    __nonzero__ = __bool__

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    def __repr__(self):
        return "<Env '%s@%s'>" % (self.user.login if self.uid else '',
                                  self.db_name)

    def check_uid(self, uid, password):
        """Check if ``(uid, password)`` is valid.

        Return ``uid`` on success, ``False`` on failure.
        The invalid entry is removed from the authentication cache.
        """
        try:
            self.client._object.execute_kw(self.db_name, uid, password,
                                           'ir.model', 'fields_get', ([None],))
        except Exception:
            auth_cache = self._cache_get('auth')
            if uid in auth_cache:
                del auth_cache[uid]
            uid = False
        return uid

    def _auth(self, user, password):
        assert self.db_name, 'Not connected'
        uid = verified = None
        if isinstance(user, int):
            (user, uid) = (uid, user)
        auth_cache = self._cache_get('auth', dict)
        if not password:
            # Read from cache
            (uid, password) = auth_cache.get(user or uid) or (uid, None)
            # Read from model 'res.users'
            if not password and self.access('res.users', 'write'):
                domain = [('login', '=', user)] if user else [uid]
                obj = self['res.users'].read(domain, 'id login password')
                if obj:
                    uid = obj[0]['id']
                    user = obj[0]['login']
                    password = obj[0]['password']
                else:
                    # Invalid user
                    uid = False
            verified = password and uid
            # Ask for password
            if not password and uid is not False:
                from getpass import getpass
                if user is None:
                    name = 'admin' if uid == SUPERUSER_ID else ('UID %d' % uid)
                else:
                    name = user
                password = getpass('Password for %r: ' % name)
        # Check if password is valid
        uid = self.check_uid(uid, password) if (uid and not verified) else uid
        if uid is None:
            # Do a standard 'login'
            try:
                uid = self.client.common.login(self.db_name, user, password)
            except Exception as exc:
                if 'does not exist' in str(exc):    # Heuristic
                    raise Error('Database does not exist')
                raise
        if not uid:
            raise Error('Invalid username or password')
        # Update the cache
        auth_cache[uid] = (uid, password)
        if user:
            auth_cache[user] = auth_cache[uid]
        return (uid, password)

    def _set_credentials(self, uid, password):
        def env_auth(method):     # Authenticated endpoints
            return partial(method, self.db_name, uid, password)
        self._execute = env_auth(self.client._object.execute)
        self._execute_kw = env_auth(self.client._object.execute_kw)
        if self.client._report:   # Odoo <= 10
            self.exec_workflow = env_auth(self.client._object.exec_workflow)
            self.report = env_auth(self.client._report.report)
            self.report_get = env_auth(self.client._report.report_get)
            self.render_report = env_auth(self.client._report.render_report)
        if self.client._wizard:   # OpenERP 6.1
            self.wizard_execute = env_auth(self.client._wizard.execute)
            self.wizard_create = env_auth(self.client._wizard.create)

    def _configure(self, uid, user, password, context):
        if self.uid:              # Create a new Env() instance
            env = Env(self.client)
            (env.db_name, env.name) = (self.db_name, self.name)
            env.context = dict(context)
            env._model_names = self._model_names
            env._models = {}
        else:                     # Configure the Env() instance
            env = self
        if uid == self.uid:       # Copy methods
            for key in ('_execute', '_execute_kw', 'exec_workflow',
                        'report', 'report_get', 'render_report',
                        'wizard_execute', 'wizard_create'):
                if hasattr(self, key):
                    setattr(env, key, getattr(self, key))
        else:                     # Create methods
            env._set_credentials(uid, password)
        # Setup uid and user
        if isinstance(user, int):
            user = 'admin' if uid == SUPERUSER_ID else None
        elif isinstance(user, Record):
            user = user.login
        env.uid = uid
        env.user = env._get('res.users', False).browse(uid)
        if user:
            assert isinstance(user, str), repr(user)
            env.user.__dict__['login'] = user
            env.user._cached_keys.add('login')
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

    def __call__(self, user=None, password=None, context=None):
        """Return an environment based on ``self`` with modified parameters."""
        if user is not None:
            (uid, password), context = self._auth(user, password), {}
        elif context is not None:
            (uid, user) = (self.uid, self.user)
        else:
            return self
        env_key = json.dumps((uid, context), sort_keys=True)
        env = self._cache_get(env_key)
        if env is None:
            env = self._configure(uid, user, password, context)
            self._cache_set(env_key, env)
        return env

    def sudo(self, user=SUPERUSER_ID):
        """Attach to the provided user, or SUPERUSER."""
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

    def execute(self, obj, method, *params, **kwargs):
        """Wrapper around ``object.execute_kw`` RPC method.

        Argument `method` is the name of an ``osv.osv`` method or
        a method available on this `obj`.
        Method `params` are allowed.  If needed, keyword
        arguments are collected in `kwargs`.
        """
        assert self.uid, 'Not connected'
        assert isinstance(obj, str)
        assert isinstance(method, str) and method != 'browse'
        ordered = single_id = False
        if method == 'read':
            assert params, 'Missing parameter'
            if not isinstance(params[0], list):
                single_id = True
                ids = [params[0]] if params[0] else False
            elif params[0] and issearchdomain(params[0]):
                # Combine search+read
                search_params = searchargs(params[:1], kwargs)
                ordered = len(search_params) > 3 and search_params[3]
                kw = ({'context': self.context},) if self.context else ()
                ids = self._execute_kw(obj, 'search', search_params, *kw)
            else:
                ordered = kwargs.pop('order', False) and params[0]
                ids = set(params[0]) - {False}
                if not ids and ordered:
                    return [False] * len(ordered)
                ids = sorted(ids)
            if not ids:
                return ids
            params = (ids,) + params[1:]
        elif method == 'search':
            # Accept keyword arguments for the search method
            params = searchargs(params, kwargs)
        elif method == 'search_count':
            params = searchargs(params)
        kw = ((dict(kwargs, context=self.context),)
              if self.context else (kwargs and (kwargs,) or ()))
        res = self._execute_kw(obj, method, params, *kw)
        if ordered:
            # The results are not in the same order as the ids
            # when received from the server
            resdic = {val['id']: val for val in res}
            if not isinstance(ordered, list):
                ordered = ids
            res = [resdic.get(id_, False) for id_ in ordered]
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
            self._models[name] = m = Model._new(self, name)
        return m

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
            errmsg = 'Model not found: %s' % (name,)
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

    def _upgrade(self, modules, button):
        # First, update the list of modules
        ir_module = self._get('ir.module.module', False)
        updated, added = ir_module.update_list()
        if added:
            print('%s module(s) added to the list' % added)
        # Find modules
        sel = modules and ir_module.search([('name', 'in', modules)])
        mods = ir_module.read([_pending_state], 'name state')
        if sel:
            # Safety check
            if any(mod['name'] not in modules for mod in mods):
                raise Error('Pending actions:\n' + '\n'.join(
                    ('  %(state)s\t%(name)s' % mod) for mod in mods))
            if button == 'button_uninstall':
                # Safety check
                names = ir_module.read([('id', 'in', sel.ids),
                                        'state != installed',
                                        'state != to upgrade',
                                        'state != to remove'], 'name')
                if names:
                    raise Error('Not installed: %s' % ', '.join(names))
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
                raise Error('Module(s) not found: %s' % ', '.join(modules))
            print('%s module(s) updated' % updated)
            return
        print('%s module(s) selected' % len(sel))
        print('%s module(s) to process:' % len(mods))
        for mod in mods:
            print('  %(state)s\t%(name)s' % mod)

        # Empty the cache for this database
        self.refresh()

        if button == 'cancel':
            # Reset module state
            installed = [mod['id'] for mod in mods if mod['state'] != 'to install']
            uninstalled = [mod['id'] for mod in mods if mod['state'] == 'to install']
            if uninstalled:
                self.execute('ir.module.module', 'button_install_cancel', uninstalled)
            if installed:
                self.execute('ir.module.module', 'button_upgrade_cancel', installed)
        else:
            # Apply scheduled upgrades
            self.execute('base.module.upgrade', 'upgrade_module', [])

    def upgrade(self, *modules):
        """Press the button ``Upgrade``."""
        return self._upgrade(modules, button='button_upgrade')

    def install(self, *modules):
        """Press the button ``Install``."""
        return self._upgrade(modules, button='button_install')

    def uninstall(self, *modules):
        """Press the button ``Uninstall``."""
        return self._upgrade(modules, button='button_uninstall')

    def upgrade_cancel(self, *modules):
        """Press the button ``Cancel Upgrade/Install/Uninstall``."""
        return self._upgrade(modules, button='cancel')


class Client(object):
    """Connection to an Odoo instance.

    This is the top level object.
    The `server` is the URL of the instance, like ``http://localhost:8069``.
    If `server` is an ``odoo``/``openerp`` Python package, it is used to
    connect to the local server.

    The `db` is the name of the database and the `user` should exist in the
    table ``res.users``.  If the `password` is not provided, it will be
    asked on login.
    """
    _config_file = os.path.join(os.curdir, CONF_FILE)
    _globals = None

    def __init__(self, server, db=None, user=None, password=None,
                 transport=None, verbose=False):
        self._connections = []
        self._set_services(server, transport, verbose)
        self.env = Env(self)
        if db:    # Try to login
            self.login(user, password=password, database=db)

    def _set_services(self, server, transport, verbose):
        if isinstance(server, list):
            appname = os.path.basename(__file__).rstrip('co')
            server = start_odoo_services(server, appname=appname)
        elif isinstance(server, str) and server[-1:] == '/':
            server = server.rstrip('/')
        self._server = server

        if not isinstance(server, str):
            assert not transport, 'Not supported'
            api_v7 = server.release.version_info < (8,)
            self._proxy = self._proxy_v7 if api_v7 else self._proxy_dispatch
        elif '/jsonrpc' in server:
            assert not transport, 'Not supported'
            self._proxy = self._proxy_jsonrpc
        else:
            if '/xmlrpc' not in server:
                self._server = server + '/xmlrpc'
            self._proxy = self._proxy_xmlrpc
            self._transport = transport

        def get_service(name):
            methods = list(_methods[name]) if (name in _methods) else []
            if float_version < 11.0:
                methods += _obsolete_methods.get(name) or ()
            return Service(self, name, methods, verbose=verbose)

        float_version = 99.0
        self.server_version = ver = get_service('db').server_version()
        self.major_version = re.search(r'\d+\.?\d*', ver).group()
        self.version_info = float_version = float(self.major_version)
        assert float_version > 6.0, 'Not supported: %s' % ver
        # Create the RPC services
        self.db = get_service('db')
        self.common = get_service('common')
        self._object = get_service('object')
        self._report = get_service('report') if float_version < 11.0 else None
        self._wizard = get_service('wizard') if float_version < 7.0 else None

    def _proxy_dispatch(self, name):
        return partial(self._server.http.dispatch_rpc, name)

    def _proxy_v7(self, name):
        return self._server.netsvc.ExportService.getService(name).dispatch

    def _proxy_xmlrpc(self, name):
        proxy = ServerProxy(self._server + '/' + name,
                            transport=self._transport, allow_none=True)
        self._connections.append(proxy)
        return proxy._ServerProxy__request

    def _proxy_jsonrpc(self, name):
        return partial(dispatch_jsonrpc, self._server, name)

    @classmethod
    def from_config(cls, environment, user=None, verbose=False):
        """Create a connection to a defined environment.

        Read the settings from the section ``[environment]`` in the
        ``odooly.ini`` file and return a connected :class:`Client`.
        See :func:`read_config` for details of the configuration file format.
        """
        (server, db, conf_user, password) = read_config(environment)
        if user and user != conf_user:
            password = None
        client = cls(server, verbose=verbose)
        client.env.name = environment
        client.login(user or conf_user, password=password, database=db)
        return client

    def __repr__(self):
        return "<Client '%s#%s'>" % (self._server, self.env.db_name)

    def close(self):
        for conn in self._connections:
            conn.__exit__()
        self._connections = []

    def _login(self, user, password=None, database=None):
        """Switch `user` and (optionally) `database`.

        If the `password` is not available, it will be asked.
        """
        env = self.env
        if database:
            try:
                dbs = self.db.list()
            except Exception:
                pass    # AccessDenied: simply ignore this check
            else:
                if database not in dbs:
                    raise Error("Database '%s' does not exist: %s" %
                                (database, dbs))
            if env.db_name != database:
                env = Env(self, database)
            # Used for logging, copied from odoo.sql_db.db_connect
            current_thread().dbname = database
        elif not env.db_name:
            raise Error('Not connected')
        try:
            env = env(user=user, password=password)
        except Exception:
            current_thread().dbname = self.env.db_name
            raise
        self.env = env(context=env['res.users'].context_get())
        return env.uid

    def login(self, user, password=None, database=None):
        """Switch `user` and (optionally) `database`."""
        if not self._globals:   # Not interactive
            return self._login(user, password=password, database=database)
        try:
            self._login(user, password=password, database=database)
        except Error as exc:
            print('%s: %s' % (exc.__class__.__name__, exc))
        else:
            # Register the new globals()
            self.connect()

    def connect(self, env_name=None):
        """Connect to another environment and replace the globals()."""
        assert self._globals, 'Not available'
        if env_name:
            self.from_config(env_name, verbose=self.db._verbose)
            return
        client = self
        env_name = client.env.name or client.env.db_name
        self._globals['client'] = client
        self._globals['env'] = client.env
        self._globals['self'] = client.env.user if client.env.uid else None
        # Tweak prompt
        sys.ps1 = '%s >>> ' % (env_name,)
        sys.ps2 = '... '.rjust(len(sys.ps1))
        # Logged in?
        if client.env.uid:
            print('Logged in as %r' % (client.env.user.login,))

    @classmethod
    def _set_interactive(cls, global_vars={}):
        # Don't call multiple times
        del Client._set_interactive
        assert cls._globals is None

        for name in ['__name__', '__version__', '__doc__', 'Client']:
            global_vars[name] = globals()[name]
        cls._globals = global_vars
        return global_vars

    def create_database(self, passwd, database, demo=False, lang='en_US',
                        user_password='admin', login='admin',
                        country_code=None):
        """Create a new database.

        The superadmin `passwd` and the `database` name are mandatory.
        By default, `demo` data are not loaded, `lang` is ``en_US``
        and no country is set into the database.
        Login if successful.
        """
        if login == 'admin' and not country_code:
            self.db.create_database(passwd, database, demo, lang,
                                    user_password)
        elif self.version_info < 9.0:
            raise Error("Custom 'login' and 'country_code' are not supported")
        else:
            self.db.create_database(passwd, database, demo, lang,
                                    user_password, login, country_code)
        return self.login(login, user_password, database=database)

    def clone_database(self, passwd, database):
        """Clone the current database.

        The superadmin `passwd` and `database` are mandatory.
        Login if successful.

        Supported since OpenERP 7.
        """
        self.db.duplicate_database(passwd, self.env.db_name, database)
        # Copy the cache for authentication
        auth_cache = self.env._cache_get('auth')
        self.env._cache_set('auth', dict(auth_cache), db_name=database)

        # Login with the current user into the new database
        (uid, password) = self.env._auth(self.env.uid, None)
        return self.login(self.env.user.login, password, database=database)


class BaseModel(object):

    ids = ()

    def with_env(self, env):
        """Attach to the provided environment."""
        return env[self._name]

    def sudo(self, user=SUPERUSER_ID):
        """Attach to the provided user, or SUPERUSER."""
        return self.with_env(self.env(user=user))

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
        return "<Model '%s'>" % (self._name,)

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
            assert rec._model is self, 'Model mismatch %r %r' % (rec, self)
            return rec
        assert issearchdomain(domain)       # a search domain
        ids = self._execute('search', domain)
        if len(ids) > 1:
            raise ValueError('domain matches too many records (%d)' % len(ids))
        return Record(self, ids[0]) if ids else None

    def create(self, values):
        """Create one or many :class:`Record`(s).

        The argument `values` is a dictionary of values which are used to
        create the record.  Relationship fields `one2many` and `many2many`
        accept either a list of ids or a RecordList or the extended Odoo
        syntax.  Relationship fields `many2one` and `reference` accept
        either a Record or the Odoo syntax.
        Since Odoo 12.0, it can create multiple records.

        The newly created :class:`Record` is returned (or :class:`RecordList`).
        """
        if hasattr(values, "items"):
            values = self._unbrowse_values(values)
        else:  # Odoo >= 12.0
            values = [self._unbrowse_values(vals) for vals in values]
        new_ids = self._execute('create', values)
        return Record(self, new_ids)

    def read(self, *params, **kwargs):
        """Wrapper for ``client.execute(model, 'read', [...], ('a', 'b'))``.

        The first argument is a list of ids ``[1, 3]`` or a single id ``42``.

        The second argument, `fields`, accepts:
         - a single field: ``'first_name'``
         - a tuple of fields: ``('street', 'city')``
         - a space separated string: ``'street city'``
         - a format spec: ``'%(street)s %(city)s'``

        If `fields` is omitted, all fields are read.

        If `domain` is a single id, then:
         - return a single value if a single field is requested.
         - return a string if a format spec is passed in the `fields` argument.
         - else, return a dictionary.

        If `domain` is not a single id, the returned value is a list of items.
        Each item complies with the rules of the previous paragraph.

        The optional keyword arguments `offset`, `limit` and `order` are
        used to restrict the search.  The `order` is also used to order the
        results returned.  Note: the low-level RPC method ``read`` itself does
        not preserve the order of the results.
        """
        fmt = None
        if len(params) > 1 and isinstance(params[1], str):
            fmt = ('%(' in params[1]) and params[1]
            if fmt:
                fields = _fields_re.findall(fmt)
            else:
                # transform: "zip city" --> ("zip", "city")
                fields = params[1].split()
                if len(fields) == 1:
                    fmt = ()    # marker
            params = (params[0], fields) + params[2:]
        res = self._execute('read', *params, **kwargs)
        if not res:
            return res
        if fmt:
            if isinstance(res, list):
                return [(d and fmt % d) for d in res]
            return fmt % res
        if fmt == ():
            if isinstance(res, list):
                return [(d and d[fields[0]]) for d in res]
            return res[fields[0]]
        return res

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
                    new_values[key] = '%s,%s' % (value._name, value.id)
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
            res['%(module)s.%(name)s' % rec] = self.get(rec['res_id'])
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
            raise AttributeError("'Model' object has no attribute %r" % attr)

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
                if isinstance(id_, seq_types):
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
                attrs['_Record__name'] = name
        # Bypass the __setattr__ method
        inst.__dict__.update(attrs)
        return inst

    def __repr__(self):
        if len(self.ids) > 16:
            ids = 'length=%d' % len(self.ids)
        else:
            ids = self.id
        return "<%s '%s,%s'>" % (self.__class__.__name__,
                                 self._name, ids)

    def __dir__(self):
        attrs = set(self.__dict__) | set(self._model._keys)
        return sorted(attrs)

    def __bool__(self):
        return bool(self.ids)
    __nonzero__ = __bool__

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
            self._check_model(item, 'contains')
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
        raise ValueError("Expected singleton: %s" % self)

    def exists(self):
        """Return a subset of records that exist."""
        ids = self.ids and self._execute('exists', self.union().ids)
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
                id_, name = idn if isinstance(idn, seq_types) else (idn, None)
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
        """Wrapper for :meth:`Record.read` method."""
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
        """Copy records and return :class:`RecordList`.  Odoo >= 18.0

        The optional argument `default` is a mapping which overrides some
        values of the new records.
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
            errmsg = "'RecordList' object has no attribute %r" % attr
            raise AttributeError(errmsg)

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute(%r, %r, [...], *params, **kwargs)."""
            return self._execute(attr, self.id, *params, **kwargs)
        return _memoize(self, attr, wrapper, (self._name, attr))

    def __setattr__(self, attr, value):
        if attr in self._model._keys or attr == 'id':
            msg = "attribute %r is read-only; use 'RecordList.write' instead."
        else:
            msg = "has no attribute %r"
        raise AttributeError("'RecordList' object %s" % msg % attr)

    def __eq__(self, other):
        return (isinstance(other, RecordList) and
                self.id == other.id and self._model is other._model)


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
        return self.__name

    def _get_name(self):
        try:
            (id_name,) = self._execute('name_get', [self.id])
            name = '%s' % (id_name[1],)
        except Exception:
            name = '%s,%d' % (self._name, self.id)
        self.__dict__['_idnames'] = [(self.id, name)]
        return _memoize(self, '_Record__name', name)

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
        elif isinstance(fields, str) and '%(' not in fields:
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
            raise ValueError('ID %r collides with another entry' % xml_id)
        self.env['ir.model.data'].create({
            'model': self._name,
            'res_id': self.id,
            'module': mod,
            'name': name,
        })

    def __getattr__(self, attr):
        if attr in self._model._keys:
            return self.read(attr)
        if attr == '_Record__name':
            return self._get_name()
        if attr.startswith('_'):
            raise AttributeError("'Record' object has no attribute %r" % attr)

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
            raise AttributeError("'Record' object has no attribute %r" % attr)
        if attr == 'id':
            raise AttributeError("'Record' object attribute 'id' is read-only")
        self.write({attr: value})

    def __eq__(self, other):
        return (isinstance(other, Record) and
                self.id == other.id and self._model is other._model)


def _interact(global_vars, use_pprint=True, usage=USAGE):
    import builtins
    import code
    import pprint

    if use_pprint:
        def displayhook(value, _printer=pprint.pprint, _builtins=builtins):
            # Pretty-format the output
            if value is None:
                return
            _printer(value)
            _builtins._ = value
        sys.displayhook = displayhook

    class Usage(object):
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

    class Console(code.InteractiveConsole):
        def runcode(self, code):
            try:
                exec(code, global_vars)
            except SystemExit:
                raise
            except:
                # Print readable 'Fault' errors
                # Work around http://bugs.python.org/issue12643
                (exc_type, exc, tb) = sys.exc_info()
                msg = ''.join(format_exception(exc_type, exc, tb, chain=False))
                print(msg.strip())

    # Key UP to avoid an empty line
    Console().interact('\033[A')


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
        help='specify alternate config file (default: %r)' % CONF_FILE)
    parser.add_option(
        '--server', default=None,
        help='full URL of the server (default: %s)' % DEFAULT_URL)
    parser.add_option('-d', '--db', default=DEFAULT_DB, help='database')
    parser.add_option('-u', '--user', default=None, help='username')
    parser.add_option(
        '-p', '--password', default=None,
        help='password, or it will be requested on login')
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

    Client._config_file = os.path.join(os.getcwd(), args.config or CONF_FILE)
    if args.list_env:
        print('Available settings:  ' + ' '.join(read_config()))
        return

    if (args.interact or not args.model):
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
            args.user = DEFAULT_USER
        client = Client(args.server, args.db, args.user, args.password,
                        verbose=args.verbose)

    if args.model and client.env.uid:
        ids = client.env.execute(args.model, 'search', domain)
        data = client.env.execute(args.model, 'read', ids, args.fields)
        if not args.fields:
            args.fields = ['id']
            if data:
                args.fields.extend([fld for fld in data[0] if fld != 'id'])
        writer = csv.DictWriter(sys.stdout, args.fields, "", "ignore",
                                quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(data or ())

    if client._globals is not None:   # Interactive mode
        if not client.env.uid:
            client.connect()
        return interact(global_vars) if interact else global_vars


if __name__ == '__main__':
    main()
