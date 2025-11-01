import sys

from unittest import mock
from unittest.mock import call, ANY

import odooly
from ._common import XmlRpcTestCase


class TestInteract(XmlRpcTestCase):
    server_version = '6.1'
    server = f"{XmlRpcTestCase.server}/xmlrpc"
    startup_calls = (
        call(ANY, 'db', ANY),
        'db.server_version',
        call(ANY, 'db', ANY),
        call(ANY, 'common', ANY),
        call(ANY, 'object', ANY),
        call(ANY, 'report', ANY),
        call(ANY, 'wizard', ANY),
        'db.list',
    )

    def setUp(self):
        super().setUp()
        # Hide readline module
        mock.patch.dict('sys.modules', {'readline': None}).start()
        mock.patch('odooly.Client._globals', None).start()
        mock.patch('odooly.Client._set_interactive', wraps=odooly.Client._set_interactive).start()
        self.interact = mock.patch('odooly._interact', wraps=odooly._interact).start()
        self.infunc = mock.patch('code.InteractiveConsole.raw_input').start()
        mock.patch('odooly.main.__defaults__', (self.interact,)).start()

    def test_main(self):
        env_tuple = (self.server, 'database', 'usr', None, None)
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        read_config = mock.patch('odooly.Client.get_config',
                                 return_value=env_tuple).start()
        getpass = mock.patch('odooly.getpass',
                             return_value='password').start()
        self.service.db.list.return_value = ['database']
        self.service.common.login.side_effect = [17, 51]
        self.service.object.execute_kw.side_effect = [{}, {}, {}]

        # Launch interactive
        self.infunc.side_effect = [
            "client\n",
            "env\n",
            "env.sudo('gaspard')\n",
            "client.login('gaspard')\n",
            "23 + 19\n",
            EOFError('Finished')]
        odooly.main()

        self.assertEqual(sys.ps1, 'demo >>> ')
        self.assertEqual(sys.ps2, '     ... ')
        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'password'),
            ('object.execute_kw', 'database', 17, 'password', 'res.users', 'context_get', ()),
            ('common.login', 'database', 'gaspard', 'password'),
            ('object.execute_kw', 'database', 51, 'password', 'res.users', 'context_get', ()),
            ('object.execute_kw', 'database', 51, 'password', 'res.users', 'context_get', ()),
        )
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 2)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(self.interact.call_count, 1)
        outlines = self.stdout.popvalue().splitlines()
        self.assertSequenceEqual(outlines[-6:], [
            "Logged in as 'usr'",
            f"<Client '{self.server}?db=database'>",
            "<Env 'usr@database'>",
            "<Env 'gaspard@database'>",
            "Logged in as 'gaspard'",
            "42",
        ])
        self.assertOutput(stderr='\x1b[A\n\n', startswith=True)

    def test_no_database(self):
        env_tuple = (self.server, 'missingdb', 'usr', None, None)
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        mock.patch('odooly.getpass', return_value='xyz').start()
        read_config = mock.patch('odooly.Client.get_config',
                                 return_value=env_tuple).start()
        self.service.db.list.return_value = ['database']

        # Launch interactive
        self.infunc.side_effect = [
            "client\n",
            "env\n",
            "env.sudo('gaspard')\n",
            "client.login('gaspard')\n",
            EOFError('Finished')]
        odooly.main()

        expected_calls = self.startup_calls + (
            "db.list",
            ('common.login', 'database', 'gaspard', 'xyz'),
        )
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        outlines = self.stdout.popvalue().splitlines()
        self.assertSequenceEqual(outlines[-5:], [
            "Database 'missingdb' does not exist: ['database']",
            f"<Client '{self.server}?db='>",
            "<Env '@()'>",
            "Error: Not connected",
            "Error: Invalid username or password",
        ])
        self.assertOutput(stderr=ANY)

    def test_invalid_user_password(self):
        env_tuple = (self.server, 'database', 'usr', 'passwd', None)
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        mock.patch('os.environ', new={'LANG': 'fr_FR.UTF-8'}).start()
        mock.patch('odooly.Client.get_config', return_value=env_tuple).start()
        mock.patch('odooly.getpass', return_value='x').start()
        self.service.db.list.return_value = ['database']
        self.service.common.login.side_effect = [17, None]
        self.service.object.execute_kw.side_effect = [{}, True, 42, {}, 42, {}, 42]

        # Launch interactive
        self.infunc.side_effect = [
            "env['res.company']\n",
            "client.login('gaspard')\n",
            "env['res.company']\n",
            EOFError('Finished')]
        odooly.main()

        def usr17(model, method, *params):
            return ('object.execute_kw', 'database', 17, 'passwd', model, method, params)

        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'passwd'),
            ('object.execute_kw', 'database', 17, 'passwd', 'res.users', 'context_get', ()),
            ('object.execute_kw', 'database', 17, 'passwd', 'ir.model.access', 'check', ('ir.model', 'read')),
            usr17('ir.model', 'search',
                  [('model', 'like', 'res.company')]),
            usr17('ir.model', 'read', 42, ('model',)),
            ('common.login', 'database', 'gaspard', 'x'),
            usr17('ir.model', 'search',
                  [('model', 'like', 'res.company')]),
            usr17('ir.model', 'read', 42, ('model',)),
        )
        self.assertCalls(*expected_calls)
        outlines = self.stdout.popvalue().splitlines()
        self.assertSequenceEqual(outlines[-4:], [
            "Logged in as 'usr'",
            'Model not found: res.company',
            'Error: Invalid username or password',
            'Model not found: res.company',
        ])
        self.assertOutput(stderr=ANY)
