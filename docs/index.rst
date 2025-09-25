.. Odooly documentation master file, created by
   sphinx-quickstart on Tue Aug 21 09:47:49 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


Odooly's documentation
=======================

*A versatile tool for browsing Odoo / OpenERP data*

The Odooly library communicates with any `Odoo / OpenERP server`_ (>= 6.1)
using the Webclient API or `the deprecated external RPC interface`_ (JSON-RPC or XML-RPC).

It provides both a :ref:`fully featured low-level API <client-and-services>`,
and an encapsulation of the methods on :ref:`Active Record objects
<model-and-records>`.  It implements the Odoo API.
Additional helpers are provided to explore the model and administrate the
server remotely.

The :doc:`intro` describes how to use it as a :ref:`command line tool
<command-line>` or within an :ref:`interactive shell <interactive-mode>`.

The :doc:`tutorial` gives an in-depth look at the capabilities.



Contents:

.. toctree::
   :maxdepth: 2

   intro
   API <api>
   tutorial
   developer

* Online documentation: https://odooly.readthedocs.io/
* Source code and issue tracker: https://github.com/tinyerp/odooly

.. _Odoo / OpenERP server: https://www.odoo.com/documentation/
.. _the deprecated external RPC interface: https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`


Credits
=======

Authored and maintained by Florent Xicluna.
