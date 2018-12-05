Changelog
---------


2.x (unreleased)
~~~~~~~~~~~~~~~~

* Add documentation for methods :meth:`RecordList.exists` and
  :meth:`RecordList.ensure_one`.

* Changed method ``exists`` on :class:`RecordList` and :class:`Record`
  to return record(s) instead of ids.

* Fix method ``RecordList.ensure_one()`` when there's identical ids
  or ``False`` values.

* Fix method :meth:`RecordList.union` and related boolean operations.


2.0b1 (2018-12-04)
~~~~~~~~~~~~~~~~~~

* First release of Odooly, which mimics the new Odoo 8.0 API.

* Other features are copied from ERPpeek 1.7.
