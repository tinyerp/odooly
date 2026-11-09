import json
import os
from getpass import getpass
from datetime import datetime

from . import __version__
from .colorize import color_bold
from .exceptions import Error, ServerError
from .helpers import issearchdomain, literal_eval, memoize, partial, searchargs
from .service import Json2
from .models import Model, Record

__all__ = ["Env", "ADMIN_USER", "SYSTEM_USER"]

ADMIN_USER = 'admin'
SYSTEM_USER = '__system__'

_pending_state = ('state', 'not in',
                  ['uninstallable', 'uninstalled', 'installed'])
_sql_action_code = """\
sql_queries = env.context.get('__sql') or []
result = env.cr.connection.notices

if not env.is_system():
    raise UserError('Not allowed')

for query in sql_queries:
    env.cr.execute(query)
    if not env.cr.description:
        result.append(env.cr.statusmessage)
    elif not env.cr.rowcount:
        result.append({c.name: () for c in env.cr.description})
    else:
        columns = [c.name for c in env.cr.description]
        result.extend(dict(zip(columns, values)) for values in env.cr.fetchall())

log(str({'queries': sql_queries, 'result': result}))
result[:] = []
"""


class Env:
    """An environment wraps data for Odoo models and records:

        - :attr:`db_name`, the current database;
        - :attr:`uid`, the current user id;
        - :attr:`context`, the current context dictionary.

        To retrieve an instance of ``some.model``:

        >>> env["some.model"]
    """

    name = uid = user = session_info = _api_key = _doc = _json2 = _access_models = None
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
            env._model_names = env._cache_get('model_names', dict)
            env._models = {}
        return env

    def __contains__(self, name):
        """Test wether this model exists."""
        return name in self.models(name)

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
        if user == SYSTEM_USER and self.uid and not password:
            info = self.client._authenticate_system()
            return info['uid'], password, info
        # Read from cache
        auth_cache = self._cache_get('auth', dict)
        (uid, pwcache) = auth_cache.get(user) or (None, None)
        password = password or pwcache
        # Ask for password
        if not password and not api_key:
            password = getpass(f"Password for '{color_bold(user)}': ")
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
            self._doc = (self._json2 or self.client.web).doc
            try:
                self._doc('res.device')
            except ServerError:
                self._doc = None
        prev_protocol = getattr(getattr(self, '_execute_kw', 0), '_protocol_name', ...)
        if self.client._object:  # RPC endpoint if available
            self._execute_kw = env_auth(self.client._object.execute_kw)
            self._execute_kw._protocol_name = self.client._proxy._protocol_name
        else:  # Otherwise, use JSON-2 or WebAPI
            self._execute_kw = self._json2 or self._call_kw
        if (
            prev_protocol not in {self._execute_kw._protocol_name, ...} and
            self.client._is_interactive()
        ):
            self.client.connect()
        self._api_key = api_key if store else None
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
        env.user = Record(env._get('res.users', False), uid)
        env.context = dict(context)
        env.session_info = session
        if user:
            assert isinstance(user, str), repr(user)
            env.user.__dict__['login'] = user

        # Set API methods
        if uid != self.uid or (api_key and api_key != self._api_key):
            env.set_api_key(api_key or password, bool(api_key))
        else:  # Copy methods
            for attr in 'access_models', 'api_key', 'doc', 'execute_kw', 'json2':
                setattr(env, f'_{attr}', getattr(self, f'_{attr}'))
        return env

    @property
    def odoo_env(self):
        """Return a server Environment."""
        return self.client._server.api.Environment(self.cr, self.uid, self.context)

    @property
    def cr(self):
        """Return a cursor on the database."""
        return self.__dict__.get('cr') or memoize(self, 'cr', self.registry.cursor())

    @property
    def registry(self):
        """Return the environment's registry."""
        return self.client._server._get_pool(self.db_name)

    def __call__(self, user=None, password=None, api_key=None, context=None):
        """Return an environment based on ``self`` with modified parameters."""
        if user is not None:
            (uid, password, session) = self._check_user_password(user, password, api_key)
            if context is None:
                context = session.get('user_context') or {}
        elif context is not None:
            (uid, user, session) = (self.uid, self.user, self.session_info)
        else:
            return self
        env_key = bytes.fromhex(f"{uid:08x}{hash(json.dumps(context, sort_keys=1)) % 2**32:08x}")
        if (env := self._cache_get(env_key)) is None:
            env = self._configure(uid, user, password, api_key, context, session)
            env._cache_set(env_key, env)
        return env

    def sudo(self, user=None):
        """Attach to the provided user, or Superuser."""
        if user is None:
            if self.client._object or not (self.session_info or {}).get('is_system'):
                user = ADMIN_USER
            else:
                user = SYSTEM_USER
        return self(user=user)

    def ref(self, xml_id):
        """Return the record for the given ``xml_id`` external ID."""
        (module, name) = xml_id.split('.')
        data = self._get('ir.model.data', False).read(
            [('module', '=', module), ('name', '=', name)], 'model res_id')
        if data:
            assert len(data) == 1
            return Record(self[data[0]['model']], data[0]['res_id'])

    @property
    def lang(self):
        """Return the current language code."""
        return self.context.get('lang')

    def refresh(self):
        db_key, preserve = (self.db_name, self.client._server), ('auth', Env)
        for key in [*self._cache]:
            if key[1:] == db_key and key[0] not in preserve and self._cache[key] != self:
                del self._cache[key]
        self._access_models = None
        self._model_names = self._cache_set('model_names', {})
        self._models = {}
        if self._json2:
            self._json2.reset()

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
        return hasattr(result, 'get') and result.get('res_model') == 'res.users.identitycheck'

    def _identitycheck(self, result):
        assert self.client.version_info >= 14.0, f'Not supported: Odoo {self.client.version_info}'
        idcheck = self._get(result['res_model'], transient=True).get(result['res_id'])
        password = self._cache_get('auth')[self.user.login][1]
        result = None
        while not result:
            try:
                password = password or getpass(f"Password for '{color_bold(self.user.login)}': ")
            except (KeyboardInterrupt, EOFError):
                print()
                raise Error("Security Control - FAILED")
            if self.client.version_info < 19.0:
                idcheck.password = password
            try:
                # Odoo >= 19 read from context
                result = idcheck.with_context(password=password).run_check()
            except ServerError as exc:
                error = exc.args[0]['data']
                if (
                    not self.client._is_interactive() or
                    error['name'] != 'odoo.exceptions.UserError'
                ):
                    raise
                password = None
                print(error['message'])
        if self.client._is_interactive():
            print("Security Control - PASSED")
        return result

    def _call_kw(self, model, method, args, kw=None):
        if self.uid != self.client._session_uid:
            password = self._cache_get('auth')[self.user.login][1]
            if self.user.login == SYSTEM_USER and not password:
                self.client._authenticate_system()
            else:
                self.client._authenticate_session(self.db_name, self.user.login, password)
        if method in {'create', 'write', 'unlink'} and self.client._use_call_button:
            return self.client.web_dataset.call_button(
                model=model, method=method, args=args, kwargs=kw or {})
        return self.client.web_dataset.call_kw(
            model=model, method=method, args=args, kwargs=kw or {})
    _call_kw._protocol_name = 'Web API'

    def execute(self, obj, method, *params, **kwargs):
        """Wrapper around ``/web/dataset/call_kw`` Webclient endpoint,
        or ``/json/2`` API endpoint or ``object.execute_kw`` RPC method.

        Argument `method` is the name of a standard ``Model`` method
        or a specific method available on this `obj`.
        Method `params` are accepted.  If needed, keyword
        arguments are collected in `kwargs`.
        """
        assert self.uid, 'Not connected'
        assert isinstance(obj, str) and isinstance(method, str) and method != 'browse'
        order_ids = single_id = False
        if method == 'read':
            assert params, 'Missing parameter'
            if not isinstance(params[0], list):
                single_id = True
                ids = [params[0]] if params[0] else False
            elif params[0] and issearchdomain(params[0]):
                # Combine search+read
                method, [ids] = 'search_read', searchargs(params[:1])
            else:
                order_ids = kwargs.pop('order', False) and params[0]
                ids = sorted({*params[0]} - {False})
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
        kw = (({**kwargs, 'context': self.context},)
              if self.context else (kwargs and ({**kwargs},) or ()))
        res = self._execute_kw(obj, method, params, *kw)
        if self._is_identitycheck(res):
            res = self._identitycheck(res)
        if order_ids:
            # Results were not in the same order as the IDs
            # in case of missing records or duplicate ID
            resdic = {val['id']: val for val in res}
            res = [resdic.get(id_, False) for id_ in order_ids]
        return (res or [None])[0] if single_id else res

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

    def _models_get(self, name, check, transient):
        if name not in self._model_names:
            if check:
                raise KeyError(name)
            self._model_names[name] = transient
        try:
            return self._models[name]
        except KeyError:
            self._models[name] = Model._new(self, name)
        return self._models[name]

    def models(self, name='', transient=False):
        """Search Odoo models.

        The argument `name` is a pattern to filter the models returned.
        If omitted, all models are returned.

        The return value is a sorted list of model names.
        """
        if self._access_models is None:
            ir_model = self._get('ir.model', False)
            domain = [('abstract', '=', False)] if 'abstract' in ir_model._keys else []  # Odoo 19
            try:
                models = ir_model.search_read(domain, ('model', 'transient'))
            except ServerError:
                # Only Odoo 15 prevents non-admin user to retrieve models
                models = ir_model.get_available_models() if self.client.version_info >= 16.0 else {}
            self._model_names.update({m['model']: m.get('transient', False) for m in models})
            self._access_models = bool(models)
        return sorted(mod for mod, is_transient in self._model_names.items()
                      if name in mod and transient == is_transient)

    def _get(self, name, check=True, transient=False):
        """Return a :class:`Model` instance.

        The argument `name` is the name of the model.  If the optional
        argument `check` is :const:`False`, no validity check is done.
        """
        check = check and not transient and self._access_models is not False
        try:
            return self._models_get(name, check, transient=transient)
        except KeyError:
            model_names = self.models(name)
        if name in self._model_names or not self._access_models:
            return self._models_get(name, self._access_models, transient=transient)
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
        if mods := ir_module.read(domain, 'name state'):
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
        sel = ir_module.search([('name', 'in', modules)])
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
            # Click upgrade/install/uninstall button
            if button != 'cancel':
                self.execute('ir.module.module', button, sel.ids)
                mods = ir_module.read([_pending_state], 'name state')
        if not mods:
            if sel:
                print(f"Already up-to-date: {self.modules([('id', 'in', sel.ids)])}")
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
            if not (ans := input('Confirm? [y/N] ')) or ans[:1].lower() != 'y':
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
            'password': password or getpass(f"Password for '{color_bold(login)}': "),
        }
        self.session_info = self.client._authenticate_session(**params)
        # When database name is discovered, copy cached data
        if (
            not self.db_name and
            (not self.uid or login == self.user.login) and
            self.session_info.get('db')
        ):
            empty_db_key = (self.db_name, self.client._server)
            self.db_name = self.session_info['db']
            for key in [*self._cache]:
                if key[1:] == empty_db_key:
                    self._cache_set(key[0], self._cache[key])
        print(f'Session authenticated for {login!r}' if self.session_info['uid'] else 'Failed')

    def session_destroy(self):
        """Terminate current Webclient session."""
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
        assert self.client.version_info >= 14.0, f'Not supported: Odoo {self.client.version_info}'
        key_vals = {'name': f'Created by Odooly {__version__}'}
        wiz_model = self._get("res.users.apikeys.description", transient=True)
        res = wiz_model.create(key_vals).make_key()
        self.user._invalidate_cache()
        self.refresh()  # Remove cached Envs
        assert res['res_model'] == "res.users.apikeys.show"
        return self.set_api_key(res['context']['default_key'])

    def _get_sql_action(self, _external_id="__odooly__.sql"):
        act_model = self._get('ir.actions.server', False)
        if not (action := act_model.get(_external_id)):
            logg_model = self._get('ir.model', False).get('base.model_ir_logging')
            values = {'name': 'SQL Execute', 'state': 'code', 'model_id': logg_model.id}
            (action := act_model.create(values).ensure_one())._set_external_id(_external_id)
        return action.with_context(lang=None)

    def sql(self, queries):
        """Execute SQL commands on the PostgreSQL server."""
        qlist = []
        for query in queries.split(";"):
            if any(li.split('--', 1)[0].strip() for li in query.splitlines()):
                qlist.append(query.strip())
        if not qlist:
            return None

        vals = {'name': f'SQL Execute {datetime.now()}_{hash(queries)*os.getpid() % 2**24:06x}'}
        if (sql_action := self._get_sql_action()).code != _sql_action_code:
            vals['code'] = _sql_action_code
        sql_action.write(vals)
        sql_action.with_context(__sql=qlist).run()

        logg = self._get('ir.logging', False).get([('func', '=', vals['name'])])
        return literal_eval(logg.message) if logg else None
