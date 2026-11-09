import functools
import pprint

from .colorize import color_comment, color_repr
from .exceptions import ServerError

__all__ = ["convert_to_width", "pp", "set_output_width", "Printer"]

MAXCOL = [79, 179, 9999]    # Line length in verbose mode
PP_FORMAT = {'sort_dicts': False, 'width': 120}


def pp(value):
    print(color_repr(pprint.pformat(value, **PP_FORMAT)))


def set_output_width(columns):
    PP_FORMAT['width'] = MAXCOL[1] = columns


def convert_to_width(verbosity):
    """Convert verbosity to output width

    - 0 --> None
    - 1 --> 79
    - 2 --> 179 (or terminal width)
    - 3 --> 9999
    - 8 --> 9999
    - 40 --> 40
    - 200 --> 200
    """
    if verbosity and verbosity < 9:
        width = MAXCOL[min(3, verbosity) - 1]
    else:
        width = verbosity
    if width:
        return max(36, width)


class Printer:
    width = None

    def _print_(self, message, _prefix):
        cols = self.width - len(_prefix) - 1
        suffix = f"... L={len(message)}" if len(message) > cols else ""
        xch = message[:cols - len(suffix)] + suffix
        print(color_comment(f"{_prefix} {xch}"))

    print_sent = functools.partialmethod(_print_, _prefix='  >')
    print_recv = functools.partialmethod(_print_, _prefix='<--')

    def __bool__(self):
        return bool(self.width)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            if issubclass(exc_type, ServerError):
                exc = exc.args[0]["data"]["name"]
            self.print_recv(f"{exc_type.__name__}: {exc}")
