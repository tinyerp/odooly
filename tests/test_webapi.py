"""Test the Web API (Webclient) with the fake Odoo server, per version.

Versions with the same behaviour are tested with the most recent one.
"""
from unittest import mock

import odooly

from ._common import FakeOdooTestCase
from ._fake_odoo import FakeOdoo, FakeUser

API_KEY = 'apikey0123'
TOTP = '123456'


class _TestWebApi(FakeOdooTestCase):
    database = 'database'
    # Expected behaviour, per version
    twofa = None        # 2FA: None (no 2FA), or 'login form'
    json2 = False       # JSON-2 API, and doc endpoints

    def fake_odoo(self):
        return FakeOdoo(self.server_version, databases=[self.database], users=[
            FakeUser(2, 'admin', 'admin', api_key=API_KEY, is_system=True),
            FakeUser(6, 'demo', 'demo'),
            FakeUser(7, 'totp_user', 'totp', totp=TOTP),
        ])

    def setUp(self):
        super().setUp()
        self.getpass_2fa = mock.patch('odooly.client.getpass', return_value=TOTP).start()

    def login_requests(self, sid):
        """Requests after /web/session/authenticate."""
        if not self.json2:
            return []
        return [
            # The password is tried as an API key, for JSON-2
            ('/json/2/res.users/context_get', None),
            ('/doc/res.device.json', sid),
        ]

    def test_login(self):
        client = odooly.Client(self.server, self.database, 'admin', 'admin')
        self.assertEqual(client.env.uid, 2)
        self.assertEqual(client.env._execute_kw._protocol_name, 'Web API')
        self.assertEqual(self.odoo_server.requests, [
            ('/web/webclient/version_info', None),
            ('/web/database/list', None),
            ('/web/session/authenticate', None),
            *self.login_requests('SID1'),
        ])
        self.assertEqual(client.env.context, self.odoo_server.context(
            self.odoo_server.users['admin'], 2))
        self.assertOutput('')

    def test_call_kw(self):
        client = odooly.Client(self.server, self.database, 'demo', 'demo')
        self.odoo_server.requests.clear()
        self.assertEqual(client.env['res.partner'].search([]).ids, [1])
        self.assertEqual(self.odoo_server.requests[-1],
                         ('/web/dataset/call_kw/res.partner/search', 'SID1'))
        self.assertOutput('')

    def test_wrong_password(self):
        with self.assertRaisesRegex(odooly.Error, 'Invalid username or password'):
            odooly.Client(self.server, self.database, 'demo', 'wrong')
        # Access Denied: no other attempt
        self.assertEqual(self.odoo_server.paths()[-1], '/web/session/authenticate')
        self.assertEqual(self.getpass_2fa.call_count, 0)
        self.assertOutput('')

    def test_2fa(self):
        client = odooly.Client(self.server, self.database, 'totp_user', 'totp')
        self.assertEqual(client.env.uid, 7)
        if self.twofa is None:  # No 2FA on the server
            self.assertEqual(self.getpass_2fa.call_count, 0)
            self.assertNotIn('/web/login/totp', self.odoo_server.paths())
        else:
            # The login form, then the 2FA code
            self.assertEqual(self.getpass_2fa.call_count, 1)
            self.assertEqual(self.odoo_server.paths()[2:6], [
                '/web/session/authenticate',
                f'/web?db={self.database}',
                '/web/login',
                '/web/login/totp',
            ])
        self.assertOutput('')

    def test_2fa_wrong_code(self):
        if self.twofa != 'login form':
            return
        self.getpass_2fa.return_value = '000000'
        with self.assertRaisesRegex(odooly.Error, 'Invalid username or password'):
            odooly.Client(self.server, self.database, 'totp_user', 'totp')
        # The code is asked again, 3 times
        self.assertEqual(self.getpass_2fa.call_count, 3)
        self.assertOutput('Verification failed\n' * 3)

    def test_api_key(self):
        if not self.json2:
            # The Web API does not accept an API key: use JSON-RPC
            with self.assertRaisesRegex(odooly.Error, 'Invalid username or password'):
                odooly.Client(self.server, self.database, 'admin', api_key=API_KEY)
            self.assertNotIn('/json/2/res.users/context_get', self.odoo_server.paths())
            self.assertOutput('')
            return

        client = odooly.Client(self.server, self.database, 'admin', api_key=API_KEY)
        self.assertEqual(client.env.uid, 2)
        self.assertEqual(client.env._execute_kw._protocol_name, 'JSON-2')
        # No Webclient session
        self.assertNotIn('/web/session/authenticate', self.odoo_server.paths())
        self.assertEqual(client.env['res.partner'].search([]).ids, [1])
        self.assertEqual(self.odoo_server.paths()[-1], '/json/2/res.partner/search')
        self.assertOutput('')


class TestWebApi13(_TestWebApi):
    """Odoo 9 to 13: no 2FA."""
    server_version = '13.0'


class TestWebApi17(_TestWebApi):
    """Odoo 14 to 17: 2FA with the login form, which has 'user_id'."""
    server_version = '17.0'
    twofa = 'login form'


class TestWebApi18(_TestWebApi):
    """Odoo 18: the login form has 'uid'."""
    server_version = '18.0'
    twofa = 'login form'


class TestWebApi21(_TestWebApi):
    """Odoo 19 to 21: JSON-2 and doc endpoints."""
    server_version = '21.0'
    twofa = 'login form'
    json2 = True


del _TestWebApi
