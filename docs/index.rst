.. Odooly documentation master file, created by
   sphinx-quickstart on Tue Aug 21 09:47:49 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


Odooly - client for Odoo
========================

*A versatile tool for Odoo*

The Odooly library communicates with any `Odoo server`_ using the Webclient API.
If an ``api_key`` is configured, it will use the JSON-2 endpoint with Odoo 19.
It can also connect through the `deprecated external RPC interface`_ (JSON-RPC).

It provides both a :ref:`fully featured low-level API <client-and-services>`,
and an encapsulation of the methods on :ref:`Active Record objects
<model-and-records>`.  It implements the Odoo ORM API.
Additional helpers are provided to explore the model and administrate the
server remotely.

The :doc:`intro` describes how to use it within a Python
:ref:`interactive shell <interactive-mode>`.

The :doc:`tutorial` gives an in-depth look at the capabilities.


Authentication methods per Odoo version, and per API:


============= ============ ========= ========== ========== =========
 Odoo \\ API    Webclient   Public     JSON-2    JSON-RPC   XML-RPC
============= ============ ========= ========== ========== =========
 22.0 +       | Login 2FA             API Key     *( both removed )*
              | Login       no-auth
------------- ------------ --------- ---------- --------------------
 19.0 to 21.0 | Login 2FA             API Key   | API Key *(deprecated)*
              | Login       no-auth             | Login *(deprecated)*
------------- ------------ --------- ---------- --------------------
 15.0 to 18.0 | Login 2FA                       | API Key  | API Key
              | Login       no-auth             | Login    | Login
------------- ------------ --------- ---------- ---------- ---------
 14.0                                           | API Key  | API Key
               Login        no-auth             | Login    | Login
------------- ------------ --------- ---------- ---------- ---------
 8.0 to 13.0   Login        no-auth              Login      Login
------------- ------------ --------- ---------- ---------- ---------
 6.1 and 7.0   Login        no-auth                         Login
============= ============ ========= ========== ========== =========

.. note:: So called Public API is available without authentication. For
          example ``/web/webclient/version_info``.  The ``/web/database/*``
          endpoints are public, although they require the Master password as argument.


Contents:

.. toctree::
   :maxdepth: 2

   intro
   API <api>
   tutorial
   developer

* Online documentation: https://odooly.readthedocs.io/
* Source code and issue tracker: https://github.com/tinyerp/odooly

.. _Odoo server: https://www.odoo.com/documentation/
.. _deprecated external RPC interface: https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`


Credits
=======

Authored and maintained by Florent Xicluna.
