==========
Odooly API
==========

.. module:: odooly

The library provides few objects to access the Odoo model and the
associated services of `the Odoo API`_.

The signature of the methods mimics the standard methods provided by the
:class:`osv.Model` Odoo class.  This is intended to help the developer when
developping addons.  What is experimented at the interactive prompt should
be portable in the application with little effort.

.. contents::
   :local:


.. _client-and-services:

Client and Services
-------------------

The :class:`Client` object provides thin wrappers around Odoo RPC services
and their methods.  Additional helpers are provided to explore the models and
list or install Odoo add-ons.


.. autoclass:: Client

.. automethod:: Client.from_config

.. automethod:: Client.create_database

.. automethod:: Client.clone_database

.. automethod:: Client.login

.. attribute:: Client.context

   Default context used for all the methods (default ``None``).
   In :ref:`interactive mode <interactive-mode>`, this default context
   contains the language of the shell environment (variable ``LANG``).
   Do not update the context, either copy it or replace it::

       # Set language to German
       client.context = {'lang': 'de_DE', 'preferred_color': 'blue'}
       # ... do something

       # Switch to Italian
       client.context = dict(client.context, lang='it_IT')
       # ... do something

       # and AVOID (because it changes the context of existing records)
       client.context['lang'] = 'fr_FR'


.. note::

   In :ref:`interactive mode <interactive-mode>`, a method
   :attr:`Client.connect(env=None)` exists, to connect to another environment,
   and recreate the :func:`globals()`.


Odoo RPC Services
~~~~~~~~~~~~~~~~~

The naked Odoo RPC services are exposed too.
The :attr:`~Client.db` and the :attr:`~Client.common` services expose few
methods which might be helpful for server administration.  Use the
:func:`dir` function to introspect them.  The :attr:`~Client._object`
service should not be used directly because its methods are wrapped and
exposed on the :class:`Env` object itself.
The two last services are deprecated and removed in recent versions of Odoo.
Please refer to `the Odoo documentation`_ for more details.


.. attribute:: Client.db

   Expose the ``db`` :class:`Service`.

   Examples: :meth:`Client.db.list` or :meth:`Client.db.server_version`
   RPC methods.

.. attribute:: Client.common

   Expose the ``common`` :class:`Service`.

   Example: :meth:`Client.common.login_message` RPC method.

.. data:: Client._object

   Expose the ``object`` :class:`Service`.

.. attribute:: Client._report

   Expose the ``report`` :class:`Service`.

   Removed in Odoo 11.

.. attribute:: Client._wizard

   Expose the ``wizard`` :class:`Service`.

   Removed in OpenERP 7.

.. autoclass:: Service
   :members:
   :undoc-members:

.. _the Odoo documentation:
.. _the Odoo API: http://doc.odoo.com/v6.1/developer/12_api.html#api


Environment
-----------

.. autoclass:: Env
   :members: lang, execute, access, models, ref, __getitem__, sudo, odoo_env, registry
   :undoc-members:

   .. attribute:: db_name

      Environment's database name.

   .. attribute:: uid

      Environment's user id.

   .. attribute:: user

      Instance of the environment's user.

   .. attribute:: context

      Environment's context dictionary.

   .. attribute:: cr

      Cursor on the current database.


.. note::

   When connected to the local Odoo server, the `Env.odoo_env` attribute
   grabs an Odoo Environment with the same characteristics as the `Env`
   instance (db_name, uid, context).
   In this case a cursor on the database is available as `Env.cr`.


Advanced methods
~~~~~~~~~~~~~~~~

Those methods give more control on the Odoo objects: workflows and reports.
Please refer to `the Odoo documentation`_ for details.


.. automethod:: Env.execute(obj, method, *params, **kwargs)

.. method:: Env.exec_workflow(obj, signal, obj_id)

   Wrapper around ``object.exec_workflow`` RPC method.

   Argument `obj` is the name of the model.  The `signal` is sent to
   the object identified by its integer ``id`` `obj_id`.

   Removed in Odoo 11.

.. method:: Env.report(obj, ids, datas=None)

   Wrapper around ``report.report`` RPC method.

   Removed in Odoo 11.

.. method:: Env.render_report(obj, ids, datas=None)

   Wrapper around ``report.render_report`` RPC method.

   Removed in Odoo 11.

.. method:: Env.report_get(report_id)

   Wrapper around ``report.report_get`` RPC method.

   Removed in Odoo 11.

.. method:: Env.wizard_create(wiz_name, datas=None)

   Wrapper around ``wizard.create`` RPC method.

   Removed in OpenERP 7.

.. method:: Env.wizard_execute(wiz_id, datas, action='init', context=None)

   Wrapper around ``wizard.execute`` RPC method.

   Removed in OpenERP 7.


Manage addons
~~~~~~~~~~~~~

These helpers are convenient to list, install or upgrade addons from a
Python script or interactively in a Python session.

.. automethod:: Env.modules

.. automethod:: Env.install

.. automethod:: Env.upgrade

.. automethod:: Env.uninstall

.. note::

   It is not recommended to install or upgrade modules in offline mode when
   any web server is still running: the operation will not be signaled to
   other processes.  This restriction does not apply when connected through
   XML-RPC or JSON-RPC.


.. _model-and-records:

Model and Records
-----------------

The :class:`Env` provides a high level API similar to the Odoo API, which
encapsulates objects into `Active Records
<http://www.martinfowler.com/eaaCatalog/activeRecord.html>`_.

The :class:`Model` is instantiated using the ``client.env[...]`` syntax.

Example: ``client.env['res.company']`` returns a :class:`Model`.

.. autoclass:: Model(client, model_name)

   .. automethod:: keys

   .. automethod:: fields

   .. automethod:: field

   .. automethod:: access

   .. automethod:: search(domain, offset=0, limit=None, order=None)

   .. automethod:: search_count(domain)

   .. automethod:: read(domain, fields=None, offset=0, limit=None, order=None)

   .. automethod:: get(domain)

   .. automethod:: browse(ids)

   .. automethod:: create

   .. automethod:: with_env(env)

   .. automethod:: sudo(user=SUPERUSER_ID)

   .. automethod:: with_context([context][, **overrides])

   .. automethod:: _get_external_ids

..
   search count read ...
   write copy unlink

.. autoclass:: RecordList(model, ids)

   .. method:: read(fields=None)

      Wrapper for the :meth:`Record.read` method.

      Return a :class:`RecordList` if `fields` is the name of a single
      ``many2one`` field, else return a :class:`list`.
      See :meth:`Model.read` for details.

   .. method:: write(values)

      Wrapper for the :meth:`Record.write` method.

   .. method:: unlink()

      Wrapper for the :meth:`Record.unlink` method.

   .. automethod:: exists()

   .. automethod:: mapped(func)

   .. automethod:: filtered(func)

   .. automethod:: sorted(key=None, reverse=False)

   .. automethod:: ensure_one()

   .. automethod:: union(*args)

   .. automethod:: concat(*args)

   .. automethod:: with_env(env)

   .. automethod:: sudo(user=SUPERUSER_ID)

   .. automethod:: with_context([context][, **overrides])

   .. method:: get_metadata()

      Wrapper for the :meth:`Record.get_metadata` method.

   .. attribute:: _external_id

      Retrieve the External IDs of the :class:`RecordList`.

      Return the list of fully qualified External IDs of
      the :class:`RecordList`, with default value False if there's none.
      If multiple IDs exist for a record, only one of them is returned.

.. autoclass:: Record(model, id)
   :members: read, write, copy, unlink, _send, _external_id, refresh
   :undoc-members:

   .. automethod:: exists()

   .. method:: get_metadata(details=True)

      Lookup metadata about the record(s).
      Return dictionaries with the following keys:

       * ``id``: object id
       * ``create_uid``: user who created the record
       * ``create_date``: date when the record was created
       * ``write_uid``: last user who changed the record
       * ``write_date``: date of the last change to the record
       * ``xmlid``: External ID to use to refer to this record (if there is one),
         in format ``module.name``.


Utilities
---------

.. autofunction:: issearchdomain

.. autofunction:: searchargs

.. autofunction:: format_exception(type, value, tb, limit=None, chain=True)

.. autofunction:: read_config

.. autofunction:: start_odoo_services
