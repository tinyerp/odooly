Changelog
---------


2.x.x (unreleased)
~~~~~~~~~~~~~~~~~~

* Drop support for Python 3.4


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
