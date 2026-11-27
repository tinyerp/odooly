"""Test the local mode: the Odoo server runs in the same process."""
import sys
import types
from pathlib import Path
from unittest import mock

import odooly
import odooly.run
from odooly.service import LocalDatabase

from ._common import OdooTestCase

OPTIONS = ['-c', '/etc/odoo/odoo.conf']
MASTER_PWD = 'master'


class _TestLocal(OdooTestCase):
    """Fake 'odoo' package, with the RPC services used by odooly."""
    server = None
    version_info = None
    databases = ('db1', 'db2')
    users = {'admin': (2, 'admin'), 'demo': (6, 'demo')}

    def setUp(self):
        super().setUp()
        self.databases = [*self.databases]
        self.odoo = self._fake_odoo()
        mock.patch('odooly.service.atexit.register').start()
        self.putenv = mock.patch('odooly.service.os.putenv').start()

    def _fake_odoo(self):
        """Odoo >= 19 does not import the sub-packages: each one is registered."""
        names = ['odoo', 'odoo.api', 'odoo.http', 'odoo.modules', 'odoo.modules.registry',
                 'odoo.release', 'odoo.service', 'odoo.service.common', 'odoo.service.db',
                 'odoo.service.model', 'odoo.sql_db', 'odoo.tools']
        modules = {name: types.ModuleType(name) for name in names}
        for name, module in modules.items():
            if '.' in name:
                (parent, child) = name.rsplit('.', 1)
                setattr(modules[parent], child, module)
        odoo = modules['odoo']
        odoo.release.version_info = self.version_info
        odoo.tools.config = mock.Mock(name='config')
        odoo.modules.registry.Registry = mock.Mock(name='Registry')
        # A new cursor for each call
        odoo.modules.registry.Registry.return_value.cursor.side_effect = mock.Mock
        odoo.api.Environment = mock.MagicMock(name='Environment')
        odoo.http.dispatch_rpc = mock.Mock(side_effect=self._dispatch_rpc)
        mock.patch.dict('sys.modules', modules).start()
        return odoo

    def _dispatch_rpc(self, service, method, params):
        if service == 'common':
            if method == 'version':
                return {'server_version': f'{self.version_info[0]}.0'}
            assert method == 'login'
            (db, login, password) = params
            (uid, user_password) = self.users.get(login, (False, None))
            return uid if (db in self.databases and password == user_password) else False
        if service == 'db':
            if method == 'list':
                return [*self.databases]
            if params[0] != MASTER_PWD:
                raise Exception('Access Denied')  # Raw odoo.exceptions.AccessDenied
            if method == 'create_database':
                self.databases.append(params[1])
            elif method == 'duplicate_database':
                self.databases.append(params[2])
            elif method == 'drop':
                self.databases.remove(params[1])
            return True
        assert (service, method) == ('object', 'execute_kw')
        (db, uid, password, model, method, args) = params[:6]
        results = {
            ('res.users', 'context_get'): {'lang': 'en_US', 'tz': 'Europe/Zurich'},
            ('ir.model', 'fields_get'): {},
            ('ir.model', 'search_read'): [{'model': 'res.users', 'transient': False}],
            ('res.users', 'search_count'): len(self.users),
            ('res.users', 'search'): [uid for (uid, __) in self.users.values()],
        }
        return results[model, method]

    def rpc_calls(self):
        """Return (service, method, db, login or uid[, model, method]) of the RPC calls."""
        calls = [(c.args[0], c.args[1], *c.args[2][:2], *c.args[2][3:5])
                 for c in self.odoo.http.dispatch_rpc.mock_calls]
        self.odoo.http.dispatch_rpc.reset_mock()
        return calls

    def test_start_odoo_services(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        self.assertIs(client._server, self.odoo)
        self.odoo.tools.config.parse_config.assert_called_once_with(OPTIONS)
        self.assertIs(self.odoo._get_pool, self.odoo.modules.registry.Registry)
        self.assertEqual(self.putenv.mock_calls, [mock.call('TZ', 'UTC'),
                                                  mock.call('PGAPPNAME', 'odooly')])

        # The services are started once
        odooly.Client(['-c', '/other.conf'], 'db1', 'admin', 'admin')
        self.odoo.tools.config.parse_config.assert_called_once_with(OPTIONS)
        self.assertOutput('')

    def test_login(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        self.assertEqual(client.version_info, float(self.version_info[0]))
        self.assertIsNone(client.web)
        self.assertIsInstance(client.database, LocalDatabase)
        self.assertEqual(client.env.uid, 2)
        self.assertEqual(client.env._execute_kw._protocol_name, 'Odoo')
        self.assertEqual(client.env['res.users'].search_count([]), 2)
        self.assertEqual(self.rpc_calls(), [
            ('common', 'version'),
            ('db', 'list'),
            ('common', 'login', 'db1', 'admin'),
            ('object', 'execute_kw', 'db1', 2, 'res.users', 'context_get'),
            ('object', 'execute_kw', 'db1', 2, 'res.users', 'search_count'),
        ])
        self.assertOutput('')

    def test_select_database(self):
        client = odooly.Client(OPTIONS)
        with self.assertRaisesRegex(odooly.Error, r"Database '' does not exist: \['db1', 'db2'\]"):
            client.login('admin', 'admin')
        with self.assertRaisesRegex(odooly.Error, "Database 'db3' does not exist"):
            client.login('admin', 'admin', database='db3')

        # Only one database: it is selected
        self.databases.remove('db2')
        self.assertEqual(client.login('admin', 'admin'), 2)
        self.assertEqual(client.env.db_name, 'db1')
        self.assertOutput('')

    def test_switch_database(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        client.login('demo', 'demo', database='db2')
        self.assertEqual((client.env.db_name, client.env.uid), ('db2', 6))
        client.login('admin', 'admin', database='db1')
        self.assertEqual((client.env.db_name, client.env.uid), ('db1', 2))
        self.assertOutput('')

    def test_create_clone_drop_database(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        self.rpc_calls()

        client.create_database(MASTER_PWD, 'db3', user_password='admin')
        client.create_database(MASTER_PWD, 'db4', user_password='admin', country_code='CH')
        client.clone_database(MASTER_PWD, 'db5')
        client.drop_database(MASTER_PWD, 'db3')
        self.assertEqual(self.databases, ['db1', 'db2', 'db4', 'db5'])
        db_calls = [c.args[1:] for c in self.odoo.http.dispatch_rpc.mock_calls
                    if c.args[0] == 'db' and c.args[1] != 'list']
        self.assertEqual(db_calls, [
            # Optional arguments are not sent, for old versions
            ('create_database', (MASTER_PWD, 'db3', False, 'en_US', 'admin', 'admin')),
            ('create_database', (MASTER_PWD, 'db4', False, 'en_US', 'admin', 'admin', 'CH')),
            ('duplicate_database', (MASTER_PWD, 'db4', 'db5')),
            ('drop', (MASTER_PWD, 'db3')),
        ])
        self.assertEqual(client.env.db_name, 'db5')

        # Odoo exceptions are not converted
        with self.assertRaisesRegex(Exception, 'Access Denied'):
            client.drop_database('wrong', 'db4')
        self.assertOutput('')

    def test_verbose_hides_passwords(self):
        client = odooly.run.InteractiveClient(OPTIONS, 'db1', 'admin', 'admin', verbose=True)
        client.drop_database(MASTER_PWD, 'db2')
        output = self.stdout.popvalue()
        self.assertIn("common.login('db1', 'admin', '*')", output)
        self.assertIn("db.drop('*', 'db2')", output)
        self.assertNotIn(MASTER_PWD, output)
        self.assertOutput('')

    def test_webclient_only(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        env = client.env
        with self.assertRaisesRegex(odooly.Error, 'Webclient session is needed'):
            env.sudo('__system__')
        with self.assertRaisesRegex(odooly.Error, 'Webclient session is needed'):
            env.session_authenticate()
        with self.assertRaisesRegex(odooly.Error, 'Webclient session is needed'):
            env['res.users'].browse(2).render_pdf('base.report_users')
        with self.assertRaisesRegex(odooly.Error, 'Invalid or expired session'):
            client.login(None, session_id='abc')
        self.assertIsNone(env.session_destroy())
        self.assertEqual(env.sudo().uid, 2)  # Default: the admin user
        self.assertOutput('')

    def test_cursor(self):
        client = odooly.Client(OPTIONS, 'db1', 'admin', 'admin')
        env = client.env
        registry = self.odoo.modules.registry.Registry
        self.assertIs(env.registry, registry.return_value)
        registry.assert_called_with('db1')

        # The cursor is kept on the Env
        cr = env.cr
        self.assertIs(env.cr, cr)
        self.assertEqual(registry.return_value.cursor.call_count, 1)

        # Another Env has its own cursor: another transaction
        self.assertIsNot(env(context={'lang': 'fr_FR'}).cr, cr)
        self.assertEqual(registry.return_value.cursor.call_count, 2)
        self.assertOutput('')

    def test_odoo_env(self):
        env = odooly.Client(OPTIONS, 'db1', 'admin', 'admin').env
        odoo_env = env.odoo_env
        self.assertIs(odoo_env, self.odoo.api.Environment.return_value)
        self.odoo.api.Environment.assert_called_once_with(env.cr, 2, env.context)

        env_fr = env(context={'lang': 'fr_FR'})
        env_fr.odoo_env
        self.odoo.api.Environment.assert_called_with(env_fr.cr, 2, {'lang': 'fr_FR'})
        self.assertOutput('')

    def test_with_odoo(self):
        env = odooly.Client(OPTIONS, 'db1', 'admin', 'admin').env
        odoo_env = self.odoo.api.Environment.return_value
        odoo_model = odoo_env.__getitem__.return_value
        self.assertIs(env['res.users'].with_odoo(), odoo_model)
        odoo_env.__getitem__.assert_called_with('res.users')

        self.assertIs(env['res.users'].browse(2).with_odoo(), odoo_model.browse.return_value)
        env['res.users'].browse([2, 6]).with_odoo()
        self.rpc_calls()
        env['res.users'].search([]).with_odoo()  # The search is executed first
        self.assertEqual(self.rpc_calls(), [
            ('object', 'execute_kw', 'db1', 2, 'res.users', 'search'),
        ])
        browse_args = [c.args for c in odoo_model.browse.call_args_list]
        self.assertEqual(browse_args, [([2],), ([2, 6],), ([2, 6],)])
        # Odoo needs plain integers
        self.assertEqual({type(i) for (ids,) in browse_args for i in ids}, {int})
        self.assertOutput('')

    def test_from_config(self):
        configs = {
            'local1': (OPTIONS, 'db1', 'admin', 'admin', None),
            'local2': (OPTIONS, 'db2', 'demo', 'demo', None),
        }
        mock.patch('odooly.run.InteractiveClient.get_config', side_effect=configs.get).start()

        client = odooly.run.InteractiveClient.from_config('local1')
        self.assertEqual((client.env.db_name, client.env.uid), ('db1', 2))
        client2 = odooly.run.InteractiveClient.from_config('local2')
        self.assertEqual((client2.env.db_name, client2.env.uid), ('db2', 6))

        # The cached client is reused, and it switches back to its database
        client.login('demo', 'demo', database='db2')
        self.assertIs(odooly.run.InteractiveClient.from_config('local1'), client)
        self.assertEqual((client.env.db_name, client.env.uid), ('db1', 2))
        # The local server is started once
        self.odoo.tools.config.parse_config.assert_called_once_with(OPTIONS)
        self.assertOutput('')

    def test_connect_client_config(self):
        args = odooly.run.get_parser().parse_args(
            ['-c', 'odoo.conf', '-d', 'db1', '-u', 'admin', '-p', 'admin'])
        self.assertIsInstance(args.config, Path)
        client = odooly.run.connect_client(args)
        self.assertEqual(client.env.uid, 2)
        # Odoo receives strings
        self.odoo.tools.config.parse_config.assert_called_once_with(['-c', 'odoo.conf'])
        self.assertOutput('')


class TestLocal18(_TestLocal):
    version_info = (18, 0, 0, 'final', 0, '')


class TestLocal19(_TestLocal):
    version_info = (19, 0, 0, 'final', 0, '')


del _TestLocal
