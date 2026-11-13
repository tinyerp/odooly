.. currentmodule:: odooly

Introduction
============

This section gives the bare minimum to use Odooly within a Python
:ref:`interactive shell <interactive-mode>`.

Installation
------------

Download and install the `latest release
<https://pypi.org/project/Odooly>`__ from PyPI::

    uv tool install -U odooly[requests]

Or::

    pip install -U odooly[requests]

As an alternative, ``uv`` can invoke Odooly without installing::

    uvx odooly --help
    uvx odooly https://demo.odoo.com/ -u demo


.. _interactive-mode:

.. include:: ../README.rst
   :start-after: _interactive-mode:

More details in the :doc:`tutorial` section.
