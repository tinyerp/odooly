from http.cookiejar import Cookie
from unittest import mock, TestCase
from unittest.mock import call, sentinel, ANY

import odooly.run
from ._common import FakeOdooTestCase, JsonRpcTestCase, OdooTestCase, OBJ, PseudoFile
from ._fake_odoo import FakeOdoo, FakeUser

AUTH = sentinel.AUTH
ID1, ID2 = 4001, 4002
STABLE = ['uninstallable', 'uninstalled', 'installed']


def _skip_test(test_case):
    pass


def imm(method, *params):
    return ('object.execute_kw', AUTH, 'ir.module.module', method, params, {'context': ANY})


def bmu(method, *params):
    return ('object.execute_kw', AUTH, 'base.module.upgrade', method, params, {'context': ANY})


def jsonrpc_call(test, service, method, args):
    params = {'service': service, 'method': method, 'args': args}
    return call(f'{test.server}/jsonrpc',
                json={'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': ANY})


class IdentDict(object):
    def __init__(self, _id):
        self._id = _id

    def __repr__(self):
        return 'IdentDict(%s)' % (self._id,)

    def __getitem__(self, key, default=None):
        return (key == 'id') and self._id or ('v_%s_%s' % (key, self._id))
    get = __getitem__

    def __eq__(self, other):
        return self._id == other._id


DIC1 = IdentDict(ID1)
DIC2 = IdentDict(ID2)


class TestServiceJsonRpc(JsonRpcTestCase):
    """Test the Service class with JSON-RPC."""
    protocol = 'jsonrpc'
    server_version = '14.0'
    uid = 22

    def _patch_service(self):
        return mock.patch('odooly.http.HTTPSession.request', return_value={'result': 'JSON_RESULT'}).start()

    def _get_client(self):
        proxy = getattr(odooly.Client, '_proxy_%s' % self.protocol)
        client = mock.Mock()
        client._printer = mock.MagicMock(name='Printer')
        client._proxy = proxy.__get__(client, odooly.Client)
        client._server = f"{self.server}/{self.protocol}"
        client._post_jsonrpc = odooly.Client._post_jsonrpc.__get__(client, odooly.Client)
        client._http.request = self.service
        return client

    def test_service(self):
        client = self._get_client()
        svc_common = odooly.client.Service(client, 'common')

        self.assertIn('common', str(svc_common.login))
        self.assertRaises(AttributeError, getattr, svc_common, 'theta')
        self.assertCalls()
        self.assertOutput('')

    def test_service_odoo(self):
        client = self._get_client()

        def get_proxy(name, methods=None):
            return odooly.client.Service(client, name)

        self.assertIn('common', str(get_proxy('common').login))
        login = get_proxy('common').login('aaa')
        with self.assertRaises(AttributeError):
            get_proxy('common').non_existent
        self.assertCalls(jsonrpc_call(self, 'common', 'login', ('aaa',)))
        self.assertEqual(login, 'JSON_RESULT')
        self.assertOutput('')

    def test_service_odoo_client(self, server_version=14.0):
        odooly.Env._cache.clear()

        server = f"{self.server}/{self.protocol}"
        return_values = [{'server_version': str(server_version)}, ['newdb'], 1, {}]
        if self.protocol == 'jsonrpc':
            return_values = [{'result': rv} for rv in return_values]
        if server_version >= 19.0:
            return_values += [{'uid': 1}, odooly.ServerError]
        self.service.side_effect = return_values
        client = odooly.Client(server, 'newdb', 'usr', 'pss')

        self.service.return_value = ANY
        self.assertIsInstance(client.common, odooly.client.Service)
        self.assertIsInstance(client._object, odooly.client.Service)

        # Removed RPC services
        self.assertRaises(AttributeError, getattr, client, 'db')
        self.assertRaises(AttributeError, getattr, client, '_report')
        self.assertRaises(AttributeError, getattr, client, '_wizard')

        self.assertIsInstance(client.database, odooly.client.WebAPI)
        self.assertIn('/web/database', str(client.database.create))
        self.assertIn('/web/database', str(client.database.exist))

        expected_calls = [
            jsonrpc_call(self, 'common', 'version', ()),
            call(f'{self.server}/web/database/list',
                 json={'jsonrpc': '2.0', 'method': 'call', 'params': {}, 'id': ANY}),
            jsonrpc_call(self, 'common', 'login', ('newdb', 'usr', 'pss')),
            jsonrpc_call(self, 'object', 'execute_kw', ('newdb', 1, 'pss', 'res.users', 'context_get', ())),
        ]
        if server_version >= 19.0:
            expected_calls += [
                call(f'{self.server}/json/2/res.users/context_get', json={}, headers=ANY),
                call(f'{self.server}/doc-bearer/res.device.json', method='GET', json=None, headers=ANY),
            ]

        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_service_odoo_15_17(self):
        self.test_service_odoo_client(server_version=17.0)
        self.test_service_odoo_client(server_version=16.0)
        self.test_service_odoo_client(server_version=15.0)

    def test_service_odoo_18_20(self):
        self.test_service_odoo_client(server_version=18.0)
        self.test_service_odoo_client(server_version=19.0)
        self.test_service_odoo_client(server_version=20.0)


class TestCreateClient(JsonRpcTestCase):
    """Test the Client class."""
    server_version = '14.0'
    server = f'{JsonRpcTestCase.server}/jsonrpc'
    startup_calls = (
        call(ANY, 'common'),
        call(ANY, 'object'),
        'common.version',
        'database.list',
    )

    def test_create(self):
        self.service.database.list.return_value = ['newdb']
        self.service.common.login.return_value = 1

        s_context = '{"lang": "en_US", "tz": "Europe/Zurich"}'
        key_1 = b"\0\0\0\1" + bytes.fromhex(f'{hash("{}") % 2**32:08x}')
        key_2 = b"\0\0\0\1" + bytes.fromhex(f'{hash(s_context) % 2**32:08x}')
        client = odooly.Client(self.server, 'newdb', 'usr', 'pss')
        expected_calls = self.startup_calls + (
            call.common.login('newdb', 'usr', 'pss'),
            call.object.execute_kw('newdb', 1, 'pss', 'res.users', 'context_get', ()),
        )
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(
            client.env._cache,
            {(odooly.Env, 'newdb', self.server): odooly.Env(client, 'newdb'),
             (key_1, 'newdb', self.server): client.env(context={}),
             (key_2, 'newdb', self.server): client.env,
             ('auth', 'newdb', self.server): {'usr': (1, 'pss', None)},
             ('model_names', 'newdb', self.server): {'res.users': False}})
        self.assertOutput('')

    def test_create_getpass(self):
        getpass = mock.patch('odooly.environment.getpass',
                             return_value='password').start()
        self.service.database.list.return_value = ['database']
        expected_calls = self.startup_calls + (
            call.common.login('database', 'usr', 'password'),
        )

        # A: Invalid login
        self.assertRaises(odooly.Error, odooly.Client, self.server, 'database', 'usr')
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 1)

        # B: Valid login
        self.service.common.login.return_value = 17
        getpass.reset_mock()
        expected_calls = expected_calls + (
            call.object.execute_kw('database', 17, 'password', 'res.users', 'context_get', ()),
        )

        client = odooly.Client(self.server, 'database', 'usr')
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 1)

    def test_create_with_cache(self):
        self.service.database.list.return_value = ['database']
        self.assertFalse(odooly.Env._cache)
        mock.patch.dict(odooly.Env._cache,
                        {('auth', 'database', self.server): {'usr': (1, 'password', None)}}).start()

        client = odooly.Client(self.server, 'database', 'usr')
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*(self.startup_calls + (
            call.object.execute_kw('database', 1, 'password', 'res.users', 'context_get', ()),
        )))
        self.assertOutput('')

    def test_create_from_config(self):
        env_tuple = (self.server, 'database', 'usr', None, None)
        read_config = mock.patch('odooly.run.InteractiveClient.get_config',
                                 return_value=env_tuple).start()
        getpass = mock.patch('odooly.environment.getpass', return_value='password').start()
        self.service.database.list.return_value = ['database']
        expected_calls = self.startup_calls + (
            call.common.login('database', 'usr', 'password'),
        )

        # A: Invalid login
        self.service.common.login.return_value = False
        self.assertRaises(odooly.Error, odooly.run.InteractiveClient.from_config, 'test')
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(getpass.call_count, 1)

        # B: Valid login
        self.service.common.login.return_value = 17
        read_config.reset_mock()
        getpass.reset_mock()
        expected_calls = expected_calls + (
            call.object.execute_kw('database', 17, 'password', 'res.users', 'context_get', ()),
        )

        client = odooly.run.InteractiveClient.from_config('test')
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(getpass.call_count, 1)

    def test_create_invalid(self):
        # Without mock
        self.service.stop()

        self.assertRaises(odooly.ServerError, odooly.Client, 'http://dsadas/jsonrpc/1')
        self.assertOutput('')


class TestSampleSession(JsonRpcTestCase):
    server_version = '14.0'
    server = f'{JsonRpcTestCase.server}/jsonrpc'
    database = 'database'
    user = 'user'
    password = 'passwd'
    uid = 4

    def test_simple(self):
        self.service.object.execute_kw.side_effect = [
            4, {'id', 'model'}, [{'id': 71, 'model': 'ir.cron'}], sentinel.CRON]

        res_users = self.env['res.users']
        self.assertEqual(res_users.search_count(), 4)
        self.assertEqual(self.env['ir.cron'].read(
            ['active = False'], 'active function'), sentinel.CRON)
        self.assertCalls(
            OBJ('res.users', 'search_count', []),
            OBJ('ir.model', 'fields_get'),
            OBJ('ir.model', 'search_read', [], ('model', 'transient')),
            OBJ('ir.cron', 'search_read', [('active', '=', False)], ['active', 'function']),
        )
        self.assertOutput('')

    def test_list_modules(self):
        self.service.object.execute_kw.side_effect = [
            [{'id': 'delivery_a', 'state': 'not installed', 'name': 'dummy'}]]

        modules = self.env.modules('delivery')
        self.assertIsInstance(modules, dict)
        self.assertIn('not installed', modules)

        self.assertCalls(
            imm('search_read', [('name', 'like', 'delivery')], ['name', 'state']),
        )
        self.assertOutput('')

    def test_module_upgrade(self):
        self.service.object.execute_kw.side_effect = [
            (42, 0), [], [42], ANY,
            [{'id': 42, 'state': ANY, 'name': ANY}], ANY, ANY]

        result = self.env.upgrade('dummy')
        self.assertIsNone(result)

        self.assertCalls(
            imm('update_list'),
            imm('search_read', [('state', 'not in', STABLE)], ['name', 'state']),
            imm('search', [('name', 'in', ('dummy',))]),
            imm('button_upgrade', [42]),
            imm('search_read', [('state', 'not in', STABLE)], ['name', 'state']),
            bmu('upgrade_module', []),
        )
        self.assertOutput(ANY)

    def test_client_verbose(self):
        client = self.client

        self.assertIsNone(client.verbose)

        client.verbose = 1
        self.assertEqual(client.verbose, 79)

        client.verbose = 3
        self.assertEqual(client.verbose, 9999)

        client.verbose = 140
        self.assertEqual(client.verbose, 140)
        self.assertEqual(client._printer.width, 140)

        client.verbose = 0
        self.assertIsNone(client.verbose)
        self.assertIsNone(client._printer.width)


class TestClientApi(JsonRpcTestCase):
    """Test the Client API for Odoo 14."""
    server_version = '14.0'
    server = f'{JsonRpcTestCase.server}/jsonrpc'
    database = 'database'
    user = 'user'
    password = 'passwd'
    uid = 4

    def obj_exec(self, *args):
        if args[4] == 'search':
            return [ID2, ID1]
        if args[4] in ('read', 'search_read'):
            return [IdentDict(res_id) for res_id in [ID1, ID2]]
        if args[4] == 'fields_get':
            keys = ('id', 'model', 'transient')
            if float(self.server_version) >= 19.0:
                keys += ('abstract',)
            return dict.fromkeys(keys, sentinel.FIELD)
        return sentinel.OTHER

    def test_create_database(self):
        create_database = self.client.create_database
        self.client.database.list.side_effect = [['db1'], ['db2'], ['db3']]

        create_database('abc', 'db1')
        create_database('xyz', 'db2', user_password='secret', lang='fr_FR')

        expected_calls = [
            call.database.create(master_pwd='abc', name='db1', lang='en_US', password='admin', demo=False, login='admin', country_code=None, phone=''),
            call.database.list(),
            call.common.login('db1', 'admin', 'admin'),
            call.object.execute_kw('db1', self.uid, 'admin', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
            call.database.create(master_pwd='xyz', name='db2', lang='fr_FR', password='secret', demo=False, login='admin', country_code=None, phone=''),
            call.database.list(),
            call.common.login('db2', 'admin', 'secret'),
            call.object.execute_kw('db2', self.uid, 'secret', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
            call.database.create(master_pwd='xyz', name='db3', lang='fr_FR', password='secret', demo=False, login='other_login', country_code='CA', phone=''),
            call.database.list(),
            call.common.login('db3', 'other_login', 'secret'),
            call.object.execute_kw('db3', self.uid, 'secret', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
        ]

        if float(self.server_version) < 19.0:
            del expected_calls[14], expected_calls[9], expected_calls[4]
        create_database('xyz', 'db3', user_password='secret', lang='fr_FR', login='other_login', country_code='CA')
        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_clone_database(self):
        clone_database = self.client.clone_database
        self.client.database.list.side_effect = [['database', 'db1'], ['database', 'db1', 'db2']]

        clone_database('abc', 'db1')

        expected_calls = [
            call.database.duplicate(master_pwd='abc', name='database', new_name='db1'),
            call.database.list(),
            call.object.execute_kw('db1', 4, 'passwd', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
            call.database.duplicate(master_pwd='xyz', name='db1', new_name='db2', neutralize_database=True),
            call.database.list(),
            call.object.execute_kw('db2', 4, 'passwd', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
        ]

        if float(self.server_version) < 16.0:
            # Error: Argument 'neutralize_database' is not supported
            self.assertRaises(odooly.Error, clone_database, 'xyz', 'db2', neutralize_database=True)
            del expected_calls[-5:]
        else:
            if float(self.server_version) < 19.0:
                del expected_calls[7], expected_calls[3]
            clone_database('xyz', 'db2', neutralize_database=True)
        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_drop_database(self):
        drop_database = self.client.drop_database
        self.client.database.list.side_effect = [['database', 'db1', 'db2'], ['database', 'db2']]

        # Failed - Database was not deleted
        self.assertRaises(odooly.Error, drop_database, 'abc', 'db2')
        # Failed - Cannot delete active database
        self.assertRaises(odooly.Error, drop_database, 'abc', 'database')
        drop_database('abc', 'db1')

        expected_calls = [
            call.database.drop(master_pwd='abc', name='db2'),
            call.database.list(),
            call.database.drop(master_pwd='abc', name='db1'),
            call.database.list(),
        ]

        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_nonexistent_methods(self):
        self.assertRaises(AttributeError, getattr, self.client, 'search')
        self.assertRaises(AttributeError, getattr, self.client, 'count')
        self.assertRaises(AttributeError, getattr, self.client, 'search_count')
        self.assertRaises(AttributeError, getattr, self.client, 'search_read')
        self.assertRaises(AttributeError, getattr, self.client, 'keys')
        self.assertRaises(AttributeError, getattr, self.client, 'fields')
        self.assertRaises(AttributeError, getattr, self.client, 'field')

        self.assertRaises(AttributeError, getattr, self.env, 'search')
        self.assertRaises(AttributeError, getattr, self.env, 'count')
        self.assertRaises(AttributeError, getattr, self.env, 'search_count')
        self.assertRaises(AttributeError, getattr, self.env, 'search_read')
        self.assertRaises(AttributeError, getattr, self.env, 'keys')
        self.assertRaises(AttributeError, getattr, self.env, 'fields')
        self.assertRaises(AttributeError, getattr, self.env, 'field')

    def test_model(self):
        self.service.object.execute_kw.side_effect = self.obj_exec

        domain = [('abstract', '=', False)] if float(self.server_version) >= 19.0 else []
        expected_calls = [OBJ('ir.model', 'search_read', domain, ('model', 'transient'))]
        side_effect = [[{'id': 13, 'model': 'foo.bar'}]]

        self.assertFalse(self.env.models('foo.bar'))
        self.assertCalls(OBJ('ir.model', 'fields_get'), *expected_calls)

        self.env._access_models = None
        self.assertRaises(odooly.Error, self.env.__getitem__, 'foo.bar')
        self.assertCalls(*expected_calls)

        self.env._access_models = None
        self.service.object.execute_kw.side_effect = side_effect
        self.assertIsInstance(self.env['foo.bar'], odooly.Model)
        self.assertIs(self.env['foo.bar'], odooly.Model(self.env, 'foo.bar'))
        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_access(self):
        self.assertTrue(self.env.has_access('foo.bar'))
        if float(self.server_version) < 18.0:
            self.assertCalls(OBJ('ir.model.access', 'check', 'foo.bar', 'read'))
        else:
            self.assertCalls(OBJ('foo.bar', 'has_access', [], 'read'))
        self.assertOutput('')

    def test_execute_kw(self):
        execute_kw = self.env._execute_kw

        execute_kw('foo.bar', 'any_method', (42,))
        execute_kw('foo.bar', 'any_method', ([42],))
        execute_kw('foo.bar', 'any_method', ([13, 17],))
        self.assertCalls(
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', (42,)),
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', ([42],)),
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', ([13, 17],)),
        )
        self.assertOutput('')

    def _module_upgrade(self, button='upgrade'):
        execute_return = [
            [7, 0], [], [42], {'name': 'Upgrade'},
            [{'id': 4, 'state': ANY, 'name': ANY},
             {'id': 5, 'state': ANY, 'name': ANY},
             {'id': 42, 'state': ANY, 'name': ANY}], ANY]
        action = getattr(self.env, button)

        expected_calls = [
            imm('update_list'),
            imm('search_read', [('state', 'not in', STABLE)], ['name', 'state']),
            imm('search', [('name', 'in', ('dummy', 'spam'))]),
            imm('button_' + button, [42]),
            imm('search_read', [('state', 'not in', STABLE)], ['name', 'state']),
            bmu('upgrade_module', []),
        ]
        if button == 'uninstall':
            domain = [
                ('id', 'in', [42]),
                ('state', '!=', 'installed'),
                ('state', '!=', 'to upgrade'),
                ('state', '!=', 'to remove'),
            ]
            expected_calls[3:3] = [imm('search_read', domain, ['name'])]
            execute_return[3:3] = [[]]

        self.service.object.execute_kw.side_effect = execute_return
        result = action('dummy', 'spam', quiet=True)
        self.assertIsNone(result)
        self.assertCalls(*expected_calls)
        self.assertIn('to process', self.stdout.popvalue())

        self.service.object.execute_kw.side_effect = [[0, 0], [], []]
        self.assertIsNone(action())
        self.assertCalls(
            *expected_calls[:2],
            imm('search', [('name', 'in', ())]),
        )
        self.assertOutput('0 module(s) updated\n')

    def test_module_upgrade(self):
        self._module_upgrade('install')
        self._module_upgrade('upgrade')
        self._module_upgrade('uninstall')

    def test_module_upgrade_cancel(self):
        states = [
            {'id': 4, 'state': 'to upgrade', 'name': ANY},
            {'id': 5, 'state': 'to remove', 'name': ANY},
            {'id': 42, 'state': 'to install', 'name': ANY},
        ]
        execute_return = [[7, 0], states, [], None, None]
        expected_calls = [
            imm('update_list'),
            imm('search_read', [('state', 'not in', STABLE)], ['name', 'state']),
            imm('search', [('name', 'in', ())]),
        ]
        if float(self.server_version) < 19.0:
            expected_calls += [
                imm('button_install_cancel', [42]),
                imm('button_upgrade_cancel', [4, 5]),
            ]
        else:
            expected_calls += [
                imm('button_reset_state'),
            ]
        self.service.object.execute_kw.side_effect = execute_return

        result = self.env.upgrade_cancel()

        self.assertIsNone(result)
        self.assertCalls(*expected_calls)
        self.assertOutput(
            "0 module(s) selected\n3 module(s) to process:"
            "\n  to upgrade\t<ANY>\n  to remove\t<ANY>\n  to install\t<ANY>\n")

        self.service.object.execute_kw.side_effect = [[0, 0], [], []]
        self.assertIsNone(self.env.upgrade_cancel())
        self.assertCalls(
            *expected_calls[:2],
            imm('search', [('name', 'in', ())]),
        )
        self.assertOutput('0 module(s) updated\n')

    def test_sudo(self):
        ctx_lang = {'lang': 'it_IT'}
        self.service.object.execute_kw.side_effect = [ctx_lang]
        getpass = mock.patch('odooly.environment.getpass', side_effect=['xxx', 'ooo']).start()
        env = self.env(user='guest')

        self.service.object.execute_kw.side_effect = [ctx_lang, ctx_lang]
        self.service.common.login.side_effect = [1]
        self.assertTrue(env.sudo().has_access('res.users', 'write'))
        self.assertFalse(env.has_access('res.users', 'write'))

        expected_calls = [
            call.common.login('database', 'guest', 'xxx'),
            ('object.execute_kw', self.database, 4, 'xxx', 'res.users', 'context_get', ()),
            #
            call.common.login('database', 'admin', 'ooo'),
            ('object.execute_kw', self.database, 1, 'ooo', 'res.users', 'context_get', ()),
            call.doc._request('res.device'),
            ('object.execute_kw', self.database, 1, 'ooo', 'res.users', 'has_access', ([], 'write'), {'context': ctx_lang}),
            ('object.execute_kw', self.database, 4, 'passwd', 'res.users', 'has_access', ([], 'write'), {'context': ctx_lang}),
        ]
        if float(self.server_version) < 19.0:
            del expected_calls[4]
            if float(self.server_version) < 18.0:
                expected_calls[-2:] = [
                    ('object.execute_kw', self.database, 1, 'ooo',
                     'ir.model.access', 'check', ('res.users', 'write'), {'context': ctx_lang}),
                    ('object.execute_kw', self.database, 4, 'passwd',
                     'ir.model.access', 'check', ('res.users', 'write'), {'context': ctx_lang}),
                ]
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.mock_calls,
                         [call("Password for 'guest': "), call("Password for 'admin': ")])
        self.assertOutput('')

    def test_local_only(self):
        # Env.cr, Env.odoo_env and with_odoo() need the local mode
        for func in (lambda: self.env.cr, lambda: self.env.odoo_env,
                     lambda: self.env['res.users'].browse(1).with_odoo()):
            with self.assertRaisesRegex(odooly.Error, 'Not available'):
                func()

    def test_obsolete_methods(self):
        self.assertRaises(AttributeError, getattr, self.env, 'exec_workflow')
        self.assertRaises(AttributeError, getattr, self.env, 'render_report')
        self.assertRaises(AttributeError, getattr, self.env, 'report')
        self.assertRaises(AttributeError, getattr, self.env, 'report_get')
        self.assertRaises(AttributeError, getattr, self.env, 'wizard_create')
        self.assertRaises(AttributeError, getattr, self.env, 'wizard_execute')


class TestClientApi17(TestClientApi):
    """Test the Client API for Odoo 17."""
    server_version = '17.0'


class TestClientApi18(TestClientApi):
    """Test the Client API for Odoo 18."""
    server_version = '18.0'


class TestClientApi19(TestClientApi):
    """Test the Client API for Odoo 19 to 21: same behaviour."""
    server_version = '19.0'


class TestSharedSession(FakeOdooTestCase):
    """Test the Client with the session_id of a browser session."""
    server_version = '17.0'
    database, user, uid = 'prod', 'jdoe@example.com', 7

    def fake_odoo(self):
        server = FakeOdoo(self.server_version, databases=['prod'], list_db=False, users=[
            FakeUser(2, 'admin', 'admin', is_system=True, context={'lang': 'en_US'}),
            FakeUser(self.uid, self.user, is_system=True, context={'lang': 'en_US'}),
        ])
        # The browser session, and a predictable id for the password session
        server.sessions['BROWSER'] = {'uid': self.uid, 'login': self.user, 'db': self.database}
        server.session_names['admin'] = 'OWN'
        # Show which user executes the search
        server.methods['res.partner', 'search'] = lambda user, args, kwargs: [user.uid]
        return server

    def setUp(self):
        super().setUp()
        self.sessions = self.odoo_server.sessions
        self.requests = self.odoo_server.requests

    def test_login_session(self):
        client = odooly.Client(self.server, session_id='BROWSER')

        self.assertEqual(client.env.uid, self.uid)
        self.assertEqual(client.env.user.login, self.user)
        self.assertEqual(client.env.db_name, self.database)
        self.assertEqual(client.env.context, {'lang': 'en_US', 'uid': self.uid})
        self.assertEqual(client.env.session_info,
                         self.odoo_server.session_info(self.sessions['BROWSER']))
        self.assertEqual(client.env._cache_get('auth')[self.user], (self.uid, None, 'BROWSER'))
        self.assertEqual(self.requests, [
            ('', None),  # HEAD request
            ('/web/webclient/version_info', None),
            ('/web/session/get_session_info', 'BROWSER'),
        ])
        self.assertEqual(client.env['res.partner'].search([]).ids, [self.uid])
        self.assertEqual(self.requests[-1], ('/web/dataset/call_kw/res.partner/search', 'BROWSER'))
        self.assertOutput('')

    def test_login_session_invalid(self):
        with self.assertRaisesRegex(odooly.Error, 'Invalid or expired session'):
            odooly.Client(self.server, session_id='WRONG')
        self.assertEqual(self.requests[-1], ('/web/session/get_session_info', 'WRONG'))

        client = odooly.Client(self.server)
        with self.assertRaisesRegex(odooly.Error, "bound to database 'prod'"):
            client.login(None, session_id='BROWSER', database='other')
        self.assertFalse([*client._http._cookies])
        self.assertIsNone(client.env.uid)

        with self.assertRaisesRegex(odooly.Error, "bound to user 'jdoe@example.com'"):
            client.login('admin', session_id='BROWSER')
        self.assertFalse([*client._http._cookies])
        self.assertIsNone(client.env.uid)
        self.assertOutput('')

    def test_switch_user(self):
        client = odooly.Client(self.server, self.database, session_id='BROWSER')
        shared_env = client.env

        # Password login does not reuse the shared session
        client.login('admin', 'admin')
        self.assertEqual(self.requests[-1], ('/web/session/authenticate', None))
        self.assertEqual(client.env['res.partner'].search([]).ids, [2])
        self.assertEqual(self.requests[-1][1], 'OWN')

        # Back to the shared session
        self.assertEqual(shared_env['res.partner'].search([]).ids, [self.uid])
        self.assertEqual(self.requests[-1][1], 'BROWSER')
        self.assertEqual(client.login(self.user), self.uid)
        # Attached again through Env.session_authenticate
        self.assertOutput(f"Session authenticated for {self.user!r}\n")

        # Back to the password user: its session is reused
        self.requests.clear()
        self.assertEqual(client.login('admin'), 2)
        self.assertEqual(client.env['res.partner'].search([]).ids, [2])
        self.assertEqual(self.requests, [
            ('/web/session/get_session_info', 'OWN'),
            ('/web/dataset/call_kw/res.partner/search', 'OWN'),
        ])
        self.assertOutput('')

    def test_destroy_own_session(self):
        client = odooly.Client(self.server, self.database, 'admin', 'admin')
        env = client.env
        self.assertEqual(env.context, {'lang': 'en_US', 'uid': 2})
        self.assertEqual(env['res.partner'].search([]).ids, [2])
        env.session_destroy()
        self.assertNotIn('OWN', self.sessions)
        self.assertOutput('')

        # Authenticate again with the password, the destroyed session is not reused
        self.requests.clear()
        self.assertEqual(env['res.partner'].search([]).ids, [2])
        self.assertEqual(self.requests, [
            ('/web/session/get_session_info', 'OWN'),
            ('/web/session/authenticate', None),
            ('/web/dataset/call_kw/res.partner/search', 'OWN'),
        ])
        self.assertEqual(env._cache_get('auth')['admin'], (2, 'admin', 'OWN'))
        self.assertNotIn('__session_id', env.session_info)
        self.assertOutput("Session authenticated for 'admin'\n")

    def test_sudo_own_session(self):
        client = odooly.Client(self.server, self.database, 'admin', 'admin')
        admin_env = client.env
        self.assertEqual(client.env.sudo('__system__').uid, 1)
        self.assertEqual(self.sessions['OWN']['uid'], 1)  # Superuser

        # The environment authenticates again with the password
        self.requests.clear()
        self.assertEqual(admin_env['res.partner'].search([]).ids, [2])
        self.assertEqual(self.requests[:2], [
            ('/web/session/get_session_info', 'OWN'),
            ('/web/session/authenticate', None),
        ])
        self.assertEqual(self.requests[-1], ('/web/dataset/call_kw/res.partner/search', 'OWN'))
        self.assertOutput("Session authenticated for 'admin'\n")
        # Become Superuser again: the fake server reuses the id 'OWN' for the
        # new session, so the saved Superuser session id is stale
        self.assertEqual(client.env.sudo('__system__').uid, 1)
        self.assertOutput("Session authenticated for 'admin'\n")

        # The session is now Superuser: authenticate again with the password
        self.requests.clear()
        self.assertEqual(client.login('admin'), 2)
        self.assertEqual(self.requests, [
            ('/web/session/get_session_info', 'OWN'),
            ('/web/session/authenticate', None),
        ])
        self.assertEqual(self.sessions['OWN']['uid'], 2)
        self.assertOutput('')

    def test_sudo_shared_session(self):
        client = odooly.Client(self.server, self.database, session_id='BROWSER')
        shared_env = client.env
        client.login('admin', 'admin')
        self.assertEqual(client.env['res.partner'].search([]).ids, [2])

        # sudo() starts from the session of shared_env, and warns about the browser
        system_env = shared_env.sudo()
        self.assertEqual(system_env.uid, 1)
        self.assertIn(('/web/become', 'BROWSER'), self.requests)
        self.assertEqual(self.sessions['BROWSER']['uid'], 1)  # Superuser
        self.assertEqual(self.sessions['OWN']['uid'], 2)
        self.assertOutput(f"Session authenticated for {self.user!r}\n"
                          "Session is now Superuser.  To undo: env.session_destroy()\n")

        # The Superuser session is reused, without /web/become again
        self.assertEqual(client.env['res.partner'].search([]).ids, [2])
        self.requests.clear()
        self.assertEqual(system_env['res.partner'].search([]).ids, [1])
        self.assertEqual(self.requests, [
            ('/web/session/get_session_info', 'BROWSER'),
            ('/web/dataset/call_kw/res.partner/search', 'BROWSER'),
        ])

        # The shared user cannot go back to its session
        with self.assertRaisesRegex(odooly.Error, "Session of 'jdoe@example.com' is now Superuser"):
            client.login(self.user)

        # Undo: terminate the session
        shared_env.session_destroy()
        self.assertNotIn('BROWSER', self.sessions)
        self.assertIn('OWN', self.sessions)
        with self.assertRaisesRegex(odooly.Error, 'Superuser session is terminated'):
            system_env['res.partner'].search([]).ids
        self.assertOutput("Session authenticated for 'admin'\n")

    def test_destroy_session_of_env(self):
        client = odooly.Client(self.server, self.database, session_id='BROWSER')
        shared_env = client.env
        client.login('admin', 'admin')
        admin_env = client.env
        self.assertEqual(shared_env['res.partner'].search([]).ids, [self.uid])

        # The BROWSER session is attached, but OWN is terminated
        admin_env.session_destroy()
        self.assertEqual(set(self.sessions), {'BROWSER'})
        self.assertEqual(self.requests[-2:], [
            ('/web/session/get_session_info', 'OWN'),
            ('/web/session/destroy', 'OWN'),
        ])
        admin_env.session_destroy()  # Already terminated
        self.assertEqual(set(self.sessions), {'BROWSER'})
        self.assertOutput(f"Session authenticated for {self.user!r}\n")

    def test_destroy_shared_session(self):
        mock.patch('odooly.environment.getpass', side_effect=EOFError).start()
        client = odooly.Client(self.server, self.database, session_id='BROWSER')
        env = client.env

        self.assertIsNone(env.session_destroy())
        self.assertNotIn('BROWSER', self.sessions)
        self.assertFalse([*client._http._cookies])
        self.assertOutput('')

        # The browser is logged out: a password is needed
        self.assertRaises(EOFError, env._get, 'res.partner')
        self.assertEqual(self.requests[-1], ('/web/session/get_session_info', 'BROWSER'))
        paths = {path for (path, sid) in self.requests}
        self.assertFalse(paths & {'/web/session/authenticate', '/web/login', '/web/become'})

    def test_connect_client(self):
        args = odooly.run.get_parser().parse_args([self.server, '--session-id', 'BROWSER'])
        client = odooly.run.connect_client(args)
        self.assertEqual(client.env.uid, self.uid)
        self.assertEqual(client.env.user.login, self.user)

        args = odooly.run.get_parser().parse_args(
            [self.server, '-u', 'admin', '--session-id', 'BROWSER'])
        with self.assertRaises(SystemExit):
            odooly.run.connect_client(args)
        self.assertIn("Session is bound to user 'jdoe@example.com'", self.stdout.popvalue())
        self.assertOutput('')

    def test_from_config(self):
        env_tuple = (self.server, self.database, 'jdoe', None, None)
        mock.patch('odooly.run.InteractiveClient.get_config', return_value=env_tuple).start()

        client = odooly.run.InteractiveClient.from_config('prod', session_id='BROWSER')
        self.assertEqual(client.env.uid, self.uid)
        self.assertEqual(client.env.name, 'prod')
        self.assertEqual(client._saved_config['prod'][2], self.user)
        self.assertOutput('')


class TestAnonymousSession(FakeOdooTestCase):
    """Database is bound to an anonymous session."""
    server_version = '20.0'

    def fake_odoo(self):
        server = FakeOdoo(self.server_version, databases=['demo1', 'demo2'], list_db=False)
        # Session cookie received on first visit, e.g. redirect to /odoo
        server.sessions['ANON'] = {'uid': None, 'login': None, 'db': 'demo2'}
        return server

    def test_login_keeps_anonymous_session(self):
        client = odooly.Client(self.server)
        client._http.set_cookie(self.server, 'session_id', 'ANON')
        client.login('demo', 'demo')

        self.assertEqual(client.env.uid, 6)
        self.assertEqual(client.env.db_name, 'demo2')
        self.assertIn(('/web', 'ANON'), self.odoo_server.requests)
        self.assertOutput('')


class TestHTTPSessionCookie(TestCase):

    def test_set_cookie(self):
        http = odooly.http.HTTPSession()
        http.set_cookie('https://odoo.example.com/web', 'session_id', 'abc')
        http.set_cookie('https://odoo.example.com/web', 'session_id', 'xyz')
        http.set_cookie('http://localhost:8069/web', 'session_id', 'loc')
        self.assertEqual(sorted((c.domain, c.value) for c in http._cookies),
                         [('localhost.local', 'loc'), ('odoo.example.com', 'xyz')])

        http.set_cookie('https://odoo.example.com/web', 'session_id', None)
        http.set_cookie('https://odoo.example.com/web', 'session_id', None)
        self.assertEqual([c.value for c in http._cookies], ['loc'])

    def test_get_cookie(self):
        http = odooly.http.HTTPSession()
        self.assertIsNone(http.get_cookie('https://odoo.example.com/web', 'session_id'))

        # A cookie with another path is ignored, like in set_cookie
        http._cookies.set_cookie(Cookie(
            0, 'session_id', 'other', None, False, 'odoo.example.com', False, False,
            '/odoo', True, False, None, True, None, None, {}))
        self.assertIsNone(http.get_cookie('https://odoo.example.com/web', 'session_id'))

        http.set_cookie('https://odoo.example.com/web', 'session_id', 'abc')
        http.set_cookie('http://localhost:8069/web', 'session_id', 'loc')
        self.assertEqual(http.get_cookie('https://odoo.example.com/', 'session_id'), 'abc')
        self.assertEqual(http.get_cookie('http://localhost:8069/', 'session_id'), 'loc')
        self.assertIsNone(http.get_cookie('https://odoo.example.com/', 'other'))
        self.assertIsNone(http.get_cookie('https://example.com/', 'session_id'))


class TestHTTPSessionError(TestCase):

    def test_html_error_page(self):
        # Werkzeug error page
        page = ('<!doctype html>\n<html lang=en>\n<title>404 Not Found</title>\n'
                '<h1>Not Found</h1>\n<p>The requested URL was not found on the server.</p>\n')
        http = odooly.http.HTTPSession()
        mock.patch.object(http, '_request', side_effect=OSError).start()
        mock.patch.object(http, '_parse_error', return_value=(404, page)).start()
        stdout = mock.patch('sys.stdout', new=PseudoFile()).start()
        self.addCleanup(mock.patch.stopall)

        with self.assertRaises(odooly.ServerError) as cm:
            http.request('http://odoo.example.com/report/pdf/missing')
        self.assertEqual(cm.exception.args[0], {'code': 404, 'data': {
            'name': 'OSError', 'debug': None,
            'arguments': ('404 Not Found - The requested URL was not found on the server.',)}})
        self.assertEqual(stdout.popvalue(), '')

        # The HTML page is printed with ODOOLY_DEBUG
        # Not started: Python 3.8 'mock.patch.stopall()' does not stop 'patch.dict'
        with mock.patch.dict('os.environ', {'ODOOLY_DEBUG': '1'}), \
                self.assertRaises(odooly.ServerError):
            http.request('http://odoo.example.com/report/pdf/missing')
        self.assertEqual(stdout.popvalue(), page + '\n')
