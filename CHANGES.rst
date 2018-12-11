Changelog
---------


2.x (unreleased)
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

* Other features are copied from ERPpeek 1.7.
