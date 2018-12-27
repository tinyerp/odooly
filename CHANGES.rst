Changelog
---------


2.x (unreleased)
~~~~~~~~~~~~~~~~

* Allow to bypass SSL verification if the server is misconfigured.
  Environment variable ``ODOOLY_SSL_UNVERIFIED=1`` is detected.

* Accept multiple command line arguments for local mode. Example:
  ``odooly -- --config path/to/odoo.conf --data-dir ./var``

* Add ``self`` to the ``globals()`` in interactive mode, to mimic
  Odoo shell.

* Fix hashing error when ``Env.context`` contains a list.

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
