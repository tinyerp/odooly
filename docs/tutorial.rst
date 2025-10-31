.. currentmodule:: odooly

========
Tutorial
========

This tutorial demonstrates some features of Odooly in the interactive shell.

It assumes an Odoo server is installed.
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

    ~$ odooly

It assumes that the server is running locally, and listens on default
port ``8069``.

If our configuration is different, then we use arguments, like::

    ~$ odooly --server http://192.168.0.42:8069

It connects using the Webclient API.

In case we use a different protocol, we can set the endpoint explicitly.
For example ``/jsonrpc`` for the JSON-RPC API::

    ~$ odooly --server http://127.0.0.1:8069/jsonrpc


.. note::

    These protocols JSON-RPC and XML-RPC are deprecated in Odoo 19 and will
    be removed in Odoo 20.

On login, it prints few lines about the commands available.

.. sourcecode:: pycon

    ~$ odooly
    Usage (some commands):
        env[name]                       # Return a Model instance
        env[name].keys()                # List field names of the model
        env[name].fields(names=None)    # Return details for the fields
        env[name].field(name)           # Return details for the field
        env[name].browse(ids=())
        env[name].search(domain)
        env[name].search(domain, offset=0, limit=None, order=None)
                                        # Return a RecordList

        rec = env[name].get(domain)     # Get the Record matching domain
        rec.some_field                  # Return the value of this field
        rec.read(fields=None)           # Return values for the fields

        client.login(user)              # Login with another user
        client.connect(env_name)        # Connect to another env.
        client.connect(server=None)     # Connect to another server
        env.models(name)                # List models matching pattern
        env.modules(name)               # List modules matching pattern
        env.install(module1, module2, ...)
        env.upgrade(module1, module2, ...)
                                        # Install or upgrade the modules
        env.upgrade_cancel()            # Reset failed upgrade/install

And it confirms that the default database is not available::

    ...
    Error: Database 'odoo' does not exist: []

Though, we have a connected client, ready to use::

    >>> client
    <Client 'http://localhost:8069/web?db='>
    >>> client.server_version
    '18.0'
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
    <Client 'http://localhost:8069/web?db=demo'>
    >>> client.database.list()
    ['demo']
    >>> env
    <Env 'admin@demo'>
    >>> env.modules(installed=True)
    {'installed': ['base', 'web', 'web_mobile', 'web_tests']}
    >>> len(env.modules()['uninstalled'])
    1398
    >>> #

.. note::

   Create an ``odooly.ini`` file in the current directory to declare all our
   environments.  Example::

       [DEFAULT]
       server = http://localhost:8069/web

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
    <Client 'http://localhost:8069/web?db=demo_test'>
    >>> client.database.list()
    ['demo', 'demo_test']
    >>> env
    <Env 'admin@demo_test'>
    >>> client.modules(installed=True)
    {'installed': ['base', 'web', 'web_mobile', 'web_tests']}
    >>> len(client.modules()['uninstalled'])
    1398
    >>> #


Find the users
--------------

We have created the database ``"demo"`` for the tests.
We are connected to this database as ``'admin'``.

Where is the table for the users?

.. sourcecode:: pycon

    >>> client
    <Client 'http://localhost:8069/web?db=demo'>
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
     'context_tz', 'date', 'group_ids', 'id', 'login', 'menu_id', 'menu_tips',
     'name', 'new_password', 'password', 'signature', 'user_email', 'view']
    >>> env['res.users'].field('company_id')
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
    <RecordList 'res.groups,length=7'>
    >>> admin_user.groups_id.full_name
    ['Administration / Access Rights',
     'Technical / Access to export feature',
     'Bypass HTML Field Sanitize',
     'Extra Rights / Contact Creation',
     'User types / Internal User',
     'Administration / Settings',
     'Extra Rights / Technical Features']
    >>> admin_user.get_metadata()
    [{'create_date': '2024-10-01 10:08:20',
      'create_uid': False,
      'id': 1,
      'noupdate': True,
      'write_date': '2024-10-01 10:08:30',
      'write_uid': [1, 'System'],
      'xmlid': 'base.user_root',
      'xmlids': [{'noupdate': True, 'xmlid': 'base.user_root'}]}]


Create a new user
-----------------

Now we want a non-admin user to continue the exploration.
Let's create ``Joe``.

.. sourcecode:: pycon

    >>> env['res.users'].create({'name': 'Joe'})
    odoo.exceptions.ValidationError: The operation cannot be completed:
    - Create/update: a mandatory field is not set.
    - Delete: another model requires the record being deleted. If possible, archive it instead.

    Model: User (res.users)
    Field: Login (login)
    >>> #

It seems we've forgotten some mandatory data.  Let's give him a ``name`` and a ``login``.

.. sourcecode:: pycon

    >>> env['res.users'].create({'login': 'joe', 'name': 'Joe'})
    <Record 'res.users,3'>
    >>> joe_user = _
    >>> joe_user.groups_id.full_name
    ['Technical / Access to export feature',
     'Extra Rights / Contact Creation',
     'User types / Internal User',
     'Extra Rights / Technical Features']

The user ``Joe`` does not have a password: we cannot login as ``joe``.
We set a password for ``Joe`` and we try again.

.. sourcecode:: pycon

    >>> client.login('joe')
    Password for 'joe':
    Error: Invalid username or password
    >>> env.user.login
    'admin'
    >>> joe_user.password = 'bartender'
    >>> client.login('joe')
    Logged in as 'joe'
    >>> env.user.login
    'joe'
    >>> #

Success!


Explore the model
-----------------

We keep connected as user ``Joe`` and we explore the world around us.

.. sourcecode:: pycon

    >>> env.user.login
    'joe'
    >>> all_models = env.models()
    odoo.exceptions.AccessError: You are not allowed to access 'Models' (ir.model) records.

    This operation is allowed for the following groups:
            - Administration/Access Rights

    Contact your administrator to request access if necessary.
    >>> all_models = env.sudo().models()
    >>> len(all_models)
    140

Among these 140 objects, some of them are ``read-only``, others are
``read-write``.  We can also filter the ``non-empty`` models.

.. sourcecode:: pycon

    >>> # Read-only models
    >>> len([m for m in all_models if not env[m].access('write')])
    116
    >>> #
    >>> # Writable but cannot delete
    >>> [m for m in all_models if env[m].access('write') and not env[m].access('unlink')]
    ['base.language.export',
     'base.partner.merge.automatic.wizard',
     'base_import.import',
     'res.users.identitycheck']
    >>> #
    >>> # Unreadable models
    >>> len([m for m in all_models if not env[m].access('read')])
    94
    >>> #
    >>> # Now print the number of entries in all (readable) models
    >>> for m in all_models:
    ...     if m == 'res.users.apikeys.show':
    ...         continue  # This one returns an error
    ...     mcount = env[m].access() and env[m].search_count()
    ...     if not mcount:
    ...         continue
    ...     print('%4d  %s' % (mcount, m))
    ...
       1  iap.service
       1  ir.attachment
       1  ir.default
      22  ir.ui.menu
       7  report.layout
       3  report.paperformat
       2  res.bank
       1  res.company
     250  res.country
       6  res.country.group
    1780  res.country.state
       1  res.currency
     162  res.currency.rate
      11  res.groups
       1  res.lang
      38  res.partner
       1  res.partner.bank
       7  res.partner.category
      21  res.partner.industry
       5  res.partner.title
       4  res.users
       1  res.users.settings
    >>> #
    >>> # Show the content of a model
    >>> config_params = env['ir.config_parameter'].sudo().search([])
    >>> config_params.read('[{id:2}]  {key:30} {value}')
    ['[ 8]  base.default_max_email_size    10',
     '[ 5]  base.login_cooldown_after      10',
     '[ 6]  base.login_cooldown_duration   60',
     '[ 7]  base.template_portal_user_id   5',
     '[10]  base_setup.default_user_rights True',
     '[ 9]  base_setup.show_effect         True',
     '[ 3]  database.create_date           2024-10-01 06:10:24',
     '[ 1]  database.secret                88888888-8888-8888-8888-888888888888',
     '[ 2]  database.uuid                  77777777-7777-7777-7777-777777777777',
     '[ 4]  web.base.url                   http://localhost:8069']


Browse the records
------------------

Query the ``"res.country"`` model::

    >>> env['res.country'].keys()
    ['address_format', 'code', 'name']
    >>> env['res.country'].search(['name like public'])
    <RecordList 'res.country,[...]'>
    >>> env['res.country'].search(['name like public']).name
    ['Central African Republic',
     'Czech Republic',
     'Democratic Republic of the Congo',
     'Dominican Republic']
    >>> env['res.country'].search(['code > X'], order='code ASC').read('{code} {name}')
    ['XK Kosovo',
     'YE Yemen',
     'YT Mayotte',
     'ZA South Africa',
     'ZM Zambia',
     'ZW Zimbabwe']
    >>> #


... the tutorial is done.

Jump to the :doc:`api` for further details.
