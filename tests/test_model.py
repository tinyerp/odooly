# -*- coding: utf-8 -*-
from mock import sentinel, ANY

import odooly
from ._common import XmlRpcTestCase, OBJ, callable

PY2 = ('' == ''.encode())


class TestCase(XmlRpcTestCase):
    server_version = '6.1'
    server = 'http://127.0.0.1:8069'
    database = 'database'
    user = 'user'
    password = 'passwd'
    uid = 1

    def obj_exec(self, db_name, uid, passwd, model, method, args, kw=None):
        if method == 'search':
            domain = args[0]
            if model.startswith('ir.model') and 'foo' in str(domain):
                if "'in', []" in str(domain) or 'other_module' in str(domain):
                    return []
                return [777]
            if domain == [('name', '=', 'Morice')]:
                return [1003]
            if 'missing' in str(domain):
                return []
            return [1001, 1002]
        if method == 'read':
            if args[0] == [777]:
                if model == 'ir.model.data':
                    return [{'model': 'foo.bar', 'module': 'this_module',
                             'name': 'xml_name', 'id': 1733, 'res_id': 42}]
                return [{'model': 'foo.bar', 'id': 371},
                        {'model': 'foo.other', 'id': 99},
                        {'model': 'ir.model.data', 'id': 17}]

            # We no longer read single ids
            self.assertIsInstance(args[0], list)

            class IdentDict(dict):
                def __init__(self, id_, fields=()):
                    self['id'] = id_
                    for f in fields:
                        self[f] = self[f]

                def __getitem__(self, key):
                    if key in self:
                        return dict.__getitem__(self, key)
                    return 'v_' + key
            if model == 'foo.bar' and (len(args) < 2 or args[1] is None):
                records = {}
                for res_id in set(args[0]):
                    rdic = IdentDict(res_id, ('name', 'message', 'spam'))
                    rdic['misc_id'] = 421
                    records[res_id] = rdic
                return [records[res_id] for res_id in args[0]]
            return [IdentDict(arg, args[1]) for arg in args[0]]
        if method == 'fields_get_keys':
            return ['id', 'name', 'message', 'misc_id']
        if method == 'fields_get':
            if model == 'ir.model.data':
                keys = ('id', 'model', 'module', 'name', 'res_id')
            else:
                keys = ('id', 'name', 'message', 'spam', 'birthdate', 'city')
            fields = dict.fromkeys(keys, {'type': sentinel.FIELD_TYPE})
            fields['misc_id'] = {'type': 'many2one', 'relation': 'foo.misc'}
            fields['line_ids'] = {'type': 'one2many', 'relation': 'foo.lines'}
            fields['many_ids'] = {'type': 'many2many', 'relation': 'foo.many'}
            return fields
        if method == 'name_get':
            ids = list(args[0])
            if 404 in ids:
                1 / 0
            if 8888 in ids:
                ids[ids.index(8888)] = b'\xdan\xeecode'.decode('latin-1')
            return [(res_id, b'name_%s'.decode() % res_id) for res_id in ids]
        if method in ('create', 'copy'):
            return 1999
        return [sentinel.OTHER]

    def setUp(self):
        super(TestCase, self).setUp()
        self.service.object.execute_kw.side_effect = self.obj_exec
        # preload 'foo.bar'
        self.env['foo.bar']
        self.service.reset_mock()


class TestModel(TestCase):
    """Tests the Model class and methods."""

    def test_model(self):
        # Reset cache for this test
        self.env._model_names.clear()

        self.assertRaises(odooly.Error, self.env.__getitem__, 'mic.mac')
        self.assertRaises(AttributeError, getattr, self.client, 'MicMac')
        self.assertCalls(ANY, ANY)
        self.assertOutput('')

        self.assertIs(self.env['foo.bar'],
                      odooly.Model(self.env, 'foo.bar'))
        # self.assertIs(self.client.model('foo.bar'),
        #               self.client.FooBar)
        self.assertCalls(
            OBJ('ir.model', 'search', [('model', 'like', 'foo.bar')]),
            OBJ('ir.model', 'read', [777], ('model',)),
        )
        self.assertOutput('')

    def test_keys(self):
        self.assertTrue(self.env['foo.bar'].keys())
        self.assertCalls(OBJ('foo.bar', 'fields_get_keys'))
        self.assertOutput('')

    def test_fields(self):
        self.assertEqual(self.env['foo.bar'].fields('bis'), {})
        self.assertEqual(self.env['foo.bar'].fields('alp bis'), {})
        self.assertEqual(self.env['foo.bar'].fields('spam bis'),
                         {'spam': {'type': sentinel.FIELD_TYPE}})
        self.assertTrue(self.env['foo.bar'].fields())

        self.assertRaises(TypeError, self.env['foo.bar'].fields, 42)

        self.assertCalls(OBJ('foo.bar', 'fields_get'))
        self.assertOutput('')

    def test_field(self):
        self.assertTrue(self.env['foo.bar'].field('spam'))

        self.assertRaises(TypeError, self.env['foo.bar'].field)

        self.assertCalls(OBJ('foo.bar', 'fields_get'))
        self.assertOutput('')

    def test_access(self):
        self.assertTrue(self.env['foo.bar'].access())
        self.assertCalls(OBJ('ir.model.access', 'check', 'foo.bar', 'read'))
        self.assertOutput('')

    def test_search(self):
        FooBar = self.env['foo.bar']

        searchterm = 'name like Morice'
        self.assertIsInstance(FooBar.search([searchterm]), odooly.RecordList)
        FooBar.search([searchterm], limit=2)
        FooBar.search([searchterm], offset=80, limit=99)
        FooBar.search([searchterm], order='name ASC')
        FooBar.search(['name = mushroom', 'state != draft'])
        FooBar.search([('name', 'like', 'Morice')])
        FooBar._execute('search', [('name like Morice')])
        FooBar.search([])
        domain = [('name', 'like', 'Morice')]
        domain2 = [('name', '=', 'mushroom'), ('state', '!=', 'draft')]
        self.assertCalls(
            OBJ('foo.bar', 'search', domain),
            OBJ('foo.bar', 'search', domain, 0, 2, None),
            OBJ('foo.bar', 'search', domain, 80, 99, None),
            OBJ('foo.bar', 'search', domain, 0, None, 'name ASC'),
            OBJ('foo.bar', 'search', domain2),
            OBJ('foo.bar', 'search', domain),
            OBJ('foo.bar', 'search', domain),
            OBJ('foo.bar', 'search', []),
        )
        self.assertOutput('')

        # Not supported
        FooBar.search('name like Morice')
        self.assertCalls(OBJ('foo.bar', 'search', 'name like Morice'))

        FooBar.search(['name like Morice'], missingkey=42)
        self.assertCalls(OBJ('foo.bar', 'search', domain, missingkey=42))
        # self.assertOutput('Ignoring: missingkey = 42\n')
        self.assertOutput('')

        self.assertRaises(TypeError, FooBar.search)
        self.assertRaises(ValueError, FooBar.search, ['abc'])
        self.assertRaises(ValueError, FooBar.search, ['< id'])
        self.assertRaises(ValueError, FooBar.search, ['name Morice'])

        self.assertCalls()
        self.assertOutput('')

    def test_search_count(self):
        FooBar = self.env['foo.bar']
        searchterm = 'name like Morice'

        FooBar.search_count([searchterm])
        FooBar.search_count(['name = mushroom', 'state != draft'])
        FooBar.search_count([('name', 'like', 'Morice')])
        FooBar._execute('search_count', [searchterm])
        FooBar.search_count([])
        FooBar.search_count()
        domain = [('name', 'like', 'Morice')]
        domain2 = [('name', '=', 'mushroom'), ('state', '!=', 'draft')]
        self.assertCalls(
            OBJ('foo.bar', 'search_count', domain),
            OBJ('foo.bar', 'search_count', domain2),
            OBJ('foo.bar', 'search_count', domain),
            OBJ('foo.bar', 'search_count', domain),
            OBJ('foo.bar', 'search_count', []),
            OBJ('foo.bar', 'search_count', []),
        )
        self.assertOutput('')

        # Invalid keyword arguments are passed to the API
        FooBar.search([searchterm], limit=2, fields=['birthdate', 'city'])
        FooBar.search([searchterm], missingkey=42)
        self.assertCalls(
            OBJ('foo.bar', 'search', domain, 0, 2, None, fields=['birthdate', 'city']),
            OBJ('foo.bar', 'search', domain, missingkey=42))
        self.assertOutput('')

        # Not supported
        FooBar.search_count(searchterm)
        self.assertCalls(OBJ('foo.bar', 'search_count', searchterm))

        self.assertRaises(TypeError, FooBar.search_count,
                          [searchterm], limit=2)
        self.assertRaises(TypeError, FooBar.search_count,
                          [searchterm], offset=80, limit=99)
        self.assertRaises(TypeError, FooBar.search_count,
                          [searchterm], order='name ASC')
        self.assertRaises(ValueError, FooBar.search_count, ['abc'])
        self.assertRaises(ValueError, FooBar.search_count, ['< id'])
        self.assertRaises(ValueError, FooBar.search_count, ['name Morice'])

        self.assertCalls()
        self.assertOutput('')

    def test_read(self):
        FooBar = self.env['foo.bar']

        def call_read(*args, **kw):
            return OBJ('foo.bar', 'read', [1001, 1002], *args, **kw)

        FooBar.read(42)
        FooBar.read([42])
        FooBar.read([13, 17])
        FooBar.read([42], 'first_name')
        self.assertCalls(
            OBJ('foo.bar', 'read', [42]),
            OBJ('foo.bar', 'read', [42]),
            OBJ('foo.bar', 'read', [13, 17]),
            OBJ('foo.bar', 'read', [42], ['first_name']),
        )
        self.assertOutput('')

        searchterm = 'name like Morice'
        FooBar.read([searchterm])
        FooBar.read([searchterm], limit=2)
        FooBar.read([searchterm], offset=80, limit=99)
        FooBar.read([searchterm], order='name ASC')
        FooBar.read([searchterm], 'birthdate city')
        FooBar.read([searchterm], 'birthdate city', limit=2)
        FooBar.read([searchterm], limit=2, fields=['birthdate', 'city'])
        FooBar.read([searchterm], order='name ASC')
        FooBar.read(['name = mushroom', 'state != draft'])
        FooBar.read([('name', 'like', 'Morice')])
        FooBar._execute('read', [searchterm])

        rv = FooBar.read([searchterm],
                         'aaa %(birthdate)s bbb %(city)s', offset=80, limit=99)
        self.assertEqual(rv, ['aaa v_birthdate bbb v_city'] * 2)

        domain = [('name', 'like', 'Morice')]
        domain2 = [('name', '=', 'mushroom'), ('state', '!=', 'draft')]
        self.assertCalls(
            OBJ('foo.bar', 'search', domain), call_read(),
            OBJ('foo.bar', 'search', domain, 0, 2, None), call_read(),
            OBJ('foo.bar', 'search', domain, 80, 99, None), call_read(),
            OBJ('foo.bar', 'search', domain, 0, None, 'name ASC'),
            call_read(),
            OBJ('foo.bar', 'search', domain), call_read(['birthdate', 'city']),
            OBJ('foo.bar', 'search', domain, 0, 2, None),
            call_read(['birthdate', 'city']),
            OBJ('foo.bar', 'search', domain, 0, 2, None),
            call_read(fields=['birthdate', 'city']),
            OBJ('foo.bar', 'search', domain, 0, None, 'name ASC'),
            call_read(),
            OBJ('foo.bar', 'search', domain2), call_read(),
            OBJ('foo.bar', 'search', domain), call_read(),
            OBJ('foo.bar', 'search', domain), call_read(),
            OBJ('foo.bar', 'search', domain, 80, 99, None),
            call_read(['birthdate', 'city']),
        )
        self.assertOutput('')

        self.assertEqual(FooBar.read([]), [])
        self.assertEqual(FooBar.read([], order='name ASC'), [])
        self.assertEqual(FooBar.read([False]), [])
        self.assertEqual(FooBar.read([False, False]), [])
        self.assertCalls()
        self.assertOutput('')

        # Not supported
        FooBar.read(searchterm)
        self.assertCalls(OBJ('foo.bar', 'read', [searchterm]))

        FooBar.read([searchterm], missingkey=42)
        self.assertCalls(OBJ('foo.bar', 'search', domain), call_read(missingkey=42))
        self.assertOutput('')

        self.assertRaises(AssertionError, FooBar.read)
        self.assertRaises(ValueError, FooBar.read, ['abc'])
        self.assertRaises(ValueError, FooBar.read, ['< id'])
        self.assertRaises(ValueError, FooBar.read, ['name Morice'])

        self.assertCalls()
        self.assertOutput('')

    def test_browse(self):
        FooBar = self.env['foo.bar']

        self.assertIsInstance(FooBar.browse(42), odooly.Record)
        self.assertIsInstance(FooBar.browse([42]), odooly.RecordList)
        self.assertEqual(len(FooBar.browse([13, 17])), 2)

        records = FooBar.browse([])
        self.assertIsInstance(records, odooly.RecordList)
        self.assertFalse(records)

        records = FooBar.with_context({'lang': 'fr_CA'}).browse([])
        self.assertIsInstance(records, odooly.RecordList)
        self.assertFalse(records)
        self.assertEqual(records.env.lang, 'fr_CA')

        records = FooBar.browse([])
        self.assertIsInstance(records, odooly.RecordList)
        self.assertFalse(records)
        self.assertIsNone(records.env.lang)

        self.assertCalls()
        self.assertOutput('')

        # No longer supported
        self.assertRaises(AssertionError, FooBar.browse, ['name like Morice'])
        self.assertRaises(AssertionError, FooBar.browse, 'name like Morice')

        self.assertRaises(TypeError, FooBar.browse)
        self.assertRaises(AssertionError, FooBar.browse, ['abc'])
        self.assertRaises(AssertionError, FooBar.browse, ['< id'])
        self.assertRaises(AssertionError, FooBar.browse, ['name Morice'])
        self.assertRaises(TypeError, FooBar.browse, [], limit=12)
        self.assertRaises(TypeError, FooBar.browse, [], limit=None)
        self.assertRaises(TypeError, FooBar.browse, [], context={})

        self.assertCalls()
        self.assertOutput('')

    def test_search_all(self):
        FooBar = self.env['foo.bar']

        records = FooBar.search([])
        self.assertIsInstance(records, odooly.RecordList)
        self.assertTrue(records)

        records = FooBar.search([], limit=12)
        self.assertIsInstance(records, odooly.RecordList)
        self.assertTrue(records)

        records = FooBar.with_context({'lang': 'fr_CA'}).search([])
        self.assertIsInstance(records, odooly.RecordList)
        self.assertTrue(records)

        records = FooBar.search([], limit=None)
        self.assertIsInstance(records, odooly.RecordList)
        self.assertTrue(records)

        self.assertCalls(
            OBJ('foo.bar', 'search', []),
            OBJ('foo.bar', 'search', [], 0, 12, None),
            OBJ('foo.bar', 'search', [], context={'lang': 'fr_CA'}),
            OBJ('foo.bar', 'search', []),
        )
        self.assertOutput('')

    def test_get(self):
        FooBar = self.env['foo.bar']

        self.assertIsInstance(FooBar.get(42), odooly.Record)
        self.assertCalls()
        self.assertOutput('')

        self.assertIsInstance(FooBar.get(['name = Morice']), odooly.Record)
        self.assertIsNone(FooBar.get(['name = Blinky', 'missing = False']))

        # domain matches too many records (2)
        self.assertRaises(ValueError, FooBar.get, ['name like Morice'])

        # set default context
        ctx = {'lang': 'en_GB', 'location': 'somewhere'}
        self.env.context = dict(ctx)

        # with context
        value = FooBar.with_context({'lang': 'fr_FR'}).get(['name = Morice'])
        self.assertEqual(type(value), odooly.Record)
        self.assertIsInstance(value.name, str)

        # with default context
        value = FooBar.get(['name = Morice'])
        self.assertEqual(type(value), odooly.Record)
        self.assertIsInstance(value.name, str)

        self.assertCalls(
            OBJ('foo.bar', 'search', [('name', '=', 'Morice')]),
            OBJ('foo.bar', 'search', [('name', '=', 'Blinky'), ('missing', '=', False)]),
            OBJ('foo.bar', 'search', [('name', 'like', 'Morice')]),
            OBJ('foo.bar', 'search', [('name', '=', 'Morice')], context={'lang': 'fr_FR'}),
            OBJ('foo.bar', 'fields_get_keys', context={'lang': 'fr_FR'}),
            OBJ('foo.bar', 'read', [1003], ['name'], context={'lang': 'fr_FR'}),
            OBJ('foo.bar', 'fields_get', context={'lang': 'fr_FR'}),
            OBJ('foo.bar', 'search', [('name', '=', 'Morice')], context=ctx),
            OBJ('foo.bar', 'read', [1003], ['name'], context=ctx),
        )
        self.assertOutput('')

        self.assertRaises(ValueError, FooBar.get, 'name = Morice')
        self.assertRaises(ValueError, FooBar.get, ['abc'])
        self.assertRaises(ValueError, FooBar.get, ['< id'])
        self.assertRaises(ValueError, FooBar.get, ['name Morice'])

        self.assertRaises(TypeError, FooBar.get)
        self.assertRaises(TypeError, FooBar.get, ['name = Morice'], limit=1)

        self.assertRaises(AssertionError, FooBar.get, [42])
        self.assertRaises(AssertionError, FooBar.get, [13, 17])

        self.assertCalls()
        self.assertOutput('')

    def test_get_xml_id(self):
        FooBar = self.env['foo.bar']
        BabarFoo = self.env._get('babar.foo', check=False)
        self.assertIsInstance(BabarFoo, odooly.Model)

        self.assertIsNone(FooBar.get('base.missing_company'))
        self.assertIsInstance(FooBar.get('base.foo_company'), odooly.Record)

        # model mismatch
        self.assertRaises(AssertionError, BabarFoo.get, 'base.foo_company')

        self.assertCalls(
            OBJ('ir.model.data', 'search', [('module', '=', 'base'), ('name', '=', 'missing_company')]),
            OBJ('ir.model.data', 'search', [('module', '=', 'base'), ('name', '=', 'foo_company')]),
            OBJ('ir.model.data', 'read', [777], ['model', 'res_id']),
            OBJ('ir.model.data', 'search', [('module', '=', 'base'), ('name', '=', 'foo_company')]),
            OBJ('ir.model.data', 'read', [777], ['model', 'res_id']),
        )

        self.assertOutput('')

    def test_create(self):
        FooBar = self.env['foo.bar']

        record42 = FooBar.browse(42)
        recordlist42 = FooBar.browse([4, 2])

        FooBar.create({'spam': 42})
        FooBar.create({'spam': record42})
        FooBar.create({'spam': recordlist42})
        FooBar._execute('create', {'spam': 42})
        FooBar.create({})
        self.assertCalls(
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'create', {'spam': 42}),
            OBJ('foo.bar', 'create', {'spam': 42}),
            OBJ('foo.bar', 'create', {'spam': [4, 2]}),
            OBJ('foo.bar', 'create', {'spam': 42}),
            OBJ('foo.bar', 'create', {}),
        )
        self.assertOutput('')

    def test_create_relation(self):
        FooBar = self.env['foo.bar']

        record42 = FooBar.browse(42)
        recordlist42 = FooBar.browse([4, 2])
        rec_null = FooBar.browse(False)

        # one2many
        FooBar.create({'line_ids': rec_null})
        FooBar.create({'line_ids': []})
        FooBar.create({'line_ids': [123, 234]})
        FooBar.create({'line_ids': [(6, 0, [76])]})
        FooBar.create({'line_ids': recordlist42})

        # many2many
        FooBar.create({'many_ids': None})
        FooBar.create({'many_ids': []})
        FooBar.create({'many_ids': [123, 234]})
        FooBar.create({'many_ids': [(6, 0, [76])]})
        FooBar.create({'many_ids': recordlist42})

        # many2one
        FooBar.create({'misc_id': False})
        FooBar.create({'misc_id': 123})
        FooBar.create({'misc_id': record42})

        self.assertCalls(
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'create', {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'create', {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'create', {'line_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'create', {'line_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'create', {'line_ids': [(6, 0, [4, 2])]}),

            OBJ('foo.bar', 'create', {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'create', {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'create', {'many_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'create', {'many_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'create', {'many_ids': [(6, 0, [4, 2])]}),

            OBJ('foo.bar', 'create', {'misc_id': False}),
            OBJ('foo.bar', 'create', {'misc_id': 123}),
            OBJ('foo.bar', 'create', {'misc_id': 42}),
        )
        self.assertOutput('')

    def test_method(self, method_name='method', single_id=True):
        FooBar = self.env['foo.bar']
        FooBar_method = getattr(FooBar, method_name)

        single_id = single_id and 42 or [42]

        FooBar_method(42)
        FooBar_method([42])
        FooBar_method([13, 17])
        FooBar._execute(method_name, [42])
        FooBar_method([])
        self.assertCalls(
            OBJ('foo.bar', method_name, single_id),
            OBJ('foo.bar', method_name, [42]),
            OBJ('foo.bar', method_name, [13, 17]),
            OBJ('foo.bar', method_name, [42]),
            OBJ('foo.bar', method_name, []),
        )
        self.assertOutput('')

    def test_standard_methods(self):
        for method in 'write', 'copy', 'unlink', 'get_metadata':
            self.test_method(method)

    def test_get_external_ids(self):
        FooBar = self.env['foo.bar']

        self.assertEqual(FooBar._get_external_ids(), {'this_module.xml_name': FooBar.get(42)})
        FooBar._get_external_ids([])
        FooBar._get_external_ids([2001, 2002])
        self.assertCalls(
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar')]),
            OBJ('ir.model.data', 'read', [777], ['module', 'name', 'res_id']),
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar'), ('res_id', 'in', [])]),
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar'), ('res_id', 'in', [2001, 2002])]),
            OBJ('ir.model.data', 'read', [777], ['module', 'name', 'res_id']),
        )
        self.assertOutput('')


class TestRecord(TestCase):
    """Tests the Model class and methods."""

    def test_read(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)
        rec_null = self.env['foo.bar'].browse(False)

        self.assertIsInstance(records, odooly.RecordList)
        self.assertIsInstance(rec, odooly.Record)
        self.assertIsInstance(rec_null, odooly.Record)

        rec.read()
        records.read()
        rec.read('message')
        records.read('message')
        rec.read('name message')
        records.read('birthdate city')

        self.assertCalls(
            OBJ('foo.bar', 'read', [42], None),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'read', [13, 17], None),
            OBJ('foo.bar', 'read', [42], ['message']),
            OBJ('foo.bar', 'read', [13, 17], ['message']),
            OBJ('foo.bar', 'read', [42], ['name', 'message']),
            OBJ('foo.bar', 'read', [13, 17], ['birthdate', 'city']),
        )
        self.assertOutput('')

    def test_write(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)

        rec.write({})
        rec.write({'spam': 42})
        rec.write({'spam': rec})
        rec.write({'spam': records})
        records.write({})
        records.write({'spam': 42})
        records.write({'spam': rec})
        records.write({'spam': records})
        self.assertCalls(
            OBJ('foo.bar', 'write', [42], {}),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'write', [42], {'spam': 42}),
            OBJ('foo.bar', 'write', [42], {'spam': 42}),
            OBJ('foo.bar', 'write', [42], {'spam': [13, 17]}),
            OBJ('foo.bar', 'write', [13, 17], {}),
            OBJ('foo.bar', 'write', [13, 17], {'spam': 42}),
            OBJ('foo.bar', 'write', [13, 17], {'spam': 42}),
            OBJ('foo.bar', 'write', [13, 17], {'spam': [13, 17]}),
        )
        self.assertOutput('')

    def test_write_relation(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)
        rec_null = self.env['foo.bar'].browse(False)

        # one2many
        rec.write({'line_ids': False})
        rec.write({'line_ids': []})
        rec.write({'line_ids': [123, 234]})
        rec.write({'line_ids': [(6, 0, [76])]})
        rec.write({'line_ids': records})

        # many2many
        rec.write({'many_ids': None})
        rec.write({'many_ids': []})
        rec.write({'many_ids': [123, 234]})
        rec.write({'many_ids': [(6, 0, [76])]})
        rec.write({'many_ids': records})

        # many2one
        rec.write({'misc_id': False})
        rec.write({'misc_id': 123})
        rec.write({'misc_id': rec})

        # one2many
        records.write({'line_ids': None})
        records.write({'line_ids': []})
        records.write({'line_ids': [123, 234]})
        records.write({'line_ids': [(6, 0, [76])]})
        records.write({'line_ids': records})

        # many2many
        records.write({'many_ids': 0})
        records.write({'many_ids': []})
        records.write({'many_ids': [123, 234]})
        records.write({'many_ids': [(6, 0, [76])]})
        records.write({'many_ids': records})

        # many2one
        records.write({'misc_id': rec_null})
        records.write({'misc_id': 123})
        records.write({'misc_id': rec})

        self.assertCalls(
            OBJ('foo.bar', 'fields_get'),

            OBJ('foo.bar', 'write', [42], {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [42], {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [42], {'line_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'write', [42], {'line_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'write', [42], {'line_ids': [(6, 0, [13, 17])]}),

            OBJ('foo.bar', 'write', [42], {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [42], {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [42], {'many_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'write', [42], {'many_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'write', [42], {'many_ids': [(6, 0, [13, 17])]}),

            OBJ('foo.bar', 'write', [42], {'misc_id': False}),
            OBJ('foo.bar', 'write', [42], {'misc_id': 123}),
            OBJ('foo.bar', 'write', [42], {'misc_id': 42}),

            OBJ('foo.bar', 'write', [13, 17], {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [13, 17], {'line_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [13, 17], {'line_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'write', [13, 17], {'line_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'write', [13, 17], {'line_ids': [(6, 0, [13, 17])]}),

            OBJ('foo.bar', 'write', [13, 17], {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [13, 17], {'many_ids': [(6, 0, [])]}),
            OBJ('foo.bar', 'write', [13, 17], {'many_ids': [(6, 0, [123, 234])]}),
            OBJ('foo.bar', 'write', [13, 17], {'many_ids': [(6, 0, [76])]}),
            OBJ('foo.bar', 'write', [13, 17], {'many_ids': [(6, 0, [13, 17])]}),

            OBJ('foo.bar', 'write', [13, 17], {'misc_id': False}),
            OBJ('foo.bar', 'write', [13, 17], {'misc_id': 123}),
            OBJ('foo.bar', 'write', [13, 17], {'misc_id': 42}),
        )

        self.assertRaises(TypeError, rec.write, {'line_ids': 123})
        self.assertRaises(TypeError, records.write, {'line_ids': 123})
        self.assertRaises(TypeError, records.write, {'line_ids': rec})
        self.assertRaises(TypeError, rec.write, {'many_ids': 123})
        self.assertRaises(TypeError, records.write, {'many_ids': rec})

        self.assertCalls()
        self.assertOutput('')

    def test_copy(self):
        rec = self.env['foo.bar'].browse(42)
        records = self.env['foo.bar'].browse([13, 17])

        recopy = rec.copy()
        self.assertIsInstance(recopy, odooly.Record)
        self.assertEqual(recopy.id, 1999)

        rec.copy({'spam': 42})
        rec.copy({'spam': rec})
        rec.copy({'spam': records})
        rec.copy({})
        self.assertCalls(
            OBJ('foo.bar', 'copy', 42, None),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'copy', 42, {'spam': 42}),
            OBJ('foo.bar', 'copy', 42, {'spam': 42}),
            OBJ('foo.bar', 'copy', 42, {'spam': [13, 17]}),
            OBJ('foo.bar', 'copy', 42, {}),
        )
        self.assertOutput('')

    def test_unlink(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)

        records.unlink()
        rec.unlink()
        self.assertCalls(
            OBJ('foo.bar', 'unlink', [13, 17]),
            OBJ('foo.bar', 'unlink', [42]),
        )
        self.assertOutput('')

    def test_get_metadata(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)

        records.get_metadata()
        rec.get_metadata()
        if self.server_version in ('6.1', '7.0'):
            method = 'perm_read'
        else:
            method = 'get_metadata'
        self.assertCalls(
            OBJ('foo.bar', method, [13, 17]),
            OBJ('foo.bar', method, [42]),
        )
        self.assertOutput('')

    def test_empty_recordlist(self):
        records = self.env['foo.bar'].browse([13, 17])
        empty = records[42:]

        self.assertIsInstance(records, odooly.RecordList)
        self.assertTrue(records)
        self.assertEqual(len(records), 2)
        self.assertEqual(records.name, ['v_name'] * 2)

        self.assertIsInstance(empty, odooly.RecordList)
        self.assertFalse(empty)
        self.assertEqual(len(empty), 0)
        self.assertEqual(empty.name, [])

        self.assertCalls(
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'read', [13, 17], ['name']),
            OBJ('foo.bar', 'fields_get'),
        )

        # Calling methods on empty RecordList
        self.assertEqual(empty.read(), [])
        self.assertIs(empty.write({'spam': 'ham'}), True)
        self.assertIs(empty.unlink(), True)
        self.assertCalls()

        self.assertEqual(empty.method(), [sentinel.OTHER])
        self.assertCalls(
            OBJ('foo.bar', 'method', []),
        )
        self.assertOutput('')

    def test_attr(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)

        # attribute "id" is always present
        self.assertEqual(rec.id, 42)
        self.assertEqual(records.id, [13, 17])

        # if the attribute is not a field, it could be a specific RPC method
        self.assertEqual(rec.missingattr(), sentinel.OTHER)
        self.assertEqual(records.missingattr(), [sentinel.OTHER])

        # existing fields can be read as attributes
        # attribute is writable on the Record object only
        self.assertFalse(callable(rec.message))
        rec.message = 'one giant leap for mankind'
        self.assertFalse(callable(rec.message))
        self.assertEqual(records.message, ['v_message', 'v_message'])

        self.assertCalls(
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'missingattr', [42]),
            OBJ('foo.bar', 'missingattr', [13, 17]),
            OBJ('foo.bar', 'read', [42], ['message']),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'write', [42], {'message': 'one giant leap for mankind'}),
            OBJ('foo.bar', 'read', [42], ['message']),
            OBJ('foo.bar', 'read', [13, 17], ['message']),
        )

        # attribute "id" is never writable
        self.assertRaises(AttributeError, setattr, rec, 'id', 42)
        self.assertRaises(AttributeError, setattr, records, 'id', 42)

        # `setattr` not allowed (except for existing fields on Record object)
        self.assertRaises(AttributeError, setattr, rec, 'missingattr', 42)
        self.assertRaises(AttributeError, setattr, records, 'message', 'one')
        self.assertRaises(AttributeError, setattr, records, 'missingattr', 42)

        # method can be forgotten (any use case?)
        del rec.missingattr, records.missingattr
        # Single attribute can be deleted from cache
        del rec.message

        # `del` not allowed for attributes or missing attr
        self.assertRaises(AttributeError, delattr, rec, 'missingattr2')
        self.assertRaises(AttributeError, delattr, records, 'message')
        self.assertRaises(AttributeError, delattr, records, 'missingattr2')

        self.assertCalls()
        self.assertOutput('')

    def test_equal(self):
        rec1 = self.env['foo.bar'].get(42)
        rec2 = self.env['foo.bar'].get(42)
        rec3 = self.env['foo.bar'].get(2)
        rec4 = self.env['foo.other'].get(42)
        records1 = self.env['foo.bar'].browse([42])
        records2 = self.env['foo.bar'].browse([2, 4])
        records3 = self.env['foo.bar'].browse([2, 4])
        records4 = self.env['foo.bar'].browse([4, 2])
        records5 = self.env['foo.other'].browse([2, 4])

        self.assertEqual(rec1.id, rec2.id)
        self.assertEqual(rec1, rec2)

        self.assertNotEqual(rec1.id, rec3.id)
        self.assertEqual(rec1.id, rec4.id)
        self.assertNotEqual(rec1, rec3)
        self.assertNotEqual(rec1, rec4)

        self.assertEqual(records1.id, [42])
        self.assertNotEqual(rec1, records1)
        self.assertEqual(records2, records3)
        self.assertNotEqual(records2, records4)
        self.assertNotEqual(records2, records5)

        # if client is different, records do not compare equal
        rec2.__dict__['_model'] = sentinel.OTHER_MODEL
        self.assertNotEqual(rec1, rec2)

        self.assertCalls()
        self.assertOutput('')

    def test_add(self):
        records1 = self.env['foo.bar'].browse([42])
        records2 = self.env['foo.bar'].browse([42])
        records3 = self.env['foo.bar'].browse([13, 17])
        records4 = self.env['foo.other'].browse([4])
        rec1 = self.env['foo.bar'].get(88)

        sum1 = records1 + records2
        sum2 = records1 + records3
        sum3 = records3
        sum3 += records1
        sum4 = rec1 + records1
        sum5 = rec1 + rec1
        self.assertIsInstance(sum1, odooly.RecordList)
        self.assertIsInstance(sum2, odooly.RecordList)
        self.assertIsInstance(sum3, odooly.RecordList)
        self.assertIsInstance(sum4, odooly.RecordList)
        self.assertIsInstance(sum5, odooly.RecordList)
        self.assertEqual(sum1.id, [42, 42])
        self.assertEqual(sum2.id, [42, 13, 17])
        self.assertEqual(sum3.id, [13, 17, 42])
        self.assertEqual(records3.id, [13, 17])
        self.assertEqual(sum4.id, [88, 42])
        self.assertEqual(sum5.id, [88, 88])

        with self.assertRaises(TypeError):
            records1 + records4
        with self.assertRaises(TypeError):
            records1 + [rec1]

        self.assertCalls()
        self.assertOutput('')

    def test_read_duplicate(self):
        records = self.env['foo.bar'].browse([17, 17])

        self.assertEqual(type(records), odooly.RecordList)

        values = records.read()
        self.assertEqual(len(values), 2)
        self.assertEqual(*values)
        self.assertEqual(type(values[0]['misc_id']), odooly.Record)

        values = records.read('message')
        self.assertEqual(values, ['v_message', 'v_message'])

        values = records.read('birthdate city')
        self.assertEqual(len(values), 2)
        self.assertEqual(*values)
        self.assertEqual(values[0], {'id': 17, 'city': 'v_city',
                                     'birthdate': 'v_birthdate'})

        self.assertCalls(
            OBJ('foo.bar', 'read', [17], None),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'read', [17], ['message']),
            OBJ('foo.bar', 'read', [17], ['birthdate', 'city']),
        )
        self.assertOutput('')

    def test_str(self):
        records = odooly.RecordList(self.env['foo.bar'], [(13, 'treize'), (17, 'dix-sept')])
        rec1 = self.env['foo.bar'].browse(42)
        rec2 = records[0]
        rec3 = self.env['foo.bar'].browse(404)

        self.assertEqual(str(rec1), 'name_42')
        self.assertEqual(str(rec2), 'treize')
        self.assertEqual(rec1._name, 'name_42')
        self.assertEqual(rec2._name, 'treize')

        # Broken name_get
        self.assertEqual(str(rec3), 'foo.bar,404')

        self.assertCalls(
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'name_get', [42]),
            OBJ('foo.bar', 'name_get', [404]),
        )

        # This str() is never updated (for performance reason).
        rec1.refresh()
        rec2.refresh()
        rec3.refresh()
        self.assertEqual(str(rec1), 'name_42')
        self.assertEqual(str(rec2), 'treize')
        self.assertEqual(str(rec3), 'foo.bar,404')

        self.assertCalls()
        self.assertOutput('')

    def test_str_unicode(self):
        rec4 = self.env['foo.bar'].browse(8888)
        expected_str = expected_unicode = 'name_\xdan\xeecode'
        if PY2:
            expected_unicode = expected_str.decode('latin-1')
            expected_str = expected_unicode.encode('ascii', 'backslashreplace')
            self.assertEqual(unicode(rec4), expected_unicode)
        self.assertEqual(str(rec4), expected_str)
        self.assertEqual(rec4._name, expected_unicode)
        self.assertEqual(repr(rec4), "<Record 'foo.bar,8888'>")

        self.assertCalls(
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'name_get', [8888]),
        )

    def test_external_id(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)
        rec3 = self.env['foo.bar'].browse([17, 13, 42])

        self.assertEqual(rec._external_id, 'this_module.xml_name')
        self.assertEqual(records._external_id, [False, False])
        self.assertEqual(rec3._external_id, [False, False, 'this_module.xml_name'])

        self.assertCalls(
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar'), ('res_id', 'in', [42])]),
            OBJ('ir.model.data', 'read', [777], ['module', 'name', 'res_id']),
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar'), ('res_id', 'in', [13, 17])]),
            OBJ('ir.model.data', 'read', [777], ['module', 'name', 'res_id']),
            OBJ('ir.model.data', 'search', [('model', '=', 'foo.bar'), ('res_id', 'in', [17, 13, 42])]),
            OBJ('ir.model.data', 'read', [777], ['module', 'name', 'res_id']),
        )
        self.assertOutput('')

    def test_set_external_id(self):
        records = self.env['foo.bar'].browse([13, 17])
        rec = self.env['foo.bar'].browse(42)
        rec3 = self.env['foo.bar'].browse([17, 13, 42])

        # Assign an External ID on a record which does not have one
        records[0]._external_id = 'other_module.dummy'
        xml_domain = ['|', '&', ('model', '=', 'foo.bar'), ('res_id', '=', 13),
                      '&', ('module', '=', 'other_module'), ('name', '=', 'dummy')]
        imd_values = {'model': 'foo.bar', 'name': 'dummy',
                      'res_id': 13, 'module': 'other_module'}
        self.assertCalls(
            OBJ('ir.model.data', 'search', xml_domain),
            OBJ('ir.model.data', 'fields_get'),
            OBJ('ir.model.data', 'create', imd_values),
        )

        # Cannot assign an External ID if there's already one
        self.assertRaises(ValueError, setattr, rec, '_external_id', 'ab.cdef')
        # Cannot assign an External ID to a RecordList
        self.assertRaises(AttributeError, setattr, rec3, '_external_id', 'ab.cdef')

        # Reject invalid External IDs
        self.assertRaises(ValueError, setattr, records[1], '_external_id', '')
        self.assertRaises(ValueError, setattr, records[1], '_external_id', 'ab')
        self.assertRaises(ValueError, setattr, records[1], '_external_id', 'ab.cd.ef')
        self.assertRaises(AttributeError, setattr, records[1], '_external_id', False)
        records[1]._external_id = 'other_module.dummy'

        self.assertCalls(
            OBJ('ir.model.data', 'search', ANY),
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('ir.model.data', 'search', ANY),
            OBJ('ir.model.data', 'create', ANY),
        )
        self.assertOutput('')

    def test_ensure_one(self):
        records = self.env['foo.bar'].browse([13, 13, False])
        self.service.object.execute_kw.side_effect = []
        self.assertEqual(records.ensure_one(), records[0])
        self.assertEqual(records.ensure_one()[0], records[0])
        self.assertCalls()
        self.assertOutput('')

    def test_exists(self):
        records = self.env['foo.bar'].browse([13, 13, False])
        self.service.object.execute_kw.side_effect = [[13]]
        self.assertEqual(records.exists(), records[:1])
        self.assertCalls(
            OBJ('foo.bar', 'exists', [13]),
        )
        self.assertOutput('')

    def test_mapped(self):
        m = self.env['foo.bar']
        self.service.object.execute_kw.side_effect = [
            [{'id':k, 'fld1': 'val%s' % k} for k in [4, 17, 7, 42, 112, 13]],
            {'fld1': {'type': 'char'}, 'foo_categ_id': {'relation': 'foo.categ', 'type': 'many2one'}},
            [{'id':k, 'foo_categ_id': [k * 10, 'Categ C%04d' % k]} for k in [4, 17, 7, 42, 112, 13]],
            [{'id':k, 'foo_categ_id': [k * 10, 'Categ C%04d' % k]} for k in [4, 17, 7, 42, 112, 13]],
            [{'id':k * 10, 'fld2': 'f2_%04d' % k} for k in [4, 17, 7, 42, 112, 13]],
            {'fld2': {'type': 'char'}},
            ['fld1'],
            [(42, 'Record 42')],
            [(False, '<none>')],
            [(4, 'Record 4')],
            [(42, 'Record 42')],
            [(False, '<none>')],
            [(4, 'Record 4')],

            [{'id': 42, 'foo_categ_id': [33, 'Categ 33']}],
            [{'id': 33, 'fld2': 'c33 f2'}],
            [(42, 'Sample42')],
            [(42, 'Sample42')],

            [{'id': 88, 'foo_categ_id': [33, 'Categ 33']}],
            [{'id': 33, 'fld2': 'c33 f2'}],
            [(88, 'Sample88')],
        ]

        ids1 = [42, 13, 17, 112, 4, 7]
        idns1 = [(42, 'qude'), (13, 'trz'), (17, 'dspt'), 42, (112, 'cdz'), False, 4, (7, 'spt')]
        ids1_sorted = sorted(set(ids1) - {False})
        records1 = m.browse(idns1)
        categs = odooly.RecordList(self.env._get('foo.categ', False),
                                   [420, 130, 170, 1120, 40, 70])
        self.assertEqual(records1.mapped('fld1'),
                         [id_ and 'val%s' % id_ for id_ in records1.ids])
        self.assertEqual(records1.mapped('foo_categ_id'), categs)
        self.assertEqual(records1.mapped('foo_categ_id.fld2'),
                         ['f2_%04d' % (id_ / 10) for id_ in categs.ids])
        self.assertEqual(records1.mapped(str), [str(r) for r in records1])

        records2 = m.browse([42, 42])
        self.assertEqual(records2.mapped('foo_categ_id.fld2'), ['c33 f2'])
        self.assertEqual(records2.mapped(str), ['Sample42'] * 2)

        rec1 = m.get(88)
        self.assertEqual(rec1.mapped('foo_categ_id.fld2'), ['c33 f2'])
        self.assertEqual(rec1.mapped(str), ['Sample88'])

        self.assertRaises(TypeError, records1.mapped)

        self.assertCalls(
            OBJ('foo.bar', 'read', ids1_sorted, ['fld1']),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'read', ids1_sorted, ['foo_categ_id']),
            OBJ('foo.bar', 'read', ids1_sorted, ['foo_categ_id']),
            OBJ('foo.categ', 'read', [k * 10 for k in ids1_sorted], ['fld2']),
            OBJ('foo.categ', 'fields_get'),
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'name_get', [42]),
            OBJ('foo.bar', 'name_get', [False]),
            OBJ('foo.bar', 'name_get', [4]),
            OBJ('foo.bar', 'name_get', [42]),
            OBJ('foo.bar', 'name_get', [False]),
            OBJ('foo.bar', 'name_get', [4]),

            OBJ('foo.bar', 'read', [42], ['foo_categ_id']),
            OBJ('foo.categ', 'read', [33], ['fld2']),
            OBJ('foo.bar', 'name_get', [42]),
            OBJ('foo.bar', 'name_get', [42]),

            OBJ('foo.bar', 'read', [88], ['foo_categ_id']),
            OBJ('foo.categ', 'read', [33], ['fld2']),
            OBJ('foo.bar', 'name_get', [88]),
        )

        records3 = m.browse([])
        self.assertEqual(records3.mapped('foo_categ_id.fld2'), [])
        self.assertEqual(records3.mapped(str), [])

        self.assertCalls()
        self.assertOutput('')

    def test_filtered(self):
        m = self.env['foo.bar']
        items = [[k, 'Item %d' % k] for k in range(1, 21)]
        self.service.object.execute_kw.side_effect = [
            [{'id':k, 'flag1': not (k % 3)} for k in [4, 17, 7, 42, 112, 13]],
            {'flag1': {'type': 'boolean'},
             'foo_child_ids': {'relation': 'foo.child', 'type': 'one2many'},
             'foo_categ_id': {'relation': 'foo.categ', 'type': 'many2one'}},
            [{'id':k, 'foo_categ_id': [k * 10, 'Categ C%04d' % k]} for k in [4, 17, 7, 42, 112, 13]],
            [{'id':k, 'foo_categ_id': [k * 10, 'Categ C%04d' % k]} for k in [4, 17, 7, 42, 112, 13]],
            [{'id':k * 10, 'flag2': bool(k % 2)} for k in [4, 17, 7, 42, 112, 13]],
            {'flag2': {'type': 'char'}},
            [{'id': k, 'foo_child_ids': {}} for k in [4, 7, 112, 13]] +
            [{'id': 42, 'foo_child_ids': items[0:6]}, {'id': 17, 'foo_child_ids': items[6:8]}],
            [{'id': k, 'flag3': (k < 3)} for k in range(1, 8)],
            {'flag3': {'type': 'boolean'}},
            [{'id': k, 'flag3': (k < 3)} for k in range(1, 8)],
            [{'id': k, 'flag3': (k < 3)} for k in range(1, 8)],

            [{'id': 42, 'foo_categ_id': False}],
            [{'id': 88, 'foo_categ_id': [33, 'Categ 33']}],
            [{'id': 33, 'flag3': 'OK'}],
        ]

        ids1 = [42, 13, 17, 42, 112, 4, 7]
        idns1 = [(42, 'qude'), (13, 'trz'), (17, 'dspt'), 42, (112, 'cdz'), False, 4, (7, 'spt')]
        ids1_sorted = sorted(set(ids1) - {False})
        records1 = m.browse(idns1)
        self.assertEqual(records1.filtered('flag1'),
                         odooly.RecordList(m, [42, 42]))
        self.assertEqual(records1.filtered('foo_categ_id'),
                         odooly.RecordList(m, ids1))
        self.assertEqual(records1.filtered('foo_categ_id.flag2'),
                         odooly.RecordList(m, [13, 17, 7]))
        self.assertEqual(records1.filtered('foo_child_ids.flag3'),
                         odooly.RecordList(m, [42, 42]))
        self.assertEqual(records1.filtered(lambda m: m.id > 41),
                         odooly.RecordList(m, [42, 42, 112]))

        rec1 = m.get(88)
        self.assertEqual(m.get(42).filtered('foo_categ_id.flag3'), m.browse([]))
        self.assertEqual(rec1.filtered('foo_categ_id.flag3'), m.browse([88]))
        self.assertEqual(rec1.filtered(bool), m.browse([88]))

        self.assertRaises(TypeError, records1.filtered)

        self.assertCalls(
            OBJ('foo.bar', 'read', ids1_sorted, ['flag1']),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'read', ids1_sorted, ['foo_categ_id']),
            OBJ('foo.bar', 'read', ids1_sorted, ['foo_categ_id']),
            OBJ('foo.categ', 'read', [k * 10 for k in ids1_sorted], ['flag2']),
            OBJ('foo.categ', 'fields_get'),

            OBJ('foo.bar', 'read', ids1_sorted, ['foo_child_ids']),
            OBJ('foo.child', 'read', [1, 2, 3, 4, 5, 6], ['flag3']),
            OBJ('foo.child', 'fields_get'),
            OBJ('foo.child', 'read', [7, 8], ['flag3']),
            OBJ('foo.child', 'read', [1, 2, 3, 4, 5, 6], ['flag3']),

            OBJ('foo.bar', 'read', [42], ['foo_categ_id']),
            OBJ('foo.bar', 'read', [88], ['foo_categ_id']),
            OBJ('foo.categ', 'read', [33], ['flag3']),
        )

        records3 = m.browse([])
        self.assertEqual(records3.filtered('foo_categ_id.fld2'), records3)
        self.assertEqual(records3.filtered(str), records3)

        self.assertCalls()
        self.assertOutput('')

    def test_sorted(self):
        m = self.env['foo.bar']
        self.service.object.execute_kw.side_effect = [
            [42, 4, 7, 17, 112],
            [42, 4, 7, 17, 112],
            [{'id':k, 'fld1': 'val%s' % k} for k in [4, 17, 7, 42, 112, 13]],
            {'fld1': {'type': 'char'}},
            [{'id':k, 'fld1': 'val%s' % k} for k in [4, 17, 7, 42, 112, 13]],
            ['fld1'],
            [(4, 'Record 4')],
            [(4, 'Record 4')],

            [{'id':k} for k in [4, 17, 7, 42, 112]],
        ]

        ids1 = [42, 13, 17, 112, 4, 7]
        idns1 = [(42, 'qude'), (13, 'trz'), (17, 'dspt'), 42, (112, 'cdz'), False, 4, (7, 'spt')]
        ids1_sorted = sorted(set(ids1) - {False})
        records1 = m.browse(idns1)
        self.assertEqual(records1.sorted(),
                         odooly.RecordList(m, [42, 4, 7, 17, 112]))
        self.assertEqual(records1.sorted(reverse=True),
                         odooly.RecordList(m, [112, 17, 7, 4, 42]))
        self.assertEqual(records1.sorted('fld1'),
                         odooly.RecordList(m, [112, 13, 17, 4, 42, 7]))
        self.assertEqual(records1.sorted('fld1', reverse=True),
                         odooly.RecordList(m, [7, 42, 4, 17, 13, 112]))
        self.assertEqual(records1.sorted(str),
                         odooly.RecordList(m, [4, 112, 17, 42, 7, 13]))
        self.assertEqual(records1.sorted(str, reverse=True),
                         odooly.RecordList(m, [13, 7, 42, 17, 112, 4]))

        self.assertRaises(KeyError, records1.sorted, 'fld1.fld2')

        self.assertCalls(
            OBJ('foo.bar', 'search', [('id', 'in', ids1)]),
            OBJ('foo.bar', 'search', [('id', 'in', ids1)]),
            OBJ('foo.bar', 'read', ids1_sorted, ['fld1']),
            OBJ('foo.bar', 'fields_get'),
            OBJ('foo.bar', 'read', ids1_sorted, ['fld1']),
            OBJ('foo.bar', 'fields_get_keys'),
            OBJ('foo.bar', 'name_get', [4]),
            OBJ('foo.bar', 'name_get', [4]),

            OBJ('foo.bar', 'read', ids1_sorted, ['fld1.fld2']),
        )

        records2 = m.browse([42, 42])
        self.assertEqual(records2.sorted(reverse=True), records2[:1])
        self.assertEqual(records2.sorted('foo_categ_id', reverse=True), records2[:1])
        self.assertEqual(records2.sorted(str, reverse=True), records2[:1])

        records3 = m.browse([])
        self.assertEqual(records3.sorted(reverse=True), records3)
        self.assertEqual(records3.sorted('foo_categ_id', reverse=True), records3)
        self.assertEqual(records3.sorted(str, reverse=True), records3)

        rec1, expected = m.get(88), odooly.RecordList(m, [88])
        self.assertEqual(rec1.sorted(reverse=True), expected)
        self.assertEqual(rec1.sorted('foo_categ_id', reverse=True), expected)
        self.assertEqual(rec1.sorted(str, reverse=True), expected)

        self.assertCalls()
        self.assertOutput('')


class TestModel90(TestModel):
    server_version = '9.0'


class TestRecord90(TestRecord):
    server_version = '9.0'


class TestModel11(TestModel):
    server_version = '11.0'


class TestRecord11(TestRecord):
    server_version = '11.0'
