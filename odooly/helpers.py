import _ast
import datetime
import functools
import re
import traceback

from .exceptions import Error, ServerError

DOMAIN_OPERATORS = frozenset('!|&')
# Supported operators are:
#   =, !=, >, >=, <, <=, like, ilike, in, not like, not ilike, not in,
#   =like, =ilike, =?, child_of, parent_of,
#   any, not any,                             # Odoo 17
#   not =like, not =ilike,                    # Odoo 19
_term_re = re.compile(
    r'([\w._]+)\s*'   r'(=like\b|=ilike\b|=\?|[<>]=?|!?=|'
    r'\b(?:like|ilike|in|any|not (?:=?like|=?ilike|in|any)|child_of|parent_of)\b)'
    r'(?![?!=<>])\s*(.+)')
_cause_message = ("\nThe above exception was the direct cause "
                  "of the following exception:\n\n")
base_method_params = [
    ('action_archive', ['ids']),
    ('action_unarchive', ['ids']),
    ('copy', ['ids', 'default']),
    ('create', ['vals_list']),
    ('get_external_id', ['ids']),
    ('get_metadata', ['ids']),
    ('read', ['ids', 'fields', 'load']),
    ('search', ['domain', 'offset', 'limit', 'order']),
    ('search_count', ['domain', 'limit']),
    ('search_read', ['domain', 'fields', 'offset', 'limit', 'order']),
    ('unlink', ['ids']),
    ('write', ['ids', 'vals']),
]


def memoize(inst, attr, value, doc_values=None):
    if hasattr(value, '__get__') and not hasattr(value, '__self__'):
        value.__name__ = attr
        if doc_values is not None:
            value.__doc__.format(*doc_values)
        value = value.__get__(inst, type(inst))
    inst.__dict__[attr] = value
    return value


# Simplified ast.literal_eval which does not parse operators
def _convert(node):
    if isinstance(node, _ast.Constant) and node.value.__class__ is not complex:
        return node.value
    if isinstance(node, _ast.Tuple):
        return tuple(map(_convert, node.elts))
    if isinstance(node, _ast.List):
        return [*map(_convert, node.elts)]
    if isinstance(node, _ast.Dict):
        return {_convert(k): _convert(v)
                for k, v in zip(node.keys, node.values)}
    if isinstance(node, _ast.UnaryOp):
        if isinstance(node.op, _ast.USub):
            return -_convert(node.operand)
        if isinstance(node.op, _ast.UAdd):
            return +_convert(node.operand)
    if isinstance(node, _ast.Attribute) and node.attr[:1] != '_':
        return getattr(_convert(node.value), node.attr)
    if isinstance(node, _ast.Call):
        kw = {kw.arg: _convert(kw.value) for kw in node.keywords}
        return _convert(node.func)(*map(_convert, node.args), **kw)
    if isinstance(node, _ast.Name) and node.id == "datetime":
        return datetime
    raise ValueError('malformed or disallowed expression')


def literal_eval(expression):
    node = compile(expression, '<unknown>', 'eval', _ast.PyCF_ONLY_AST)
    return _convert(node.body)


def format_params(params, hide=('passw', 'pwd')):
    secret = {key: ... for key in params if any(sub in key for sub in hide)}
    return [f'{key}={v!r}' if v != ... else f'{key}=*'
            for (key, v) in {**params, **secret}.items()]


def format_exception(exc_type, exc, tb, limit=None, chain=True,
                     _format_exception=traceback.format_exception, **kw):
    """Format a stack trace and the exception information.

    This wrapper is a replacement of ``traceback.format_exception``
    which formats the error and traceback received by API.
    If `chain` is True, then the original exception is printed too.
    """
    values = _format_exception(exc_type, exc, tb, limit=limit, **kw)
    server_error = None
    if issubclass(exc_type, Error):             # client-side
        values = [f"{exc}\n"]
    elif issubclass(exc_type, OSError):         # HTTPError (requests or urllib)
        values = [f"{exc_type.__name__}: {exc}\n"]
    elif issubclass(exc_type, ServerError):     # JSON-RPC or Web API
        server_error = exc.args[0]['data']
        if 'arguments' not in server_error and 'error' in server_error:
            server_error = server_error['error']['data']
        print_tb = not server_error.get('name', '').startswith(('odoo.', 'werkzeug.'))
    if server_error:
        # Format readable API errors
        try:
            message = str(server_error['arguments'][0])
        except Exception:
            message = str(server_error.get('arguments') or server_error.get('error'))
        fault = f"{server_error['name']}: {message}"
        tb = print_tb and not message.startswith('FATAL:') and server_error['debug']
        if chain:
            values = [tb or fault, _cause_message] + values
            values[-1] = fault
        else:
            values = [tb or fault]
    return values


def issearchdomain(arg):
    """Check if the argument is a search domain.

    Examples:
      - ``[('name', '=', 'mushroom'), ('state', '!=', 'draft')]``
      - ``['name = mushroom', 'state != draft']``
      - ``[]``
    """
    return isinstance(arg, list) and not (arg and (
        # Not a list of ids: [1, 2, 3]
        isinstance(arg[0], int) or
        # Not a list of ids as str: ['1', '2', '3']
        (isinstance(arg[0], str) and arg[0].isdigit())))


def searchargs(params, kwargs=None):
    """Compute the 'search' parameters."""
    if not params:
        return ([],)
    if not isinstance(domain := params[0], list):
        return params
    for (idx, term) in enumerate(domain):
        if isinstance(term, str) and term not in DOMAIN_OPERATORS:
            if not (m := _term_re.match(term.strip())):
                raise ValueError(f"Cannot parse term {term!r}")
            (field, operator, value) = m.groups()
            try:
                value = literal_eval(value)
            except Exception:
                pass  # Interpret the value as a string
            domain[idx] = (field, operator, value)
    params = (domain,) + params[1:]
    if kwargs and len(params) == 1:
        args = (kwargs.pop('offset', 0),
                kwargs.pop('limit', None),
                kwargs.pop('order', None))
        if any(args):
            params += args
    return params


class partial(functools.partial):
    __slots__ = ()

    def __repr__(self):
        # Hide arguments
        return f"{self.__class__.__name__}({self.func!r}, ...)"
