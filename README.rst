=================================
Odooly, a versatile tool for Odoo
=================================

Download and install the latest release::

    pip install -U odooly

.. contents::
   :local:
   :backlinks: top

Documentation and tutorial: https://odooly.readthedocs.io/


Overview
--------

Odooly connects to an Odoo instance through HTTP.  It makes it easy to browse the application model,
and to perform actions.  It carries three modes of use:

(1) with command line arguments
(2) as an interactive shell
(3) as a client library


Key features:

- provides an API similar to Odoo Model, through Webclient API
- supports JSON-2 API with Odoo 19 and more recent
- supports external APIs JSON-RPC and XML-RPC as alternative
- compatible with Odoo 8 to 19, and OpenERP
- single file ``odooly.py``, no external dependency
- helpers for ``search``, for data model introspection, etc...
- simplified syntax for search ``domain``
- entire API accessible on the ``Client.env`` environment
- can be imported and used as a library: ``from odooly import Client``
- supports Python 3.6 and more recent



.. _interactive-mode:

Interactive use
---------------

Launch without any configuration.  It connects to the Odoo server, local or remote::

    ~$ odooly --server https://demo.odoo.com/

Or::

    ~$ odooly --server http://127.0.0.1:8069/


Environments can also be declared in ``odooly.ini``::

    [DEFAULT]
    scheme = http
    host = localhost
    port = 8069
    database = odoo
    username = admin

    [demo]
    username = demo
    password = demo
    protocol = web

    [demo_jsonrpc]
    username = demo
    password = demo
    protocol = jsonrpc

    [local]
    scheme = local
    options = -c /path/to/odoo-server.conf --without-demo all


Connect to the Odoo server::

    ~$ odooly --list
    ~$ odooly --env demo


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
   more.  Example::

       ~$ odooly --server https://demo.odoo.com/ -vv

   It's also possible to set verbosity from the interactive prompt::

       >>> client._printer.cols = 180

.. note::

   To preserve the commands' history when closing the session, first
   create an empty file in your home directory::

       ~$ touch ~/.odooly_history



.. _command-line:

Command line arguments
----------------------

There are few arguments to query Odoo models from the command line.
Although it is quite limited::

    ~$ odooly --help

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
                            http://localhost:8069/web)
      -d DB, --db=DB        database
      -u USER, --user=USER  username
      -p PASSWORD, --password=PASSWORD
                            password, or it will be requested on login
      --api-key=API_KEY     API Key for JSON2 or JSON-RPC/XML-RPC

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
