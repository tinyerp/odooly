from functools import partial
from unittest import TestCase

from odooly import issearchdomain, searchargs, Model, Client, Printer


class TestUtils(TestCase):

    def test_issearchdomain(self):
        self.assertFalse(issearchdomain(None))
        self.assertFalse(issearchdomain(42))
        self.assertFalse(issearchdomain('42'))
        self.assertFalse(issearchdomain([1, 42]))
        self.assertFalse(issearchdomain(['1', '42']))

        self.assertTrue(issearchdomain([('name', '=', 'mushroom'),
                                        ('state', '!=', 'draft')]))
        self.assertTrue(issearchdomain(['name = mushroom', 'state != draft']))
        self.assertTrue(issearchdomain([]))

        # Removed with 1.6
        self.assertFalse(issearchdomain('state != draft'))
        self.assertFalse(issearchdomain(('state', '!=', 'draft')))

    def test_searchargs(self):
        domain = [('name', '=', 'mushroom'), ('state', '!=', 'draft')]

        self.assertEqual(searchargs(([],)), ([],))
        self.assertEqual(searchargs((domain,)), (domain,))
        self.assertEqual(searchargs((False,)), (False,))    # Odoo >= 19
        self.assertEqual(searchargs((True,)), (True,))      # Odoo >= 19
        self.assertEqual(searchargs((['name = mushroom', 'state != draft'],)),
                         (domain,))
        self.assertEqual(searchargs((['status=Running'],)),
                         ([('status', '=', 'Running')],))
        self.assertEqual(searchargs((['state="in_use"'],)),
                         ([('state', '=', 'in_use')],))
        self.assertEqual(searchargs((['spam.ham in(1, 2)'],)),
                         ([('spam.ham', 'in', (1, 2))],))
        self.assertEqual(searchargs((['spam in(1, 2)'],)),
                         ([('spam', 'in', (1, 2))],))

        # Standard comparison operators
        self.assertEqual(searchargs((['ham=2'],)), ([('ham', '=', 2)],))
        self.assertEqual(searchargs((['ham!=2'],)), ([('ham', '!=', 2)],))
        self.assertEqual(searchargs((['ham>2'],)), ([('ham', '>', 2)],))
        self.assertEqual(searchargs((['ham>=2'],)), ([('ham', '>=', 2)],))
        self.assertEqual(searchargs((['ham<2'],)), ([('ham', '<', 2)],))
        self.assertEqual(searchargs((['ham<=2'],)), ([('ham', '<=', 2)],))

        # Combine with unary operators
        self.assertEqual(searchargs((['ham=- 2'],)), ([('ham', '=', -2)],))
        self.assertEqual(searchargs((['ham<+ 2'],)), ([('ham', '<', 2)],))

        # Operators rarely used
        self.assertEqual(searchargs((['status =like Running'],)),
                         ([('status', '=like', 'Running')],))
        self.assertEqual(searchargs((['status=like Running'],)),
                         ([('status', '=like', 'Running')],))
        self.assertEqual(searchargs((['status =ilike Running'],)),
                         ([('status', '=ilike', 'Running')],))
        self.assertEqual(searchargs((['status =? Running'],)),
                         ([('status', '=?', 'Running')],))
        self.assertEqual(searchargs((['status=?Running'],)),
                         ([('status', '=?', 'Running')],))

        for oper in ('like', 'not like', 'ilike', 'not ilike', 'not =like',
                     'not =ilike', 'any', 'not any', 'child_of', 'parent_of'):
            self.assertEqual(searchargs((['status %s Running' % oper],)),
                             ([('status', oper, 'Running')],))

    def test_searchargs_date(self):
        # Do not interpret dates as integers
        self.assertEqual(searchargs((['create_date > "2001-12-31"'],)),
                         ([('create_date', '>', '2001-12-31')],))
        self.assertEqual(searchargs((['create_date > 2001-12-31'],)),
                         ([('create_date', '>', '2001-12-31')],))

        self.assertEqual(searchargs((['create_date > 2001-12-31 23:59:00'],)),
                         ([('create_date', '>', '2001-12-31 23:59:00')],))

        # Not a date, but it should be parsed as string too
        self.assertEqual(searchargs((['port_nr != 122-2'],)),
                         ([('port_nr', '!=', '122-2')],))

    def test_searchargs_digits(self):
        # Do not convert digits to octal
        self.assertEqual(searchargs((['code = 042'],)), ([('code', '=', '042')],))
        self.assertEqual(searchargs((['code > 042'],)), ([('code', '>', '042')],))
        self.assertEqual(searchargs((['code > 420'],)), ([('code', '>', 420)],))

        # Standard octal notation is supported
        self.assertEqual(searchargs((['code = 0o42'],)), ([('code', '=', 34)],))

        # Other numeric literals are still supported
        self.assertEqual(searchargs((['duration = 0'],)), ([('duration', '=', 0)],))
        self.assertEqual(searchargs((['price < 0.42'],)), ([('price', '<', 0.42)],))

        # Overflow for integers, not for float
        self.assertEqual(searchargs((['phone = 41261234567'],)),
                         ([('phone', '=', '41261234567')],))
        self.assertEqual(searchargs((['elapsed = 67891234567.0'],)),
                         ([('elapsed', '=', 67891234567.0)],))

    def test_searchargs_invalid(self):

        # Not recognized as a search domain
        self.assertEqual(searchargs(('state != draft',)), ('state != draft',))
        self.assertEqual(searchargs((('state', '!=', 'draft'),)),
                         (('state', '!=', 'draft'),))

        # Operators == and <> are deprecated in Odoo 19, operator == is a typo
        self.assertRaises(ValueError, searchargs, (['ham==2'],))
        self.assertRaises(ValueError, searchargs, (['ham == 2'],))
        self.assertRaises(ValueError, searchargs, (['ham <> 2'],))
        self.assertRaises(ValueError, searchargs, (['ham<>2'],))

        # Mixed-up operators
        self.assertRaises(ValueError, searchargs, (['ham =! 2'],))
        self.assertRaises(ValueError, searchargs, (['ham =< 2'],))
        self.assertRaises(ValueError, searchargs, (['ham => 2'],))
        self.assertRaises(ValueError, searchargs, (['ham ?= 2'],))

        self.assertRaises(ValueError, searchargs, (['ham='],))
        self.assertRaises(ValueError, searchargs, (['ham on salad'],))
        self.assertRaises(ValueError, searchargs, (['spam.hamin(1, 2)'],))
        self.assertRaises(ValueError, searchargs, (['spam.hamin (1, 2)'],))
        self.assertRaises(ValueError, searchargs, (['spamin (1, 2)'],))
        self.assertRaises(ValueError, searchargs, (['[id = 1540]'],))
        self.assertRaises(ValueError, searchargs, (['some_id child_off'],))
        self.assertRaises(ValueError, searchargs, (['someth like3'],))

    def test_readfmt(self):
        dummy = object.__new__(Model)
        readfmt = partial(dummy._parse_format, browse=False)

        # Helper for 'read' methods
        (fields, fmt) = readfmt('a %(color)s elephant enters %(location)r.\n\n%(firstname)s has left')
        self.assertEqual(fields, ['color', 'location', 'firstname'])

        (fields, fmt) = readfmt('a {color} elephant enters {location[1]}.\n\n{firstname!r} has left')
        self.assertEqual(fields, ['color', 'location', 'firstname'])

    def test_printer(self):
        # Verbosity None or 0   --> disable logging
        # Verbosity 1 to 8      --> mapped 1 -> 79 / 2 -> 179 / 3+ -> 9999
        # Verbosity >= 36       --> width to print in columns
        client = object.__new__(Client)
        client._printer = Printer()
        client.verbose = 2
        self.assertEqual(client._printer.cols, 179)
        self.assertEqual(client.verbose, 179)
        client.verbose = 3
        self.assertEqual(client._printer.cols, 9999)
        client.verbose = 250
        self.assertEqual(client._printer.cols, 250)
        client.verbose = None
        self.assertIsNone(client._printer.cols)
        client.verbose = 64
        self.assertEqual(client._printer.cols, 64)
        self.assertEqual(client.verbose, 64)
        client.verbose = True
        self.assertEqual(client._printer.cols, 79)
        client.verbose = 8
        self.assertEqual(client._printer.cols, 9999)
        self.assertEqual(client.verbose, 9999)
        client.verbose = 0
        self.assertIsNone(client._printer.cols)

        self.assertRaises(TypeError, setattr, client, 'verbose', 'a')
        self.assertRaises(IndexError, setattr, client, 'verbose', -4)
