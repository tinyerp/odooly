"""Test the Web API (Webclient) with the fake Odoo server, per version.

Versions with the same behaviour are tested with the most recent one.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import odooly
import odooly.run

from ._common import FakeOdooTestCase
from ._fake_odoo import PDF, FakeOdoo, FakeUser

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
        self.assertEqual(client.env['res.partner'].search([]).ids, [1, 3])
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

    def test_has_access(self):
        self.odoo_server.denied.add(('demo', 'res.users', 'write'))
        client = odooly.Client(self.server, self.database, 'demo', 'demo')
        self.assertTrue(client.env['res.users'].has_access('read'))
        self.assertFalse(client.env['res.users'].has_access('write'))
        if float(self.server_version) < 18.0:
            self.assertEqual(self.odoo_server.paths()[-1],
                             '/web/dataset/call_kw/ir.model.access/check')
        else:
            self.assertEqual(self.odoo_server.paths()[-1],
                             '/web/dataset/call_kw/res.users/has_access')
        self.assertOutput('')

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
        self.assertEqual(client.env['res.partner'].search([]).ids, [1, 3])
        self.assertEqual(self.odoo_server.paths()[-1], '/json/2/res.partner/search')
        # has_access with JSON-2
        self.odoo_server.denied.add(('admin', 'res.users', 'unlink'))
        self.assertTrue(client.env['res.users'].has_access('write'))
        self.assertFalse(client.env['res.users'].has_access('unlink'))
        self.assertEqual(self.odoo_server.paths()[-1], '/json/2/res.users/has_access')
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


class _TestModels(FakeOdooTestCase):
    """Test Env.models(), for an admin and for a user."""
    database = 'database'
    # Expected behaviour, per version
    user_models = 'all'     # Models for a user: 'all', 'reference field' or 'model selector'
    abstract = True         # Abstract models are listed

    def fake_odoo(self):
        return FakeOdoo(self.server_version, databases=[self.database])

    def all_models(self):
        models = ['ir.model', 'mail.thread', 'res.company', 'res.partner', 'res.users',
                  self.odoo_server.report_model()]
        return sorted(models if self.abstract else set(models) - {'mail.thread'})

    def test_models_admin(self):
        env = odooly.Client(self.server, self.database, 'admin', 'admin').env
        self.assertEqual(env.models(), self.all_models())
        self.assertEqual(env.models('res.'), ['res.company', 'res.partner', 'res.users'])
        self.assertEqual(env.models(transient=True), ['base.language.install'])
        self.assertNotIn('/web/dataset/call_kw/ir.model/get_available_models',
                         self.odoo_server.paths())
        self.assertOutput('')

    def test_models_user(self):
        env = odooly.Client(self.server, self.database, 'demo', 'demo').env
        if self.user_models == 'all':
            self.assertEqual(env.models(), self.all_models())
            self.assertEqual(env.models(transient=True), ['base.language.install'])
        elif self.user_models == 'reference field':
            # Odoo 15: all the models, from a Reference field, without 'transient'
            all_models = sorted(self.odoo_server.models)
            self.assertEqual(env.models(), all_models)
            self.assertEqual(env.models(transient=True), [])
            self.assertEqual(self.odoo_server.paths()[-1],
                             '/web/dataset/call_kw/ir.server.object.lines/fields_get')
            # The model name is checked
            self.assertEqual(env['res.partner'].search([]).ids, [1, 3])
            with self.assertRaisesRegex(odooly.Error, 'Model not found: res.partnerX'):
                env['res.partnerX']
        else:
            # Only the models of the model selector: no transient, no abstract
            self.assertEqual(env.models(), sorted(set(self.all_models()) - {'mail.thread'}))
            self.assertEqual(env.models(transient=True), [])
            self.assertEqual(self.odoo_server.paths()[-1],
                             '/web/dataset/call_kw/ir.model/get_available_models')
        self.assertOutput('')


class TestModels14(_TestModels):
    """Odoo 9 to 14: a user can read 'ir.model'."""
    server_version = '14.0'


class TestModels15(_TestModels):
    """Odoo 15: a user cannot read 'ir.model', and no 'get_available_models'."""
    server_version = '15.0'
    user_models = 'reference field'


class TestModels18(_TestModels):
    """Odoo 16 to 18: 'get_available_models', for a user."""
    server_version = '18.0'
    user_models = 'model selector'


class TestModels21(_TestModels):
    """Odoo 19 to 21: abstract models are not listed."""
    server_version = '21.0'
    user_models = 'model selector'
    abstract = False


class _TestReport(FakeOdooTestCase):
    """Test render_pdf(), with the Web API."""
    database = 'database'

    def fake_odoo(self):
        return FakeOdoo(self.server_version, databases=[self.database])

    def setUp(self):
        super().setUp()
        self.env = odooly.Client(self.server, self.database, 'admin', 'admin').env
        self.report_model = self.odoo_server.report_model()

    def test_render_pdf_record(self):
        result = self.env['res.partner'].browse(1).render_pdf('base.partner_card_logo')
        self.assertEqual((result.name, result.getvalue()), ('Partner Card Logo.pdf', PDF))
        self.assertIn(f'/web/dataset/call_kw/{self.report_model}/search',
                      self.odoo_server.paths())
        # A single record: /report/download, for the filename
        [(path, data)] = self.odoo_server.report_requests
        self.assertEqual(path, '/report/download')
        [url, report_type] = json.loads(data['data'])
        self.assertEqual(report_type, 'qweb-pdf')
        self.assertEqual(urlsplit(url).path, '/report/pdf/base.partner_card_logo/1')
        self.assertEqual(json.loads(parse_qs(urlsplit(url).query)['context'][0]),
                         self.env.context)
        self.assertOutput('')

    def test_render_pdf_records(self):
        result = self.env['res.partner'].browse([1, 3]).render_pdf('base.partner_card_logo')
        self.assertEqual((result.name, result.getvalue()), ('Partner Card Logo.pdf', PDF))
        [(path, data)] = self.odoo_server.report_requests
        self.assertEqual(path, '/report/pdf/base.partner_card_logo/1,3')
        # Fields 'context' and 'options', read by Odoo
        self.assertEqual(data, {'context': json.dumps(self.env.context)})

        records = self.env['res.partner'].browse([1, 3])
        records.render_pdf('base.partner_card_logo', data={'is_test': True})
        self.assertEqual(self.odoo_server.report_requests[-1][1], {
            'context': json.dumps(self.env.context), 'options': '{"is_test": true}'})
        self.assertOutput('')

    def test_render_pdf_missing(self):
        records = self.env['res.partner'].browse(1)
        with self.assertRaisesRegex(odooly.Error, "Missing report: 'base.unknown'"):
            records.render_pdf('base.unknown')
        with self.assertRaisesRegex(odooly.Error, 'No report found'):
            records.render_pdf()
        # Several reports match 'partner_card', and none is equal
        with self.assertRaisesRegex(odooly.Error, "Missing report: 'partner_card'"):
            records.render_pdf('partner_card')
        self.assertEqual(self.odoo_server.report_requests, [])
        self.assertOutput('')

    def test_render_pdf_name(self):
        records = self.env['res.partner'].browse(1)
        # A single report matches
        self.assertEqual(records.render_pdf('card_logo').name, 'Partner Card Logo.pdf')
        # Several reports match: the exact name is selected
        self.assertEqual(records.render_pdf('base.partner_card').name, 'Partner Card.pdf')
        self.assertOutput('')

    def test_render_pdf_interactive(self):
        mock.patch('odooly.client.Client._is_interactive', return_value=True).start()
        mock.patch('odooly.report.open_with_default_app').start()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        mock.patch('odooly.report.Path.cwd', return_value=Path(tmpdir.name)).start()
        # Select the 1st report, save with the default filename, do not open
        answers = mock.patch('odooly.report.input', create=True,
                             side_effect=['1', 'y', '', 'n']).start()

        result = self.env['res.partner'].browse(1).render_pdf()
        self.assertEqual(result, Path(tmpdir.name) / 'Partner_Card.pdf')
        self.assertEqual(result.read_bytes(), PDF)
        self.assertEqual([c.args[0] for c in answers.mock_calls], [
            'Select a report: ',
            'Save? [Y/n] ',
            'Enter filename [Partner_Card.pdf]: ',
            'Open "Partner_Card.pdf"? [Y/n] ',
        ])
        reports = [
            ' 1. Partner Card    (base.partner_card `qweb-pdf`)',
            ' 2. Partner Sheet    (base.partner_sheet `qweb-html`)',
        ]
        if float(self.server_version) < 11.0:
            # Odoo 9 and 10: no 'binding_model_id', all reports are listed
            reports.append(' 3. Partner Card Logo    (base.partner_card_logo `qweb-pdf`)')
        self.assertOutput('\n'.join(['Available reports:', *reports, '', '']))


class TestReport10(_TestReport):
    """Odoo 9 and 10: 'ir.actions.report.xml'."""
    server_version = '10.0'


class TestReport21(_TestReport):
    """Odoo 11 to 21: 'ir.actions.report', with 'binding_model_id'."""
    server_version = '21.0'


del _TestWebApi, _TestModels, _TestReport
