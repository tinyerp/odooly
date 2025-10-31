Changelog
---------


2.4.x (unreleased)
~~~~~~~~~~~~~~~~~~

* For WebAPI and JSON-RPC, do not print traceback for common
  Odoo errors, like ``UserError`` and ``ValidationError``.

* Fix ``sudo()`` KeyError in some cases.

* Do not raise an error when a field is read on a ghost :class:`Record`.


2.4.5 (2025-10-30)
~~~~~~~~~~~~~~~~~~

* Configure ``server = ...`` instead of ``scheme / host / port / protocol``.

* Better error message for ``in`` operator on :class:`RecordList`.

* Use ``display_name`` instead of ``name_get()`` for Odoo >= 8,
  because ``name_get`` is deprecated in Odoo 17 and removed in Odoo 18.

* Remove workaround not needed anymore for interactive console.
  Issue was fixed in Python source code.


2.4.4 (2025-10-16)
~~~~~~~~~~~~~~~~~~

* Support ``{...}`` string format for :meth:`RecordList.read`
  and :meth:`Model.read`.

* Use ``search_read`` method with Odoo >= 8.

* Fix cache when switching between environments.

* Use a separate HTTP session when using JSON-2 API Key.

* Change :meth:`Model.sudo` and :meth:`RecordList.sudo` to
  become Superuser, on Odoo >= 12.

* Fix ResourceWarning with Python 3.14.


2.4.3 (2025-10-12)
~~~~~~~~~~~~~~~~~~

* Add operators ``not =like`` and ``not =ilike`` for Odoo 19.

* Fix API Key authentication for RPC protocols.

* Able to connect with HTTP redirection. For example:
  ``odooly --server http://demo.odoo.com``

* Add method :meth:`Client.save` to save current environment in
  memory, with a name.  Change :meth:`Client.get_config` to a
  class method.

* Fix command line usage with a list of IDs.

* Keep ``env.user.login`` when ``env.user.refresh()`` is called.

* Obfuscate :attr:`Env.context` in cache key.


2.4.2 (2025-10-08)
~~~~~~~~~~~~~~~~~~

* Fix :meth:`Client.clone_database`.

* New method :meth:`Env.set_api_key`.


2.4.1 (2025-10-06)
~~~~~~~~~~~~~~~~~~

* Catch and format authentication error properly.

* Print errors when ``verbose`` is enabled.

* Fix 2FA authentication retry, when code is invalid.

* Fix incorrect data serialization when JSON is empty ``{}``.

* Try to login even if ``database`` is not set, with Odoo >= 10.

* Fix Web authentication for Odoo 10 to 14.

* Ask for confirmation before (un)installing dependent modules.

* Propose database selector when needed, even for JSON-2 authentication.

* Support ``--api-key`` on the command line.


2.4.0 (2025-10-03)
~~~~~~~~~~~~~~~~~~

* Store :attr:`Env.session_info` when it is retrieved with Webclient API.
  Insert ``user_context``  into ``session_info`` when RPC API is used.

* Add a database selector for Webclient API.

* Method ``exists`` becomes private with Odoo 19.

* Fix method :meth:`Env.upgrade_cancel` for Odoo 19.

* Fix parsing version of Saas instances.

* New static method :meth:`Client.get_config`

* Support JSON-2 API with Odoo >= 19.

* Configure ``api_key`` separately.  Allow to use JSON-2 even
  if ``password`` is not configured.

* New method :meth:`Env.generate_api_key` for Odoo >= 14.

* Support methods protected by ``check_identity``, for Odoo >= 14.


2.3.2 (2025-10-01)
~~~~~~~~~~~~~~~~~~

* Print HTTP error status when error occurs.

* Support ``env._web.session('get_session_info')`` as alternative to
  ``client.web_session.get_session_info()``, for example.

* When using Webclient, ``database =`` configuration becomes optional.

* Method :meth:`Model.sudo` defaults to ``'admin'`` user, instead of UID 1.

* Simplify authentication, passwords are encrypted since Odoo 12 and
  values cannot be retrieved by ``'admin'``.

* Add API overview table to the documentation: availability and authentication
  mode per Odoo version.


2.3.1 (2025-09-30)
~~~~~~~~~~~~~~~~~~

* Fix ``context_get`` arguments.

* Do not authenticate with ``/web/session/authenticate`` when
  protocol is ``jsonrpc`` or ``xmlrpc``.  It cannot authenticate API keys.

* Experimental support for 2FA with Webclient session, with Odoo >= 15.

* Fix PyPI classifiers.

* Update documentation.


2.3.0 (2025-09-29)
~~~~~~~~~~~~~~~~~~

* Support webclient :class:`WebAPI` protocol as an alternative:
  ``/web/dataset/*``, ``/web/database/*``, ...
  Webclient API is stable since Odoo 9.

* Authenticate with ``/web/session/authenticate`` by default
  and retrieve :attr:`Env.session_info`, with Odoo >= 9.

* Use Webclient API by default when ``protocol`` is not set.
  It is same as setting ``protocol = web``.

* New function :meth:`Client.drop_database`.

* New functions to create/destroy a session:
  :meth:`Env.session_authenticate` and :meth:`Env.session_destroy`.

* Drop support for Python 3.5


2.2.1 (2025-09-24)
~~~~~~~~~~~~~~~~~~

* Support method :meth:`Model.create` with a list of values.
  With Odoo >= 12.

* Support method :meth:`RecordList.copy`.
  With Odoo >= 18.

* Extend local mode to support Odoo >= 15.

* Fix :meth:`Env.uninstall`.

* Add helper :meth:`Env.upgrade_cancel` to reset module states.


2.2.0 (2025-09-16)
~~~~~~~~~~~~~~~~~~

* Support for Odoo 17, 18 and 19.

* Support Python 3.12 and 3.13.

* Drop support for Python 2.7 and Python 3.4.

* Enable Github Actions CI. Remove Travis CI.

* Support new search operators: `any|not any|parent_of`.


2.1.9 (2019-10-02)
~~~~~~~~~~~~~~~~~~

* No change.  Re-upload to PyPI.


2.1.8 (2019-10-02)
~~~~~~~~~~~~~~~~~~

* Default location for the configuration file is the
  initial working directory.

* Enhanced syntax for method :meth:`RecordList.filtered`.
  E.g. instead of ``records.filtered(lambda r: r.type == 'active')``
  it's faster to use ``records.filtered(['type = active'])``.

* Support unary operators even for Python 3.

* Basic sequence operations on :class:`Env` instance.


2.1.7 (2019-03-20)
~~~~~~~~~~~~~~~~~~

* No change.  Re-upload to PyPI.


2.1.6 (2019-03-20)
~~~~~~~~~~~~~~~~~~

* Fix :meth:`RecordList.mapped` method with empty one2many or
  many2many fields.

* Hide arguments of ``partial`` objects.


2.1.5 (2019-02-12)
~~~~~~~~~~~~~~~~~~

* Fix new feature of 2.1.4.


2.1.4 (2019-02-12)
~~~~~~~~~~~~~~~~~~

* Support ``env['res.partner'].browse()`` and return an empty
  ``RecordList``.


2.1.3 (2019-01-09)
~~~~~~~~~~~~~~~~~~

* Fix a bug where method ``with_context`` returns an error if we update
  the values of the logged-in user before.

* Allow to call RPC method ``env['ir.default'].get(...)`` thanks to a
  passthrough in the :meth:`Model.get` method.


2.1.2 (2019-01-02)
~~~~~~~~~~~~~~~~~~

* Store the cursor :attr:`Env.cr` on the :class:`Env` instance
  in local mode.

* Drop support for Python 3.2 and 3.3


2.1.1 (2019-01-02)
~~~~~~~~~~~~~~~~~~

* Do not call ORM method ``exists`` on an empty list because it fails
  with OpenERP.

* Provide cursor :attr:`Env.cr` in local mode, even with OpenERP
  instances.

* Optimize and fix method :meth:`RecordList.filtered`.


2.1 (2018-12-27)
~~~~~~~~~~~~~~~~

* Allow to bypass SSL verification if the server is misconfigured.
  Environment variable ``ODOOLY_SSL_UNVERIFIED=1`` is detected.

* Accept multiple command line arguments for local mode. Example:
  ``odooly -- --config path/to/odoo.conf --data-dir ./var``

* Add ``self`` to the ``globals()`` in interactive mode, to mimic
  Odoo shell.

* On login, assign the context of the user:
  ``env['res.users'].context_get()``.  Do not copy the context when
  switching database, or when connecting with a different user.

* Drop attribute ``Client.context``.  It is only available as
  :attr:`Env.context`.

* Fix hashing error when :attr:`Env.context` contains a list.

* Assign the model name to ``Record._name``.

* Fix installation/upgrade with an empty list.

* Catch error when database does not exist on login.

* Format other Odoo errors like ``DatabaseExists``.


2.0 (2018-12-12)
~~~~~~~~~~~~~~~~

* Fix cache of first ``Env`` in interactive mode.

* Correctly invalidate the cache after installing/upgrading add-ons.

* Add tests for :meth:`Model.with_context`, :meth:`Model.sudo` and
  :meth:`Env.sudo`.

* Copy the context when switching database.

* Change interactive prompt ``sys.ps2`` to ``"     ... "``.


2.0b3 (2018-12-10)
~~~~~~~~~~~~~~~~~~

* Provide :meth:`Env.sudo` in addition to same method on ``Model``,
  ``RecordList`` and ``Record`` instances.

* Workflows and method ``object.exec_workflow`` are removed in Odoo 11.

* Do not prevent login if access to ``Client.db.list()`` is denied.

* Use a cache of :class:`Env` instances.


2.0b2 (2018-12-05)
~~~~~~~~~~~~~~~~~~

* Add documentation for methods :meth:`RecordList.exists` and
  :meth:`RecordList.ensure_one`.

* Add documentation for methods :meth:`RecordList.mapped`,
  :meth:`RecordList.filtered` and :meth:`RecordList.sorted`.

* Add documentation for methods :meth:`Model.with_env`,
  :meth:`Model.sudo` and :meth:`Model.with_context`.  These methods
  are also available on :class:`RecordList` and :class:`Record`.

* Changed method ``exists`` on :class:`RecordList` and :class:`Record`
  to return record(s) instead of ids.

* Fix methods ``mapped``, ``filtered`` and ``sorted``. Add tests.

* Fix method ``RecordList.ensure_one()`` when there's identical ids
  or ``False`` values.

* Fix method ``RecordList.union(...)`` and related boolean operations.


2.0b1 (2018-12-04)
~~~~~~~~~~~~~~~~~~

* First release of Odooly, which mimics the new Odoo 8.0 API.

* Other features are copied from `ERPpeek
  <https://github.com/tinyerp/erppeek>`__ 1.7.
