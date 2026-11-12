"""Odoo client library and command line tool"""
__version__ = '3.0.0'

from .client import Client
from .environment import Env
from .exceptions import Error, ServerError
from .models import BaseModel, BaseRecord, Model, Record, RecordList

__all__ = ['Client', 'Env', 'Error', 'ServerError',
           'BaseModel', 'Model', 'BaseRecord', 'Record', 'RecordList']
