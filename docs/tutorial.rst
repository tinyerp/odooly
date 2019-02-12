.. currentmodule:: odooly

========
Tutorial
========

This tutorial demonstrates some features of Odooly in the interactive shell.

It assumes an Odoo or OpenERP server is installed.
The shell is a true Python shell.  We have access to all the features and
modules of the Python interpreter.

.. contents:: Steps:
   :local:
   :backlinks: top


First connection
----------------

The server is freshly installed and does not have an Odoo database yet.
The tutorial creates its own database ``demo`` to play with.

Open the Odooly shell::

    $ odooly

It assumes that the server is running locally, and listens on default
port ``8069``.

If our configuration is different, then we use arguments, like::

    $ odooly --server http://192.168.0.42:8069

It connects using the XML-RPC protocol. If you want to use the JSON-RPC
protocol instead, then pass the full URL with ``/jsonrpc`` path::

    $ odooly --server http://127.0.0.1:8069/jsonrpc


On login, it prints few lines about the commands available.

.. sourcecode:: pycon

    $ odooly
    Usage (some commands):
        env[name]                       # Return a Model instance
        env[name].keys()                # List field names of the model
        env[name].fields(names=None)    # Return details for the fields
        env[name].field(name)           # Return details for the field
        env[name].browse(ids=None)
        env[name].search(domain)
        env[name].search(domain, offset=0, limit=None, order=None)
                                        # Return a RecordList

        rec = env[name].get(domain)     # Get the Record matching domain
        rec.some_field                  # Return the value of this field
        rec.read(fields=None)           # Return values for the fields

        client.login(user)              # Login with another user
        client.connect(env)             # Connect to another env.
        env.models(name)                # List models matching pattern
        env.modules(name)               # List modules matching pattern
        env.install(module1, module2, ...)
        env.upgrade(module1, module2, ...)
                                        # Install or upgrade the modules

And it confirms that the default database is not available::

    ...
    Error: Database 'odoo' does not exist: []

Though, we have a connected client, ready to use::

    >>> client
    <Client 'http://localhost:8069/xmlrpc#()'>
    >>> client.server_version
    '6.1'
    >>> #


Create a database
-----------------

We create the database ``"demo"`` for this tutorial.
We need to know the superadmin password before to continue.
This is the ``admin_passwd`` in the ``odoo-server.conf`` file.
Default password is ``"admin"``.

.. note:: This password gives full control on the databases. Set a strong
          password in the configuration to prevent unauthorized access.


.. sourcecode:: pycon

    >>> client.create_database('super_password', 'demo')
    Logged in as 'admin'
    >>> client
    <Client 'http://localhost:8069/xmlrpc#demo'>
    >>> client.db.list()
    ['demo']
    >>> env
    <Env 'admin@demo'>
    >>> env.modules(installed=True)
    {'installed': ['base', 'web', 'web_mobile', 'web_tests']}
    >>> len(env.modules()['uninstalled'])
    202
    >>> #

.. note::

   Create an ``odooly.ini`` file in the current directory to declare all our
   environments.  Example::

       [DEFAULT]
       host = localhost
       port = 8069

       [demo]
       database = demo
       username = joe

   Then we connect to any environment with ``odooly --env demo`` or switch
   during an interactive session with ``client.connect('demo')``.


Clone a database
----------------

It is sometimes useful to clone a database (testing, backup, migration, ...).
A shortcut is available for that, the required parameters are the new
database name and the superadmin password.


.. sourcecode:: pycon

    >>> client.clone_database('super_password', 'demo_test')
    Logged in as 'admin'
    >>> client
    <Client 'http://localhost:8069/xmlrpc#demo_test'>
    >>> client.db.list()
    ['demo', 'demo_test']
    >>> env
    <Env 'admin@demo'>
    >>> client.modules(installed=True)
    {'installed': ['base', 'web', 'web_mobile', 'web_tests']}
    >>> len(client.modules()['uninstalled'])
    202
    >>> #


Find the users
--------------

We have created the database ``"demo"`` for the tests.
We are connected to this database as ``'admin'``.

Where is the table for the users?

.. sourcecode:: pycon

    >>> client
    <Client 'http://localhost:8069/xmlrpc#demo'>
    >>> env.models('user')
    ['res.users', 'res.users.log']

We've listed two models which matches the name, ``res.users`` and
``res.users.log``.  Through the environment :class:`Env` we reach the users'
model and we want to introspect its fields.
Fortunately, the :class:`Model` class provides methods to retrieve all
the details.

.. sourcecode:: pycon

    >>> env['res.users']
    <Model 'res.users'>
    >>> print(env['res.users'].keys())
    ['action_id', 'active', 'company_id', 'company_ids', 'context_lang',
     'context_tz', 'date', 'groups_id', 'id', 'login', 'menu_id', 'menu_tips',
     'name', 'new_password', 'password', 'signature', 'user_email', 'view']
    >>> env['res.users'].field('company')
    {'change_default': False,
     'company_dependent': False,
     'context': {'user_preference': True},
     'depends': [],
     'domain': [],
     'help': 'The company this user is currently working for.',
     'manual': False,
     'readonly': False,
     'relation': 'res.company',
     'required': True,
     'searchable': True,
     'sortable': True,
     'store': True,
     'string': 'Company',
     'type': 'many2one'}
    >>> #

Let's examine the ``'admin'`` user in details.

.. sourcecode:: pycon

    >>> env['res.users'].search_count()
    1
    >>> admin_user = env['res.users'].browse(1)
    >>> admin_user.groups_id
    <RecordList 'res.groups,[1, 2, 3]'>
    >>> admin_user.groups_id.name
    ['Access Rights', 'Configuration', 'Employee']
    >>> admin_user.groups_id.full_name
    ['Administration / Access Rights',
     'Administration / Configuration',
     'Human Resources / Employee']
    >>> admin_user.get_metadata()
    {'create_date': False,
     'create_uid': False,
     'id': 1,
     'write_date': '2012-09-01 09:01:36.631090',
     'write_uid': [1, 'Administrator'],
     'xmlid': 'base.user_admin'}


Create a new user
-----------------

Now we want a non-admin user to continue the exploration.
Let's create ``Joe``.

.. sourcecode:: pycon

    >>> env['res.users'].create({'login': 'joe'})
    Fault: Integrity Error

    The operation cannot be completed, probably due to the following:
    - deletion: you may be trying to delete a record while other records still reference it
    - creation/update: a mandatory field is not correctly set

    [object with reference: name - name]
    >>> #

It seems we've forgotten some mandatory data.  Let's give him a ``name``.

.. sourcecode:: pycon

    >>> env['res.users'].create({'login': 'joe', 'name': 'Joe'})
    <Record 'res.users,3'>
    >>> joe_user = _
    >>> joe_user.groups_id.full_name
    ['Human Resources / Employee', 'Partner Manager']

The user ``Joe`` does not have a password: we cannot login as ``joe``.
We set a password for ``Joe`` and we try again.

.. sourcecode:: pycon

    >>> client.login('joe')
    Password for 'joe':
    Error: Invalid username or password
    >>> env.user
    'admin'
    >>> joe_user.password = 'bar'
    >>> client.login('joe')
    Logged in as 'joe'
    >>> env.user
    'joe'
    >>> #

Success!


Explore the model
-----------------

We keep connected as user ``Joe`` and we explore the world around us.

.. sourcecode:: pycon

    >>> env.user
    'joe'
    >>> all_models = env.models()
    >>> len(all_models)
    92

Among these 92 objects, some of them are ``read-only``, others are
``read-write``.  We can also filter the ``non-empty`` models.

.. sourcecode:: pycon

    >>> # Read-only models
    >>> len([m for m in all_models if not env[m].access('write')])
    44
    >>> #
    >>> # Writable but cannot delete
    >>> [m for m in all_models if env[m].access('write') and not env[m].access('unlink')]
    ['ir.property', 'web.planner']
    >>> #
    >>> # Unreadable models
    >>> [m for m in all_models if not env[m].access('read')]
    ['ir.actions.todo',
     'ir.actions.todo.category',
     'res.payterm']
    >>> #
    >>> # Now print the number of entries in all (readable) models
    >>> for m in all_models:
    ...     mcount = env[m].access() and env[m].search_count()
    ...     if not mcount:
    ...         continue
    ...     print('%4d  %s' % (mcount, m))
    ... 
       1  ir.actions.act_url
      64  ir.actions.act_window
      14  ir.actions.act_window.view
      76  ir.actions.act_window_close
      76  ir.actions.actions
       4  ir.actions.client
       4  ir.actions.report
       3  ir.actions.server
       1  ir.default
     112  ir.model
    3649  ir.model.data
    1382  ir.model.fields
      33  ir.ui.menu
     221  ir.ui.view
       3  report.paperformat
       1  res.company
     249  res.country
       2  res.country.group
     678  res.country.state
       2  res.currency
       9  res.groups
       1  res.lang
       5  res.partner
      21  res.partner.industry
       5  res.partner.title
       1  res.request.link
       4  res.users
      12  res.users.log
    >>> #
    >>> # Show the content of a model
    >>> config_params = env['ir.config_parameter'].search([])
    >>> config_params.read('key value')
    [{'id': 1, 'key': 'web.base.url', 'value': 'http://localhost:8069'},
     {'id': 2, 'key': 'database.create_date', 'value': '2012-09-01 09:01:12'},
     {'id': 3,
      'key': 'database.uuid',
      'value': '52fc9630-f49e-2222-e622-08002763afeb'}]


Browse the records
------------------

Query the ``"res.country"`` model::

    >>> env['res.country'].keys()
    ['address_format', 'code', 'name']
    >>> env['res.country'].search(['name like public'])
    <RecordList 'res.country,[41, 42, 57, 62, 144]'>
    >>> env['res.country'].search(['name like public']).name
    ['Central African Republic',
     'Congo, Democratic Republic of the',
     'Czech Republic',
     'Dominican Republic',
     'Macedonia, the former Yugoslav Republic of']
    >>> env['res.country'].search(['code > Y'], order='code ASC').read('code name')
    [{'code': 'YE', 'id': 247, 'name': 'Yemen'},
     {'code': 'YT', 'id': 248, 'name': 'Mayotte'},
     {'code': 'ZA', 'id': 250, 'name': 'South Africa'},
     {'code': 'ZM', 'id': 251, 'name': 'Zambia'},
     {'code': 'ZW', 'id': 253, 'name': 'Zimbabwe'}]
    >>> #

..
    env['res.country'].search(['code > Y'], order='code ASC').read('%(code)s %(name)s')

... the tutorial is done.

Jump to the :doc:`api` for further details.
