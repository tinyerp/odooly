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
and to perform actions on the server.  It is both an interactive shell (with pretty-printing and colors)
and a client library.


Key features:

- provides an API similar to Odoo Model, through Webclient API
- supports JSON-2 API with Odoo 19 and more recent
- supports external API JSON-RPC as alternative
- compatible with Odoo 9 to 20
- single file ``odooly.py``, no external dependency
- helpers for ``search``, for data model introspection, etc...
- simplified syntax for search ``domain``
- entire API accessible on the ``Client.env`` environment
- can be imported and used as a library: ``from odooly import Client``
- supports Python 3.8 and more recent



.. _interactive-mode:

Interactive use
---------------

Launch without any configuration.  It connects to the Odoo server, local or remote::

    ~$ odooly https://demo.odoo.com/

Or::

    ~$ odooly http://127.0.0.1:8069/


Environments can also be declared in ``odooly.ini``::

    [DEFAULT]
    database = odoo
    username = admin

    [demo]
    server = http://localhost:8069/web
    username = demo
    password = demo

    [demo/jsonrpc]
    server = http://localhost:8069/jsonrpc
    username = demo
    password = demo

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

   With Python 3.14, output is colored by default, and new Python REPL
   console is used.  Colored output can be activated with previous Python
   versions, through environment variable ``FORCE_COLOR``.

   To opt-out, use environment variable ``NO_COLOR=1``.

   Use the ``-v/--verbose`` switch to see what happens behind the scene.
   Lines are truncated at 79 chars.  Use ``-vv`` or ``-vvv`` to print
   more.  Example::

       ~$ FORCE_COLOR=1 odooly https://demo.odoo.com/ -vv

   It's also possible to set verbosity from the interactive prompt::

       >>> client.verbose = 160  # Max line length

.. note::

   To preserve the commands' history when closing the session, first
   create an empty file in your home directory::

       ~$ touch ~/.odooly_history
