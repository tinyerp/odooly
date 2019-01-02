#!/usr/bin/env python
import sys

from setuptools import setup

if (3, 0) < sys.version_info < (3, 4):
    # Package 'unittest2' does not discover tests on Python 3.2 and 3.3
    setup(
        tests_require=['mock', 'unittest2py3k'],
        test_suite='unittest2.collector.collector',
    )
else:
    setup()
