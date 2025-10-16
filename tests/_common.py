from io import BytesIO
from urllib.request import HTTPError
from unittest import mock, TestCase
from unittest.mock import call, sentinel

import odooly

sample_context = {'lang': 'en_US', 'tz': 'Europe/Zurich'}
type_call = type(call)


class PseudoFile(list):
    write = list.append

    def popvalue(self):
        rv = ''.join(self)
        del self[:]
        return rv


def OBJ(model, method, *params, **kw):
    if 'context' not in kw:
        kw['context'] = sample_context
    elif kw['context'] is None:
        del kw['context']
    return ('object.execute_kw', sentinel.AUTH, model, method, params) + ((kw,) if kw else ())


class XmlRpcTestCase(TestCase):
    server_version = None
    server = "http://192.0.2.199:9999"
    database = user = password = uid = None
    maxDiff = None

    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        self.stdout = mock.patch('sys.stdout', new=PseudoFile()).start()
        self.stderr = mock.patch('sys.stderr', new=PseudoFile()).start()

        # Clear the login cache
        mock.patch.dict('odooly.Env._cache', clear=True).start()

        # Avoid hanging on getpass
        mock.patch('odooly.getpass', side_effect=RuntimeError).start()

        self.service = self._patch_service()
        if self.server and self.database:
            # create the client
            self.client = odooly.Client(
                self.server, self.database, self.user, self.password)
            self.env = self.client.env
            # reset the mock
            self.service.reset_mock()

    def _patch_http_request(self, uid=None, context=sample_context):
        def func(url, *, method='POST', data=None, json=None, headers=None):
            if url.endswith("/web/session/authenticate"):
                result = {'uid': uid or self.uid, 'user_context': context}
            else:
                with HTTPError(url, 404, 'Not Found', headers, BytesIO()) as not_found:
                    raise not_found
            return {'result': result}
        return mock.patch('odooly.HTTPSession.request', side_effect=func).start()

    def _patch_service(self):
        def get_svc(server, name, *args, **kwargs):
            return getattr(svcs, name)
        patcher = mock.patch('odooly.Service', side_effect=get_svc)
        svcs = patcher.start()
        svcs.stop = patcher.stop
        for svc_name in 'db common object wizard report'.split():
            svcs.attach_mock(mock.Mock(name=svc_name), svc_name)
        # Default values
        svcs.db.server_version.return_value = self.server_version
        svcs.db.list.return_value = [self.database]
        svcs.common.login.return_value = self.uid
        # env['res.users'].context_get()
        svcs.object.execute_kw.return_value = sample_context
        return svcs

    def _assertCalls(self, mock_, expected_calls):
        for idx, expected in enumerate(expected_calls):
            if isinstance(expected, str):
                if expected[:4] == 'call':
                    expected = expected[4:].lstrip('.')
                assert expected[-2:] != '()'
                expected_calls[idx] = type_call((expected,))
        self.assertSequenceEqual(mock_.mock_calls, expected_calls)
        mock_.reset_mock()

    def assertServiceCalls(self, *expected_args):
        expected_calls = list(expected_args)
        for idx, expected in enumerate(expected_calls):
            if not isinstance(expected, type_call) and isinstance(expected, tuple):
                rpcmethod = expected[0]
                if len(expected) > 1 and expected[1] == sentinel.AUTH:
                    args = (self.database, self.uid, self.password) + expected[2:]
                else:
                    args = expected[1:]
                expected_calls[idx] = getattr(call, rpcmethod)(*args)
        self._assertCalls(self.service, expected_calls)

    def assertOutput(self, stdout='', stderr='', startswith=False):
        # compare with ANY to make sure output is not empty
        if stderr is mock.ANY:
            self.assertTrue(self.stderr.popvalue())
        else:
            stderr_value = self.stderr.popvalue()
            if startswith and stderr:
                stderr_value = stderr_value[:len(stderr)]
            self.assertMultiLineEqual(stderr_value, stderr)
        if stdout is mock.ANY:
            self.assertTrue(self.stdout.popvalue())
        else:
            stdout_value = self.stdout.popvalue()
            if startswith and stdout:
                stdout_value = stdout_value[:len(stdout)]
            self.assertMultiLineEqual(stdout_value, stdout)

    # Legacy
    assertCalls = assertServiceCalls
