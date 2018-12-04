# -*- coding: utf-8 -*-
import sys

import mock
from mock import call, ANY

import odooly
from ._common import XmlRpcTestCase


class TestInteract(XmlRpcTestCase):
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

    def setUp(self):
        super(TestInteract, self).setUp()
        # Hide readline module
        mock.patch.dict('sys.modules', {'readline': None}).start()
        mock.patch('odooly.Client._globals', None).start()
        mock.patch('odooly.Client._set_interactive', wraps=odooly.Client._set_interactive).start()
        self.interact = mock.patch('odooly._interact', wraps=odooly._interact).start()
        self.infunc = mock.patch('code.InteractiveConsole.raw_input').start()
        mock.patch('odooly.main.__defaults__', (self.interact,)).start()

    def test_main(self):
        env_tuple = ('http://127.0.0.1:8069', 'database', 'usr', None)
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        read_config = mock.patch('odooly.read_config',
                                 return_value=env_tuple).start()
        getpass = mock.patch('getpass.getpass',
                             return_value='password').start()
        self.service.db.list.return_value = ['database']
        self.service.common.login.return_value = 17
        self.service.object.execute_kw.side_effect = TypeError

        # Launch interactive
        self.infunc.side_effect = [
            "client\n",
            "env\n",
            "client.login('gaspard')\n",
            "23 + 19\n",
            EOFError('Finished')]
        odooly.main()

        # self.assertSequenceEqual(self.stdout.popvalue().splitlines(), [])
        self.assertEqual(sys.ps1, 'demo >>> ')
        self.assertEqual(sys.ps2, 'demo ... ')
        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'password'),
            ('object.execute_kw', 'database', 17, 'password',
             'ir.model.access', 'check', ('res.users', 'write'), {'context': ANY}),
            ('common.login', 'database', 'gaspard', 'password'),
        )
        self.assertCalls(*expected_calls)
        self.assertEqual(getpass.call_count, 2)
        self.assertEqual(read_config.call_count, 1)
        self.assertEqual(self.interact.call_count, 1)
        outlines = self.stdout.popvalue().splitlines()
        self.assertSequenceEqual(outlines[-5:], [
            "Logged in as 'usr'",
            "<Client 'http://127.0.0.1:8069/xmlrpc#database'>",
            "<Env 'usr@database'>",
            "Logged in as 'gaspard'",
            "42",
        ])
        self.assertOutput(stderr='\x1b[A\n\n', startswith=True)

    def test_no_database(self):
        env_tuple = ('http://127.0.0.1:8069', 'missingdb', 'usr', None)
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        read_config = mock.patch('odooly.read_config',
                                 return_value=env_tuple).start()
        self.service.db.list.return_value = ['database']

        # Launch interactive
        self.infunc.side_effect = [
            "client\n",
            "env\n",
            "client.login('gaspard')\n",
            EOFError('Finished')]
        odooly.main()

        expected_calls = self.startup_calls
        self.assertCalls(*expected_calls)
        self.assertEqual(read_config.call_count, 1)
        outlines = self.stdout.popvalue().splitlines()
        self.assertSequenceEqual(outlines[-4:], [
            "Error: Database 'missingdb' does not exist: ['database']",
            "<Client 'http://127.0.0.1:8069/xmlrpc#()'>",
            "<Env '@()'>",
            "Error: Not connected",
        ])
        self.assertOutput(stderr=ANY)

    def test_invalid_user_password(self):
        env_tuple = ('http://127.0.0.1:8069', 'database', 'usr', 'passwd')
        mock.patch('sys.argv', new=['odooly', '--env', 'demo']).start()
        mock.patch('os.environ', new={'LANG': 'fr_FR.UTF-8'}).start()
        mock.patch('odooly.read_config', return_value=env_tuple).start()
        mock.patch('getpass.getpass', return_value='x').start()
        self.service.db.list.return_value = ['database']
        self.service.common.login.side_effect = [17, None]
        self.service.object.execute_kw.side_effect = [42, {}, TypeError, 42, {}]

        # Launch interactive
        self.infunc.side_effect = [
            "env['res.company']\n",
            "client.login('gaspard')\n",
            "env['res.company']\n",
            EOFError('Finished')]
        odooly.main()

        def usr17(model, method, *params):
            return ('object.execute_kw', 'database', 17, 'passwd', model, method, params, {'context': ANY})

        expected_calls = self.startup_calls + (
            ('common.login', 'database', 'usr', 'passwd'),
            usr17('ir.model', 'search',
                  [('model', 'like', 'res.company')]),
            usr17('ir.model', 'read', 42, ('model',)),
            usr17('ir.model.access', 'check', 'res.users', 'write'),
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
