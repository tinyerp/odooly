# -*- coding: utf-8 -*-
import mock
from mock import call, sentinel, ANY

import odooly
from ._common import XmlRpcTestCase, OBJ

AUTH = sentinel.AUTH
ID1, ID2 = 4001, 4002
STABLE = ['uninstallable', 'uninstalled', 'installed']


def _skip_test(test_case):
    pass


def imm(method, *params):
    return ('object.execute_kw', AUTH, 'ir.module.module', method, params)


def bmu(method, *params):
    return ('object.execute_kw', AUTH, 'base.module.upgrade', method, params)


class IdentDict(object):
    def __init__(self, _id):
        self._id = _id

    def __repr__(self):
        return 'IdentDict(%s)' % (self._id,)

    def __getitem__(self, key):
        return (key == 'id') and self._id or ('v_%s_%s' % (key, self._id))

    def __eq__(self, other):
        return self._id == other._id
DIC1 = IdentDict(ID1)
DIC2 = IdentDict(ID2)


class TestService(XmlRpcTestCase):
    """Test the Service class."""
    protocol = 'xmlrpc'

    def _patch_service(self):
        return mock.patch('odooly.ServerProxy._ServerProxy__request').start()

    def _get_client(self):
        client = mock.Mock()
        client._server = 'http://127.0.0.1:8069/%s' % self.protocol
        proxy = getattr(odooly.Client, '_proxy_%s' % self.protocol)
        client._proxy = proxy.__get__(client, odooly.Client)
        return client

    def test_service(self):
        client = self._get_client()
        svc_alpha = odooly.Service(client, 'alpha', ['beta'])

        self.assertIn('alpha', str(svc_alpha.beta))
        self.assertRaises(AttributeError, getattr, svc_alpha, 'theta')
        if self.protocol == 'xmlrpc':
            self.assertIn('_ServerProxy__request', str(svc_alpha.beta(42)))
            self.assertCalls(call('beta', (42,)), "().__str__")
        else:
            self.assertCalls()
        self.assertOutput('')

    def test_service_openerp(self):
        client = self._get_client()

        def get_proxy(name, methods=None):
            if methods is None:
                methods = odooly._methods.get(name, ())
            return odooly.Service(client, name, methods, verbose=False)

        self.assertIn('common', str(get_proxy('common').login))
        login = get_proxy('common').login('aaa')
        with self.assertRaises(AttributeError):
            get_proxy('common').non_existent
        if self.protocol == 'xmlrpc':
            self.assertIn('_ServerProxy__request', str(login))
            self.assertCalls(call('login', ('aaa',)), 'call().__str__')
        else:
            self.assertEqual(login, 'JSON_RESULT',)
            self.assertCalls(ANY)
        self.assertOutput('')

    def test_service_openerp_client(self, server_version=11.0):
        server = 'http://127.0.0.1:8069/%s' % self.protocol
        return_values = [str(server_version), ['newdb'], 1]
        if self.protocol == 'jsonrpc':
            return_values = [{'result': rv} for rv in return_values]
        self.service.side_effect = return_values
        client = odooly.Client(server, 'newdb', 'usr', 'pss')

        self.service.return_value = ANY
        self.assertIsInstance(client.db, odooly.Service)
        self.assertIsInstance(client.common, odooly.Service)
        self.assertIsInstance(client._object, odooly.Service)
        if server_version >= 11.0:
            self.assertIs(client._report, None)
            self.assertIs(client._wizard, None)
        elif server_version >= 7.0:
            self.assertIsInstance(client._report, odooly.Service)
            self.assertIs(client._wizard, None)
        else:
            self.assertIsInstance(client._report, odooly.Service)
            self.assertIsInstance(client._wizard, odooly.Service)

        self.assertIn('/%s|db' % self.protocol, str(client.db.create_database))
        self.assertIn('/%s|db' % self.protocol, str(client.db.db_exist))
        if server_version >= 8.0:
            self.assertRaises(AttributeError, getattr,
                              client.db, 'create')
            self.assertRaises(AttributeError, getattr,
                              client.db, 'get_progress')
        else:
            self.assertIn('/%s|db' % self.protocol, str(client.db.create))
            self.assertIn('/%s|db' % self.protocol, str(client.db.get_progress))

        self.assertCalls(ANY, ANY, ANY)
        self.assertOutput('')

    def test_service_openerp_61_to_70(self):
        self.test_service_openerp_client(server_version=7.0)
        self.test_service_openerp_client(server_version=6.1)

    def test_service_odoo_80_90(self):
        self.test_service_openerp_client(server_version=9.0)
        self.test_service_openerp_client(server_version=8.0)

    def test_service_odoo_10_11(self):
        self.test_service_openerp_client(server_version=11.0)
        self.test_service_openerp_client(server_version=10.0)


class TestServiceJsonRpc(TestService):
    """Test the Service class with JSON-RPC."""
    protocol = 'jsonrpc'

    def _patch_service(self):
        return mock.patch('odooly.http_post', return_value={'result': 'JSON_RESULT'}).start()


class TestCreateClient(XmlRpcTestCase):
    """Test the Client class."""
    server_version = '6.1'
    startup_calls = (
        call(ANY, 'db', ANY, verbose=ANY),
        'db.server_version',
        call(ANY, 'db', ANY, verbose=ANY),
        call(ANY, 'common', ANY, verbose=ANY),
        call(ANY, 'object', ANY, verbose=ANY),
        call(ANY, 'report', ANY, verbose=ANY),
        call(ANY, 'wizard', ANY, verbose=ANY),
        'db.list',
    )

    def test_create(self):
        self.service.db.list.return_value = ['newdb']
        self.service.common.login.return_value = 1

        client = odooly.Client('http://127.0.0.1:8069', 'newdb', 'usr', 'pss')
        expected_calls = self.startup_calls + (
            ('common.login', 'newdb', 'usr', 'pss'),)
        url_xmlrpc = 'http://127.0.0.1:8069/xmlrpc'
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(
            client.env._cache,
            {('_auth', 'newdb', url_xmlrpc): {1: (1, 'pss'),
                                              'usr': (1, 'pss')},
             ('model_names', 'newdb', url_xmlrpc): {'res.users'}})
        self.assertOutput('')

    def test_create_getpass(self):
        getpass = mock.patch('getpass.getpass',
                             return_value='password').start()
        self.service.db.list.return_value = ['database']
        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'password'),)

        # A: Invalid login
        self.assertRaises(odooly.Error, odooly.Client,
                          'http://127.0.0.1:8069', 'database', 'usr')
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 1)

        # B: Valid login
        self.service.common.login.return_value = 17
        getpass.reset_mock()

        client = odooly.Client('http://127.0.0.1:8069', 'database', 'usr')
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 1)

    def test_create_with_cache(self):
        self.service.db.list.return_value = ['database']
        self.assertFalse(odooly.Env._cache)
        url_xmlrpc = 'http://127.0.0.1:8069/xmlrpc'
        mock.patch.dict(odooly.Env._cache,
                        {('_auth', 'database', url_xmlrpc): {'usr': (1, 'password')}}).start()

        client = odooly.Client('http://127.0.0.1:8069', 'database', 'usr')
        expected_calls = self.startup_calls + (
            ('object.execute', 'database', 1, 'password',
             'ir.model', 'fields_get', [None]),)
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertOutput('')

    def test_create_from_config(self):
        env_tuple = ('http://127.0.0.1:8069', 'database', 'usr', None)
        read_config = mock.patch('odooly.read_config',
                                 return_value=env_tuple).start()
        getpass = mock.patch('getpass.getpass',
                             return_value='password').start()
        self.service.db.list.return_value = ['database']
        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'password'),)

        # A: Invalid login
        self.assertRaises(odooly.Error, odooly.Client.from_config, 'test')
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(getpass.call_count, 1)

        # B: Valid login
        self.service.common.login.return_value = 17
        read_config.reset_mock()
        getpass.reset_mock()

        client = odooly.Client.from_config('test')
        self.assertIsInstance(client, odooly.Client)
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(getpass.call_count, 1)

    def test_create_invalid(self):
        # Without mock
        self.service.stop()

        self.assertRaises(EnvironmentError, odooly.Client, 'dsadas')
        self.assertOutput('')


class TestSampleSession(XmlRpcTestCase):
    server_version = '6.1'
    server = 'http://127.0.0.1:8069'
    database = 'database'
    user = 'user'
    password = 'passwd'
    uid = 1

    def test_simple(self):
        self.service.object.execute_kw.side_effect = [
            4, 71, [{'model': 'ir.cron'}], sentinel.IDS, sentinel.CRON]

        res_users = self.env['res.users']
        self.assertEqual(res_users.search_count(), 4)
        self.assertEqual(self.env['ir.cron'].read(
            ['active = False'], 'active function'), sentinel.CRON)
        self.assertCalls(
            OBJ('res.users', 'search_count', []),
            OBJ('ir.model', 'search', [('model', 'like', 'ir.cron')]),
            OBJ('ir.model', 'read', 71, ('model',)),
            OBJ('ir.cron', 'search', [('active', '=', False)]),
            OBJ('ir.cron', 'read', sentinel.IDS, ['active', 'function']),
        )
        self.assertOutput('')

    def test_list_modules(self):
        self.service.object.execute_kw.side_effect = [
            ['delivery_a', 'delivery_b'],
            [{'state': 'not installed', 'name': 'dummy'}]]

        modules = self.client.env.modules('delivery')
        self.assertIsInstance(modules, dict)
        self.assertIn('not installed', modules)

        self.assertCalls(
            imm('search', [('name', 'like', 'delivery')]),
            imm('read', ['delivery_a', 'delivery_b'], ['name', 'state']),
        )
        self.assertOutput('')

    def test_module_upgrade(self):
        self.service.object.execute_kw.side_effect = [
            (42, 0), [42], [], ANY, [42],
            [{'id': 42, 'state': ANY, 'name': ANY}], ANY]

        result = self.client.env.upgrade('dummy')
        self.assertIsNone(result)

        self.assertCalls(
            imm('update_list'),
            imm('search', [('name', 'in', ('dummy',))]),
            imm('search', [('state', 'not in', STABLE)]),
            imm('button_upgrade', [42]),
            imm('search', [('state', 'not in', STABLE)]),
            imm('read', [42], ['name', 'state']),
            bmu('upgrade_module', []),
        )
        self.assertOutput(ANY)


class TestClientApi(XmlRpcTestCase):
    """Test the Client API."""
    server_version = '6.1'
    server = 'http://127.0.0.1:8069'
    database = 'database'
    user = 'user'
    password = 'passwd'
    uid = 1

    def obj_exec(self, *args):
        if args[4] == 'search':
            return [ID2, ID1]
        if args[4] == 'read':
            return [IdentDict(res_id) for res_id in args[5][::-1]]
        return sentinel.OTHER

    def test_create_database(self):
        create_database = self.client.create_database
        self.client.db.list.side_effect = [['db1'], ['db2']]

        create_database('abc', 'db1')
        create_database('xyz', 'db2', user_password='secret', lang='fr_FR')

        self.assertCalls(
            call.db.create_database('abc', 'db1', False, 'en_US', 'admin'),
            call.db.list(),
            call.common.login('db1', 'admin', 'admin'),
            call.db.create_database('xyz', 'db2', False, 'fr_FR', 'secret'),
            call.db.list(),
            call.common.login('db2', 'admin', 'secret'),
        )
        self.assertOutput('')

        if float(self.server_version) < 9.0:
            self.assertRaises(odooly.Error, create_database, 'xyz', 'db2', user_password='secret', lang='fr_FR', login='other_login', country_code='CA')
            self.assertRaises(odooly.Error, create_database, 'xyz', 'db2', login='other_login')
            self.assertRaises(odooly.Error, create_database, 'xyz', 'db2', country_code='CA')
            self.assertOutput('')
            return

        # Odoo 9
        self.client.db.list.side_effect = [['db2']]
        create_database('xyz', 'db2', user_password='secret', lang='fr_FR', login='other_login', country_code='CA')

        self.assertCalls(
            call.db.create_database('xyz', 'db2', False, 'fr_FR', 'secret', 'other_login', 'CA'),
            call.db.list(),
            call.common.login('db2', 'other_login', 'secret'),
        )
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

        self.assertTrue(self.client.env.models('foo.bar'))
        self.assertCalls(
            OBJ('ir.model', 'search', [('model', 'like', 'foo.bar')]),
            OBJ('ir.model', 'read', [ID2, ID1], ('model',)),
        )
        self.assertOutput('')

        self.assertRaises(odooly.Error, self.client.env.__getitem__, 'foo.bar')
        self.assertCalls(
            OBJ('ir.model', 'search', [('model', 'like', 'foo.bar')]),
            OBJ('ir.model', 'read', [ID2, ID1], ('model',)),
        )
        self.assertOutput('')

        self.service.object.execute_kw.side_effect = [
            sentinel.IDS, [{'id': 13, 'model': 'foo.bar'}]]
        self.assertIsInstance(self.client.env['foo.bar'], odooly.Model)
        self.assertIs(self.client.env['foo.bar'],
                      odooly.Model(self.client.env, 'foo.bar'))
        self.assertCalls(
            OBJ('ir.model', 'search', [('model', 'like', 'foo.bar')]),
            OBJ('ir.model', 'read', sentinel.IDS, ('model',)),
        )
        self.assertOutput('')

    def test_access(self):
        self.assertTrue(self.client.env.access('foo.bar'))
        self.assertCalls(OBJ('ir.model.access', 'check', 'foo.bar', 'read'))
        self.assertOutput('')

    def test_execute_kw(self):
        execute_kw = self.client.env._execute_kw

        execute_kw('foo.bar', 'any_method', 42)
        execute_kw('foo.bar', 'any_method', [42])
        execute_kw('foo.bar', 'any_method', [13, 17])
        self.assertCalls(
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', 42),
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', [42]),
            ('object.execute_kw', AUTH, 'foo.bar', 'any_method', [13, 17]),
        )
        self.assertOutput('')

    def test_exec_workflow(self):
        exec_workflow = self.client.env.exec_workflow

        self.assertTrue(exec_workflow('foo.bar', 'light', 42))

        self.assertRaises(TypeError, exec_workflow)
        self.assertRaises(TypeError, exec_workflow, 'foo.bar')
        self.assertRaises(TypeError, exec_workflow, 'foo.bar', 'rip')
        self.assertRaises(TypeError, exec_workflow, 'foo.bar', 'rip', 42, None)
        self.assertRaises(AssertionError, exec_workflow, 42, 'rip', 42)
        self.assertRaises(AssertionError, exec_workflow, 'foo.bar', 42, 42)

        self.assertCalls(
            ('object.exec_workflow', AUTH, 'foo.bar', 'light', 42),
        )
        self.assertOutput('')

    def test_wizard(self):
        wizard_create = self.client.env.wizard_create
        wizard_execute = self.client.env.wizard_execute
        self.service.wizard.create.return_value = ID1

        self.assertTrue(wizard_create('foo.bar'))
        wiz_id = wizard_create('billy')
        self.assertTrue(wiz_id)
        self.assertTrue(wizard_execute(wiz_id, {}, 'shake', None))
        self.assertTrue(wizard_execute(42, {}, 'kick', None))

        self.assertCalls(
            ('wizard.create', AUTH, 'foo.bar'),
            ('wizard.create', AUTH, 'billy'),
            ('wizard.execute', AUTH, ID1, {}, 'shake', None),
            ('wizard.execute', AUTH, 42, {}, 'kick', None),
        )
        self.assertOutput('')

    def test_report(self):
        self.assertTrue(self.client.env.report('foo.bar', sentinel.IDS))
        self.assertCalls(
            ('report.report', AUTH, 'foo.bar', sentinel.IDS),
        )
        self.assertOutput('')

    def test_render_report(self):
        self.assertTrue(self.client.env.render_report('foo.bar', sentinel.IDS))
        self.assertCalls(
            ('report.render_report', AUTH, 'foo.bar', sentinel.IDS),
        )
        self.assertOutput('')

    def test_report_get(self):
        self.assertTrue(self.client.env.report_get(ID1))
        self.assertCalls(
            ('report.report_get', AUTH, ID1),
        )
        self.assertOutput('')

    def _module_upgrade(self, button='upgrade'):
        execute_return = [
            [7, 0], [42], [], {'name': 'Upgrade'}, [4, 42, 5],
            [{'id': 4, 'state': ANY, 'name': ANY},
             {'id': 5, 'state': ANY, 'name': ANY},
             {'id': 42, 'state': ANY, 'name': ANY}], ANY]
        action = getattr(self.client.env, button)

        expected_calls = [
            imm('update_list'),
            imm('search', [('name', 'in', ('dummy', 'spam'))]),
            imm('search', [('state', 'not in', STABLE)]),
            imm('button_' + button, [42]),
            imm('search', [('state', 'not in', STABLE)]),
            imm('read', [4, 42, 5], ['name', 'state']),
            bmu('upgrade_module', []),
        ]
        if button == 'uninstall':
            execute_return[3:3] = [[], {'state': {'type': 'selection'}}, ANY]
            expected_calls[3:3] = [
                imm('search', [('id', 'in', [42]),
                               ('state', '!=', 'installed'),
                               ('state', '!=', 'to upgrade'),
                               ('state', '!=', 'to remove')]),
                imm('fields_get'),
                imm('write', [42], {'state': 'to remove'}),
            ]

        self.service.object.execute_kw.side_effect = execute_return
        result = action('dummy', 'spam')
        self.assertIsNone(result)
        self.assertCalls(*expected_calls)

        self.assertIn('to process', self.stdout.popvalue())
        self.assertOutput('')

    def test_module_upgrade(self):
        self._module_upgrade('install')
        self._module_upgrade('upgrade')
        self._module_upgrade('uninstall')


class TestClientApi90(TestClientApi):
    """Test the Client API for Odoo 9."""
    server_version = '9.0'
    test_wizard = _skip_test


class TestClientApi11(TestClientApi):
    """Test the Client API for Odoo 11."""
    server_version = '11.0'
    test_wizard = _skip_test
    test_report = test_render_report = test_report_get = _skip_test
