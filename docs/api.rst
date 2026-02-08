==========
Odooly API
==========

.. module:: odooly

The library provides few objects to access the Odoo model and the
associated services of `the Odoo API`_.

The signature of the methods mimics the standard methods provided by the
:class:`odoo.models.Model` Odoo class.  This is intended to help the developer
when developping addons.  What is experimented at the interactive prompt
should be portable in the application with little effort.

.. contents::
   :local:


.. _client-and-services:

Client and Services
-------------------

The :class:`Client` object provides thin wrappers around Odoo Webclient API
and RPC services and their methods.  Additional helpers are provided on the
``Client.env`` environment, to explore the models and to list or to install
Odoo add-ons.  Please refer to :class:`Env` documentation below.


.. autoclass:: Client

.. automethod:: Client.from_config

.. automethod:: Client.create_database

.. automethod:: Client.clone_database

.. automethod:: Client.drop_database

.. automethod:: Client.login

.. automethod:: Client.save

.. automethod:: Client.get_config

.. attribute:: Client.env

   Current :class:`Env` environment of the client.


.. note::

   In :ref:`interactive mode <interactive-mode>`, a method
   :attr:`Client.connect(env=None, server=None, user=None)` exists, to connect
   to another environment, and recreate the :func:`globals()`.

.. note::

   If the HTTPS server certificate is invalid, there's a trick to bypass the
   certificate verification, when the environment variable is set
   ``ODOOLY_SSL_UNVERIFIED=1``.


Odoo Webclient API
~~~~~~~~~~~~~~~~~~

These HTTP routes were developed for the Odoo Web application.  They are used
by Odooly to provide high level methods on :class:`Env` and :class:`Model`.
The :attr:`~Client.database` endpoint exposes few methods which might be helpful
for database management.  Use :func:`dir` function to introspect them.

.. attribute:: Client.database

   Expose the ``/web/database`` :class:`WebAPI`.

   Example: :meth:`Client.database.list` method.

.. attribute:: Client.web

   Expose the root ``/web`` :class:`WebAPI`.

.. attribute:: Client.web_dataset

   Expose the ``/web/dataset`` :class:`WebAPI`.

.. attribute:: Client.web_session

   Expose the ``/web/session`` :class:`WebAPI`.

.. attribute:: Client.web_webclient

   Expose the ``/web/webclient`` :class:`WebAPI`.

.. autoclass:: WebAPI
   :members:
   :undoc-members:

.. autoclass:: Json2
   :members: __call__, doc
   :undoc-members:


Odoo RPC Services
~~~~~~~~~~~~~~~~~

The Odoo RPC services are exposed too. They could be used for server and
database operations.
The :attr:`~Client.db` and the :attr:`~Client.common` services provided
methods which might be helpful for server administration.  Use the
:func:`dir` function to introspect them.  The :attr:`~Client._object`
service should not be used directly.  It provides same feature as the
:attr:`~Client.web_dataset` Webclient endpoint.  Use :class:`Env` and :class:`Model`
instead.
Please refer to `the Odoo documentation`_ for more details.

.. note::

   These RPC services are deprecated in Odoo 19.  They are scheduled
   for removal in Odoo 20.

.. attribute:: Client.db

   Expose the ``db`` :class:`Service`.

   Examples: :meth:`Client.db.list` or :meth:`Client.db.server_version`
   RPC methods.

   Removed in Odoo 20.

.. attribute:: Client.common

   Expose the ``common`` :class:`Service`.

   Example: :meth:`Client.common.login_message` RPC method.

   Removed in Odoo 20.

.. data:: Client._object

   Expose the ``object`` :class:`Service`.

   Removed in Odoo 20.

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
.. _the Odoo API: https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html


Environment
-----------

.. autoclass:: Env
   :members: lang, access, models, ref, __getitem__, odoo_env, registry
   :undoc-members:

   .. attribute:: db_name

      Environment's database name.

   .. attribute:: uid

      Environment's user id.

   .. attribute:: user

      Instance of the environment's user.

   .. attribute:: context

      Environment's context dictionary.
      It defaults to the ``lang`` and ``tz`` of the user.
      Use :meth:`Model.with_context` to switch the context.
      For example ``env['account.invoice'].with_context({})`` can be used
      to call a method which does not accept the ``context`` argument.

   .. attribute:: cr

      Cursor on the current database.

   .. automethod:: generate_api_key

   .. automethod:: set_api_key

   .. automethod:: session_authenticate

   .. automethod:: session_destroy

   .. attribute:: session_info

      Dictionary returned when a Webclient session is authenticated.
      It contains ``uid`` and ``user_context`` among other user's preferences
      and server parameters.

   .. automethod:: sudo(user=SUPERUSER_ID)


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

.. method:: Env._call_kw(obj, method, params, kw=None)

   Expose the ``/web/dataset/call_kw`` endpoint.

.. method:: Env._json2(obj, method, params, kw=None)

   Expose the ``/json/2`` endpoint.

   Added in Odoo 19.

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

.. automethod:: Env.upgrade_cancel

.. note::

   It is not recommended to install or upgrade modules in offline mode when
   any web server is still running: the operation will not be signaled to
   other processes.  This restriction does not apply when connected through
   Webclient API or other RPC API.


.. _model-and-records:

Model and Records
-----------------

The :class:`Env` provides a high level API similar to the Odoo API, which
encapsulates objects into `Active Records
<https://www.martinfowler.com/eaaCatalog/activeRecord.html>`_.

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

   .. automethod:: _methods([name])

..
   search count read ...
   write copy unlink

.. autoclass:: RecordList(model, ids)

   .. method:: read(fields=None)

      Same as :meth:`Record.read` method.

      Return a :class:`RecordList` if `fields` is the name of a single
      ``many2one`` field, else return a :class:`list`.
      See :meth:`Model.read` for details.

   .. method:: write(values)

      Same as :meth:`Record.write` method.

   .. method:: unlink()

      Same as :meth:`Record.unlink` method.

   .. automethod:: copy()

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

      Same as :meth:`Record.get_metadata` method.

   .. method:: _methods([name])

      Same as :meth:`Model._methods` method.

   .. attribute:: _external_id

      Retrieve the External IDs of the :class:`RecordList`.

      Return the list of fully qualified External IDs of
      the :class:`RecordList`, with default value False if there's none.
      If multiple IDs exist for a record, only one of them is returned.

   .. attribute:: _keys

      Return list of field names.

   .. attribute:: _fields

      Return a dictionary of the fields.

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

   .. method:: _methods([name])

      Same as :meth:`Model._methods` method.

   .. attribute:: _keys

      Return list of field names.

   .. attribute:: _fields

      Return a dictionary of the fields.


Utilities
---------

.. autofunction:: issearchdomain

.. autofunction:: searchargs

.. autofunction:: format_exception(type, value, tb, limit=None, chain=True)

.. autofunction:: read_config

.. autofunction:: start_odoo_services
