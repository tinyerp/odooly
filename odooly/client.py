import json
import os
import re
import time
from getpass import getpass
from threading import current_thread
from urllib.parse import urlencode, urljoin, urlsplit

from .colorize import color_bold
from .environment import Env, ADMIN_USER
from .exceptions import Error, ServerError
from .helpers import format_params, partial
from .http import HTTPSession
from .service import Json2, LocalDatabase, Service, WebAPI, start_odoo_services

__all__ = ["Client"]


def extract_http_response(method, result, regex):
    if method == 'HEAD':
        return result.url
    found = re.search(regex or r'odoo._*session_info_* = (.*);', result)
    return found and (found.group(1) if regex else json.loads(found.group(1)))


class Client:
    """Connection to an Odoo instance.

    This is the top level object.
    The `server` is the URL of the instance, like ``http://localhost:8069``.
    If `server` is an ``odoo`` Python package, it is used to connect to the local server.

    The `db` is the name of the database and the `user` should exist in the
    table ``res.users``.  If the `password` is not provided, it will be
    asked on login.

    As an alternative, the `session_id` of an authenticated Webclient
    session can be provided.
    """
    _use_call_button = False
    _printer = None

    def __init__(self, server, db=None, user=None, password=None, api_key=None, session_id=None):
        self._http = HTTPSession()
        self._session_uid = self._session_info = None
        self._set_services(server, db)
        self.env = Env(self)
        if user or session_id:  # Try to login
            self.login(user, password=password, api_key=api_key, database=db, session_id=session_id)

    def _set_services(self, server, db):
        if isinstance(server, list):
            server = start_odoo_services(server, appname='odooly')
        elif isinstance(server, str):
            rsvr = urlsplit(server)
            if "@" in rsvr.netloc:
                [username, password] = rsvr._userinfo
                rsvr = rsvr._replace(netloc=rsvr.netloc.rsplit("@", 1)[1])
                self._http.set_auth(server, username, password)
            if rsvr.path[-1:] == '/':
                rsvr = rsvr._replace(path=rsvr.path.rstrip('/'))
            server = rsvr.geturl()
        self._server = server

        if not isinstance(server, str):
            self._proxy = self._proxy_odoo
        elif '/jsonrpc' in server:
            self._proxy = self._proxy_jsonrpc
        else:
            if not db:
                # Resolve redirects
                __, server = self._request_parse(server, method='HEAD')
            if not server.endswith('/web'):
                server = urljoin(server, '/web')
            self._server = server
            self._proxy = self.common = self._object = None

        if isinstance(server, str):
            self.web = WebAPI(self, 'web')
            self.web.doc = WebAPI(self, 'doc')._request  # Odoo 19
            self.database = WebAPI(self, 'web/database')
            self.report = WebAPI(self, 'report')
            self.web_dataset = WebAPI(self, 'web/dataset')
            self.web_session = WebAPI(self, 'web/session')
            self.web_webclient = WebAPI(self, 'web/webclient')
        else:
            self.web = None

        if self._proxy is None:
            self.server_version = self.web_webclient.version_info()['server_version']
        else:
            # Create the RPC services
            self.common = Service(self, 'common')
            self._object = Service(self, 'object')
            if self.web is None:  # Local server
                self.database = LocalDatabase(self)
            self.server_version = self.common.version()['server_version']
        # Parse server version
        major_minor = re.search(r'\d+\.?\d*', self.server_version).group()
        self.version_info = float(major_minor)
        assert self.version_info > 8.0, f'Not supported: Odoo {major_minor}'

    def _request_parse(self, path, *, method=None, data=None, headers=None, regex=None):
        verb = method or ('GET' if data is None else 'POST')
        url = urljoin(self._server, path)
        if not self._printer:
            res = self._http.request(url, data=data, headers=headers, method=verb)
            return res, extract_http_response(verb, res, regex)
        with self._printer as log:
            log.print_sent(' '.join([verb, path] + format_params(data or {})))
            res = self._http.request(url, data=data, headers=headers, method=verb)
            parsed = extract_http_response(verb, res, regex)
            log.print_recv(str(parsed))
        return res, parsed

    def _post_jsonrpc(self, endpoint='', params=None):
        req_id = f"{os.getpid():04x}{int(time.time() * 1E6) % 2**40:010x}"
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params or {}, 'id': req_id}
        resp = self._http.request(urljoin(self._server, endpoint), json=payload)
        if r_error := resp.get('error'):
            raise ServerError(r_error)
        return resp.get('result')

    def _proxy_odoo(self, name):
        return partial(self._server._dispatch_rpc, name)
    _proxy_odoo._protocol_name = 'Odoo'

    def _proxy_jsonrpc(self, name):
        def dispatch_jsonrpc(method, args):
            return self._post_jsonrpc(params={'service': name, 'method': method, 'args': args})
        return dispatch_jsonrpc
    _proxy_jsonrpc._protocol_name = 'JSON-RPC'

    def _proxy_web(self, name):
        if name == 'doc':
            def dispatch_web(model, params):
                return self._http.request(urljoin(self._server, f"doc/{model}.json"), method='GET')
        elif name == 'report':
            def dispatch_web(path, params):
                return self._http.request(
                    urljoin(self._server, f"{name}/{path}"), data=params, method='GET')
        elif name == 'web/database':
            def dispatch_web(method, params):
                if method != 'list':
                    return self._http.request(
                        urljoin(self._server, f"{name}/{method}"), data=params)
                return self._post_jsonrpc(f"{name}/{method}", params=params)
        else:
            def dispatch_web(method, params):
                if method == 'call_kw' and name == 'web/dataset':
                    # Because of odoo/odoo#195886
                    method = f"{method}/{params['model']}/{params['method']}"
                return self._post_jsonrpc(f"{name}/{method}", params=params)
        return dispatch_web

    def __repr__(self):
        return f"<Client '{self._server}?db={self.env.db_name or ''}'>"

    def _set_session(self, session_info, session_id=None):
        """Set the ``session_id`` HTTP cookie and the uid of the current session."""
        self._http.set_cookie(self._server, 'session_id', session_id)
        self._session_uid = session_info and session_info['uid']
        self._session_info = session_info

    def _get_session_id(self):
        """Return the ``session_id`` HTTP cookie of the current session."""
        return self._http.get_cookie(self._server, 'session_id')

    def _load_session(self, session_id):
        """Attach an authenticated Webclient session, and return its info.

        The `session_id` is the value of the ``session_id`` cookie.
        Return None if the session is invalid or expired.
        """
        if not self.web:
            return
        if self._session_info and session_id == self._get_session_id():
            session_info = self._session_info
            self._session_info = None
            return session_info
        self._http.set_cookie(self._server, 'session_id', session_id)
        try:
            session_info = self.web_session.get_session_info()
        except ServerError:  # odoo.http.SessionExpiredException
            self._set_session(None)
            return
        self._set_session(session_info, session_id)
        return session_info

    def _authenticate(self, db, login, password, api_key):
        if api_key and not password and self.version_info >= 19.0:
            json2_api = Json2(self, db, api_key)
            context = json2_api('res.users', 'context_get', ())
            info = {'uid': context['uid'], 'user_context': context, 'db': db}
        elif self.web:
            info = self._authenticate_session(db, login, password)
        else:
            raise Error("Error: Cannot authenticate")
        return info

    def _authenticate_session(self, db, login, password):
        self._set_session(None)  # Do not authenticate on the shared session
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
            pass  # Cannot extract `csrf_token` or `session_info` with Regex
        except ServerError as exc:
            # Ignore: odoo.exceptions.AccessDenied
            if exc.args[0]['code'] not in {0, 200}:
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
            token = getpass(f"Authentication Code for '{color_bold(kw['login'])}' (2FA 6-digits): ")

            # 5. Submit TOTP
            params = {'csrf_token': csrf, 'totp_token': token, 'remember': 1}
            rv, session_info = self._request_parse('/web/login/totp', data=params)
        return session_info if session_info.get('username') == kw['login'] else {'uid': None}

    def _authenticate_system(self):
        __, session_info = self._request_parse('/web/become')
        self._session_uid = session_info.get('uid')
        self._session_info = None  # The session has changed
        if self._session_uid != 1:
            raise Error("Cannot become Superuser")
        return session_info

    def _authenticate_rpc(self, db, uid, login, password):
        # The password is asked by Env._check_user_password, which caches it
        if not uid:
            uid = self.common.login(db, login, password)
        session_info = {'uid': uid}
        if uid:
            args = db, uid, password, 'res.users', 'context_get', ()
            session_info['user_context'] = self._object.execute_kw(*args)
        return session_info

    def _select_database(self, db_list):
        return db_list[0] if len(db_list) == 1 else None

    def login(self, user, password=None, database=None, api_key=None, session_id=None):
        """Switch `user` and (optionally) `database`.

        If the `password` is not available, it will be asked.

        As an alternative, the `session_id` of an authenticated Webclient
        session can be provided: it is the value of the ``session_id``
        cookie of a browser session.  Use it when the password login is
        disabled, for example when the user signs in with OAuth.
        The session is shared with the browser: Odooly does not authenticate
        again on this session, and it does not log out, unless
        :meth:`Env.session_destroy` is called.  Note that :meth:`Env.sudo`
        turns the browser session into a Superuser session.
        The `user` and the `database` are optional: if provided, they must
        match the session.
        """
        env = self.env
        session_info = None
        if session_id:  # Reuse a Webclient session
            if not (session_info := self._load_session(session_id)):
                raise Error("Error: Invalid or expired session")
            if database and database != session_info['db']:
                self._set_session(None)
                raise Error(f"Error: Session is bound to database {session_info['db']!r}")
            if user and user != session_info['username']:
                self._set_session(None)
                raise Error(f"Error: Session is bound to user {session_info['username']!r}")
            (user, database) = (session_info['username'], session_info['db'])
        if not session_id and (not env.db_name or (database and env.db_name != database)):
            try:
                dbs = self.database.list()
            except Exception:
                pass  # AccessDenied: simply ignore this check
            else:
                if not database:
                    # Database selector page
                    database = self._select_database(dbs) or ''
                if dbs and database not in dbs:
                    raise Error(f"Database {database!r} does not exist: {dbs}")
        if database and env.db_name != database:
            if env.db_name and self._session_uid and not session_info:
                self._set_session(None)  # Do not reuse the session on another database
            env = Env(self, database)
        if session_info:
            # Saved like any other session: Env._check_user_password reuses it
            auth_cache = env._cache_get('auth', dict)
            auth_cache[user] = (session_info['uid'], None, session_id)
        try:
            self.env = env(user=user, password=password, api_key=api_key)
        except Exception:
            raise
        finally:
            # Used for logging, copied from odoo.sql_db.db_connect
            current_thread().dbname = self.env.db_name
        return self.env.uid

    def create_database(self, passwd, database, demo=False, lang='en_US',
                        user_password=ADMIN_USER, login=ADMIN_USER,
                        country_code=None):
        """Create a new database.

        The superadmin `passwd` and the `database` name are mandatory.
        By default, `demo` data are not loaded, `lang` is ``en_US``
        and no country is set into the database.
        Login if successful.
        """
        self.database.create(master_pwd=passwd, name=database, lang=lang,
                             password=user_password, demo=demo, login=login,
                             country_code=country_code, phone='')
        return self.login(login, user_password, database=database)

    def clone_database(self, passwd, database, neutralize_database=False):
        """Clone the current database.

        The superadmin `passwd` and `database` are mandatory.
        Login if successful.
        """
        extra = {"neutralize_database": neutralize_database} if neutralize_database else {}
        if extra and self.version_info < 16.0:
            raise Error("Argument 'neutralize_database' is not supported")
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
        self.database.drop(master_pwd=passwd, name=database)
        if database in self.database.list():
            raise Error("Failed - Database was not deleted")

    @classmethod
    def _is_interactive(cls):
        return False
