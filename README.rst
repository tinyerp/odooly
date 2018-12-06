=========================================================
Odooly, a versatile tool for browsing Odoo / OpenERP data
=========================================================

Download and install the latest release::

    pip install -U odooly

.. contents::
   :local:
   :backlinks: top

Documentation and tutorial: http://odooly.readthedocs.org

CI tests: https://travis-ci.org/tinyerp/odooly


Overview
--------

Odooly carries three completing uses:

(1) with command line arguments
(2) as an interactive shell
(3) as a client library


Key features:

- provides an API very close to the Odoo API 8.0, through JSON-RPC and XML-RPC
- compatible with OpenERP 6.1 through Odoo 12.0
- single executable ``odooly.py``, no external dependency
- helpers for ``search``, for data model introspection, etc...
- simplified syntax for search ``domain`` and ``fields``
- full API accessible on the ``Client.env`` environment
- the module can be imported and used as a library: ``from odooly import Client``
- supports Python 3 and Python 2.7



.. _command-line:

Command line arguments
----------------------

There are few arguments to query Odoo models from the command line.
Although it is quite limited::

    $ odooly --help

    Usage: odooly.py [options] [search_term_or_id [search_term_or_id ...]]

    Inspect data on Odoo objects.  Use interactively or query a model (-m) and
    pass search terms or ids as positional parameters after the options.

    Options:
      --version             show program's version number and exit
      -h, --help            show this help message and exit
      -l, --list            list sections of the configuration
      --env=ENV             read connection settings from the given section
      -c CONFIG, --config=CONFIG
                            specify alternate config file (default: 'odooly.ini')
      --server=SERVER       full URL of the server (default:
                            http://localhost:8069/xmlrpc)
      -d DB, --db=DB        database
      -u USER, --user=USER  username
      -p PASSWORD, --password=PASSWORD
                            password, or it will be requested on login
      -m MODEL, --model=MODEL
                            the type of object to find
      -f FIELDS, --fields=FIELDS
                            restrict the output to certain fields (multiple
                            allowed)
      -i, --interact        use interactively; default when no model is queried
      -v, --verbose         verbose
    $ #


Example::

    $ odooly -d demo -m res.partner -f name -f lang 1
    "name","lang"
    "Your Company","en_US"

::

    $ odooly -d demo -m res.groups -f full_name 'id > 0'
    "full_name"
    "Administration / Access Rights"
    "Administration / Configuration"
    "Human Resources / Employee"
    "Usability / Multi Companies"
    "Usability / Extended View"
    "Usability / Technical Features"
    "Sales Management / User"
    "Sales Management / Manager"
    "Partner Manager"



.. _interactive-mode:

Interactive use
---------------

Edit ``odooly.ini`` and declare the environment(s)::

    [DEFAULT]
    scheme = http
    host = localhost
    port = 8069
    database = odoo
    username = admin

    [demo]
    username = demo
    password = demo
    protocol = xmlrpc

    [demo_jsonrpc]
    username = demo
    password = demo
    protocol = jsonrpc

    [local]
    scheme = local
    options = -c /path/to/odoo-server.conf --without-demo all


Connect to the Odoo server::

    odooly --list
    odooly --env demo


This is a sample session::

    >>> env['res.users']
    <Model 'res.users'>
    >>> env['res.users'].search_count()
    4
    >>> crons = env['ir.cron'].with_context(active_test=False).search([])
    >>> crons.read('active name')
    [{'active': True, 'id': 5, 'name': 'Calendar: Event Reminder'},
     {'active': False, 'id': 4, 'name': 'Mail: Fetchmail Service'}]
    >>> #
    >>> env.modules('delivery')
    {'uninstalled': ['delivery', 'website_sale_delivery']}
    >>> env.upgrade('base')
    1 module(s) selected
    42 module(s) to process:
      to upgrade    account
      to upgrade    account_chart
      to upgrade    account_tax_include
      to upgrade    base
      ...
    >>> #


.. note::

   Use the ``--verbose`` switch to see what happens behind the scene.
   Lines are truncated at 79 chars.  Use ``-vv`` or ``-vvv`` to print
   more.


.. note::

   To preserve the history of commands when closing the session, first
   create an empty file in your home directory:
   ``touch ~/.odooly_history``
