"""A fake Odoo server, which answers the HTTP requests of odooly by path.

It covers the Web API (Webclient), JSON-2, the documentation endpoints and
JSON-RPC.  The same services are used for the local mode, through a fake
``odoo`` package.  The behaviour depends on the Odoo version.
"""
import io
import itertools
import json as _json
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from odooly import ServerError

MASTER_PWD = 'master'
TOTP_FORM = '<input name="totp_token"/>'
SYSTEM_USER = '__system__'


def odoo_error(name, message, code=200):
    """Return the 'error' member of a JSON-RPC response, as sent by Odoo."""
    return {'code': code, 'message': 'Odoo Server Error',
            'data': {'name': name, 'debug': f'Traceback ...\n{name}: {message}\n',
                     'message': message, 'arguments': [message], 'context': {}}}


ACCESS_DENIED = odoo_error('odoo.exceptions.AccessDenied', 'Access Denied')
ACCESS_ERROR = odoo_error('odoo.exceptions.AccessError', 'You are not allowed to access this')
PDF = b'%PDF-1.4 fake'
SESSION_EXPIRED = odoo_error('odoo.http.SessionExpiredException', 'Session expired', code=100)


class OdooException(Exception):
    """Raised by a service: converted to an error response."""

    def __init__(self, error):
        super().__init__(error['data']['message'])
        self.error = error


def http_error(code, message):
    """HTTP error, as raised by odooly.http.HTTPSession.request."""
    return ServerError({'code': code, 'data': {
        'name': 'HTTPError', 'debug': None, 'arguments': (f'{code} - {message}',)}})


class FakeUser(SimpleNamespace):
    """A user: uid, login, password, api_key, totp, is_system, context."""

    def __init__(self, uid, login, password=None, api_key=None, totp=None,
                 is_system=False, context=None):
        super().__init__(uid=uid, login=login, password=password, api_key=api_key, totp=totp,
                         is_system=is_system,
                         context=context or {'lang': 'en_US', 'tz': 'Europe/Zurich'})


class FakeOdoo:
    """A fake Odoo server.

    Use :meth:`patch` to answer the requests of ``odooly.http.HTTPSession``.
    The requests are recorded in :attr:`requests` as ``(path, session_id)``.
    """
    server = 'http://192.0.2.199:9999'
    csrf_token = 'csrf0123'

    def __init__(self, version='19.0', databases=('database',), users=None, list_db=True):
        self.version = version
        self.version_info = tuple(int(n) for n in version.split('.')[:2])
        self.databases = [*databases]
        self.list_db = list_db
        self.users = {u.login: u for u in users or [
            FakeUser(2, 'admin', 'admin', is_system=True),
            FakeUser(6, 'demo', 'demo'),
        ]}
        self.sessions = {}
        self.session_names = {}  # Optional: {login: session_id}
        self.requests = []
        self._sid = itertools.count(1)
        # Model methods: {(model, method): func(user, args, kwargs)}
        self.methods = {}
        # Denied access: {(login, model, mode)}
        self.denied = set()
        report_model = self.report_model()
        self.records = {
            'res.users': {u.uid: {'id': u.uid, 'login': u.login} for u in self.users.values()},
            'res.partner': {1: {'id': 1, 'name': 'My Company'}, 3: {'id': 3, 'name': 'Bob'}},
            report_model: {
                rid: {'id': rid, 'name': name, 'model': 'res.partner', 'report_name': report_name,
                      'report_type': report_type, 'binding_model_id': binding}
                for (rid, name, report_name, report_type, binding) in [
                    # Like 'account.report_invoice[_with_payments]'
                    (1, 'Partner Card', 'base.partner_card', 'qweb-pdf', 85),
                    (2, 'Partner Sheet', 'base.partner_sheet', 'qweb-html', 85),
                    (3, 'Partner Card Logo', 'base.partner_card_logo', 'qweb-pdf', False),
                ]
            },
        }
        if self.version_info < (11,):  # No 'binding_model_id' on 'ir.actions.report.xml'
            for record in self.records[report_model].values():
                del record['binding_model_id']
        # Models: {name: (transient, abstract)}
        self.models = {name: (False, False) for name in [
            'ir.model', 'res.company', 'res.partner', 'res.users', report_model]}
        self.models.update({'base.language.install': (True, False), 'mail.thread': (False, True)})
        self.report_requests = []

    def report_model(self):
        """Odoo 9 and 10: 'ir.actions.report.xml'."""
        return 'ir.actions.report' if self.version_info >= (11,) else 'ir.actions.report.xml'

    # --- Helpers -------------------------------------------------------------

    def patch(self):
        """Patch ``HTTPSession.request``, and return the mock."""
        return mock.patch('odooly.http.HTTPSession.request', autospec=True,
                          side_effect=self.request).start()

    def paths(self):
        return [path for (path, sid) in self.requests]

    def user(self, uid):
        return next((u for u in self.users.values() if u.uid == uid), None)

    def new_session(self, http, url, user, db, mfa=False):
        sid = self.session_names.get(user.login) or f'SID{next(self._sid)}'
        self.sessions[sid] = {'uid': None if mfa else user.uid, 'login': user.login, 'db': db}
        http.set_cookie(url, 'session_id', sid)
        return sid

    def monodb(self, session):
        """The database of the session, or the only database, like ``odoo.http``."""
        if session and session.get('db'):
            return session['db']
        return self.databases[0] if len(self.databases) == 1 else None

    def session_info(self, session):
        user = self.users.get(session['login'])
        if session['uid'] == 1:
            user = FakeUser(1, SYSTEM_USER, is_system=True, context=user.context)
        return {
            'uid': session['uid'], 'username': user.login, 'db': session['db'],
            'user_context': self.context(user, session['uid']),
            'is_system': user.is_system, 'server_version': self.version,
        }

    def context(self, user, uid):
        """The user context: with 'uid' since Odoo 16."""
        return {**user.context, 'uid': uid} if self.version_info >= (16,) else {**user.context}

    def check_login(self, db, login, password):
        user = self.users.get(login)
        if db not in self.databases or not user or user.password != password:
            raise OdooException(ACCESS_DENIED)
        return user

    def call(self, user, model, method, args, kwargs):
        """Execute a model method."""
        if (func := self.methods.get((model, method))) is not None:
            return func(user, args, kwargs)
        if (model, method) == ('res.users', 'context_get'):
            return self.context(user, user.uid)
        if model == 'ir.model':
            return self.call_ir_model(user, method, args)
        if (model, method) == ('ir.server.object.lines', 'fields_get'):
            # Since Odoo 12, the Reference field lists the models (with sudo since 15)
            if self.version_info < (15,) and not user.is_system:
                raise OdooException(ACCESS_ERROR)
            selection = [[name, name] for name in sorted(self.models)]
            return {'resource_ref': {'type': 'reference', 'selection': selection}}
        if (model, method) == ('ir.model.access', 'check'):  # Odoo < 18
            if (user.login, args[0], args[1]) in self.denied:
                raise OdooException(ACCESS_ERROR)
            return True
        if method == 'has_access' and self.version_info >= (18,):
            mode = kwargs.get('operation') or args[1]
            return (user.login, model, mode) not in self.denied
        records = self.records.get(model, {})
        if method == 'fields_get':
            keys = {key for rec in records.values() for key in rec} | {'id', 'display_name'}
            return {key: {'type': 'char', 'string': key} for key in sorted(keys)}
        if method == 'search':
            return self.search(records, args[0] if args else kwargs.get('domain', []))
        if method == 'search_read':
            ids = self.search(records, args[0] if args else kwargs.get('domain', []))
            return [records[i] for i in ids]
        if method == 'search_count':
            return len(self.search(records, args[0] if args else []))
        if method == 'read':
            return [records[i] for i in args[0] if i in records]
        raise OdooException(odoo_error('AttributeError', f'{model}.{method}'))

    def call_ir_model(self, user, method, args):
        """Access to 'ir.model': for admin only, since Odoo 15."""
        if method == 'fields_get':
            keys = ['id', 'display_name', 'model', 'name', 'transient']
            if self.version_info >= (19,):
                keys.append('abstract')
            return {key: {'type': 'char', 'string': key} for key in keys}
        if method == 'get_available_models' and self.version_info >= (16,):
            # Web add-on: valid models for the model selector
            return [{'model': name, 'display_name': name}
                    for (name, (transient, abstract)) in sorted(self.models.items())
                    if not transient and not abstract]
        if method == 'search_read':
            if self.version_info >= (15,) and not user.is_system:
                raise OdooException(ACCESS_ERROR)
            records = {}
            for (idx, (name, (transient, abstract))) in enumerate(sorted(self.models.items())):
                records[idx + 1] = {'id': idx + 1, 'model': name, 'transient': transient}
                if self.version_info >= (19,):
                    records[idx + 1]['abstract'] = abstract
            return [records[i] for i in self.search(records, args[0] if args else [])]
        raise OdooException(odoo_error('AttributeError', f'ir.model.{method}'))

    def search(self, records, domain):
        """Search the records, with a simple domain."""
        fields = {key for rec in records.values() for key in rec}
        result = []
        for (rid, rec) in records.items():
            for (field, op, value) in domain:
                if field not in fields:
                    raise OdooException(odoo_error('ValueError', f'Invalid field {field!r}'))
                if not {
                    '=': lambda v: v == value, '!=': lambda v: v != value,
                    'in': lambda v: v in value, 'like': lambda v: value in str(v),
                }[op](rec.get(field)):
                    break
            else:
                result.append(rid)
        return result

    def model_doc(self, model):
        return {'model': model, 'methods': {'context_get': {'parameters': {}, 'api': ['model']}}}

    # --- Services: common, object, db --------------------------------------

    def rpc(self, service, method, params):
        """The RPC services, for JSON-RPC and for the local mode."""
        if service == 'common':
            if method == 'version':
                return {'server_version': self.version, 'protocol_version': 1}
            if method in ('login', 'authenticate'):
                (db, login, password) = params[:3]
                try:
                    return self.check_login(db, login, password).uid
                except OdooException:
                    return False
        elif service == 'object' and method in ('execute_kw', 'execute'):
            (db, uid, password, model, method, args) = params[:6]
            user = self.user(uid)
            if not (db in self.databases and user and password in {user.password, user.api_key}):
                raise OdooException(ACCESS_DENIED)
            return self.call(user, model, method, args, {**(params[6:] or [{}])[0]})
        elif service == 'db':
            return self.rpc_db(method, params)
        raise OdooException(odoo_error('KeyError', f"Method not found: {service}.{method}"))

    def rpc_db(self, method, params):
        if method == 'list':
            if not self.list_db:
                raise OdooException(ACCESS_DENIED)
            return [*self.databases]
        if params[0] != MASTER_PWD:
            raise OdooException(ACCESS_DENIED)
        # Signatures, with the master password: 'phone' since 12.0,
        # 'neutralize_database' since 16.0
        max_args = {
            'create_database': 7 if self.version_info < (12,) else 8,
            'duplicate_database': 3 if self.version_info < (16,) else 4,
            'drop': 2,
        }
        assert len(params) <= max_args[method], f"Too many arguments: {method}{params}"
        if method == 'create_database':
            self.databases.append(params[1])
        elif method == 'duplicate_database':
            self.databases.append(params[2])
        elif method == 'drop':
            self.databases.remove(params[1])
        return True

    # --- HTTP ----------------------------------------------------------------

    def request(self, http, url, *, method='POST', data=None, json=None, headers=None):
        """Answer the request, like ``HTTPSession.request``."""
        parts = urlsplit(url)
        path = parts.path
        sid = http.get_cookie(url, 'session_id')
        self.requests.append((path + (f'?{parts.query}' if parts.query else ''), sid))
        if method == 'HEAD':
            return mock.Mock(url=url)
        params = (json or {}).get('params', {}) if json and 'jsonrpc' in json else json
        try:
            if path.startswith(('/json/2/', '/doc-bearer/')):
                return self.json2(path, params, headers or {})
            if path == '/jsonrpc':
                return {'result': self.rpc(params['service'], params['method'], params['args'])}
            if method == 'GET' or data is not None:
                return self.http_page(http, url, path, parse_qs(parts.query), data or {}, sid)
            return {'result': self.web(http, url, path, params or {}, sid)}
        except OdooException as exc:
            if path.startswith('/json/2/'):
                raise http_error(401 if 'AccessDenied' in exc.error['data']['name'] else 422,
                                 exc.error['data']['message'])
            return {'error': exc.error}

    def web(self, http, url, path, params, sid):
        """JSON-RPC routes of the Web API."""
        session = self.sessions.get(sid)
        if path == '/web/webclient/version_info':
            return {'server_version': self.version,
                    'server_version_info': [*self.version_info, 0, 'final', 0, ''],
                    'server_serie': self.version, 'protocol_version': 1}
        if path == '/web/database/list':
            return self.rpc_db('list', ())
        if path == '/web/session/authenticate':
            user = self.check_login(params['db'], params['login'], params['password'])
            mfa = user.totp is not None and self.version_info >= (14,)  # auth_totp
            sid = self.new_session(http, url, user, params['db'], mfa=mfa)
            return self.session_info(self.sessions[sid])
        if path == '/web/session/get_session_info':
            if not session or not session['uid']:
                raise OdooException(SESSION_EXPIRED)
            return self.session_info(session)
        if path == '/web/session/destroy':
            self.sessions.pop(sid, None)
            return None
        if path.startswith('/web/dataset/call_kw/'):
            if not session or not session['uid']:
                raise OdooException(SESSION_EXPIRED)
            user = self.user(session['uid']) or FakeUser(1, SYSTEM_USER)
            return self.call(user, params['model'], params['method'],
                             params.get('args', ()), params.get('kwargs', {}))
        raise http_error(404, 'Not Found')

    def http_page(self, http, url, path, query, data, sid):
        """HTTP routes (HTML pages, doc), with the session info in the page."""
        session = self.sessions.get(sid)
        if path.startswith('/report/'):
            return self.report(path, data, session)
        if path.startswith('/doc/') and path.endswith('.json'):
            if self.version_info < (19,) or not session:
                raise http_error(404, 'Not Found')
            return self.model_doc(path[5:-5])
        if path == '/web/login' and data:
            db = data.get('db') or self.monodb(session)
            try:
                user = self.check_login(db, data['login'], data['password'])
            except OdooException:
                return self.page({'uid': None}, frontend=True)
            mfa = user.totp is not None and self.version_info >= (14,)  # auth_totp
            sid = self.new_session(http, url, user, db, mfa=mfa)
            if mfa:
                return self.page({'uid': None}, extra=TOTP_FORM, frontend=True)
            return self.page(self.session_info(self.sessions[sid]), frontend=True)
        if path == '/web/login/totp':
            user = session and self.users[session['login']]
            if not user or data.get('totp_token') != user.totp:
                return self.page({'uid': None}, extra=TOTP_FORM, frontend=True)
            session['uid'] = user.uid
            return self.page(self.session_info(session), frontend=True)
        if path == '/web/become':
            user = session and session['uid'] and self.user(session['uid'])
            if user and user.is_system:
                session['uid'] = 1
            return self.page(self.session_info(session) if session else {'uid': None})
        if path == '/web':
            if not (query.get('db') or self.monodb(session)):
                raise http_error(404, 'Not Found')  # No database selected
            if session and session['uid']:
                return self.page(self.session_info(session))
            return self.page({'uid': None})
        raise http_error(404, 'Not Found')

    def report(self, path, data, session):
        """Routes /report/download and /report/pdf/<report_name>/<ids>."""
        self.report_requests.append((path, data))
        if not session or not session['uid']:
            raise http_error(403, 'Forbidden')
        if path == '/report/download':
            [url, report_type] = _json.loads(data['data'])
            report_path = urlsplit(url).path
        else:
            report_path = path
        [report_name, *ids] = report_path[len('/report/pdf/'):].split('/')
        reports = self.records[self.report_model()].values()
        report = next((r for r in reports if r['report_name'] == report_name), None)
        if report is None:
            raise http_error(404, 'Not Found')
        rfile = io.BytesIO(PDF)
        # Only /report/download sets the filename (Content-Disposition)
        rfile.name = f"{report['name']}.pdf" if path == '/report/download' else None
        return rfile

    def page(self, session_info, extra='', frontend=False):
        if frontend and self.version_info < (18,) and session_info.get('uid'):
            # Before Odoo 18, the frontend pages (login) have 'user_id'
            session_info = {**session_info, 'user_id': session_info['uid']}
            del session_info['uid']
        return (f'<html><script>odoo.__session_info__ = {_json.dumps(session_info)};'
                f' csrf_token: "{self.csrf_token}",</script>{extra}</html>')

    def json2(self, path, params, headers):
        """JSON-2 and doc with bearer token (Odoo >= 19)."""
        if self.version_info < (19,):
            raise http_error(404, 'Not Found')
        api_key = headers.get('Authorization', '')[len('Bearer '):]
        user = next((u for u in self.users.values() if api_key and u.api_key == api_key), None)
        if not user or headers.get('X-Odoo-Database') not in self.databases:
            raise http_error(401, 'Unauthorized')
        if path.startswith('/doc-bearer/'):
            return self.model_doc(path[12:-5])
        (model, method) = path[8:].split('/')
        params = {**(params or {})}
        ids = params.pop('ids', None)
        return self.call(user, model, method, (ids,) if ids is not None else (), params)
