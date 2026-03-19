#!/usr/bin/env python
"""Connect to an Odoo server."""
# Colorize command-line output
import builtins
import keyword
import io
import os
import re
import token as T
import tokenize
import unicodedata

import odooly

BUILTINS = {name for name in dir(builtins) if name[:1] != '_'}
T_STRING = {getattr(T, tk) for tk in dir(T) if 'STRING' in tk}
T_MIDDLE = {getattr(T, tk) for tk in dir(T) if 'STRING_MIDDLE' in tk}
KEYWORDS = {*keyword.kwlist}
SOFTKEYW = {*getattr(keyword, 'softkwlist', ())}
J_SPECIAL = {'false', 'null', 'true'}
CONSTANTS = {'False', 'None', 'True'}
DEF_CLASS = {'def', 'class'}


class THEME:  # Default theme
    keyword = '\x1b[1;34m'
    builtin = '\x1b[36m'
    comment = '\x1b[31m'
    string = '\x1b[32m'
    number = '\x1b[33m'
    op = '\x1b[0m'  # No color
    definition = '\x1b[1m'
    reset = '\x1b[0m'


def gen_colors(value, theme, keywords=KEYWORDS):
    """Generate color tuples (start, end, color)."""
    sio = io.StringIO(value)
    line_offsets = [..., 0] + [sio.tell() for __ in sio]
    sio.seek(0)

    bracket_level = is_def_name = 0
    yield None, 0, theme.reset
    try:
        for token in tokenize.generate_tokens(sio.readline):
            if token.start == token.end:
                continue
            color, end_offset = None, 0
            if token.type in T_STRING:
                if token.type in T_MIDDLE and token.string[-1:] in '{}':
                    end_offset += 1
                color = theme.string
            elif token.type == T.COMMENT:
                color = theme.comment
            elif token.type == T.NUMBER:
                color = theme.number
            elif token.type == T.OP:
                if token.string in '([{':
                    bracket_level += 1
                elif token.string in ')]}':
                    bracket_level -= 1
                color = theme.op
            elif token.type == T.NAME:
                if token.string in keywords:
                    is_def_name = token.string in DEF_CLASS
                    color = theme.keyword
                elif keywords is not KEYWORDS:
                    continue
                elif is_def_name:
                    is_def_name = False
                    color = theme.definition
                elif token.string in SOFTKEYW and not bracket_level:
                    color = theme.keyword  # soft_keyword
                elif token.string in BUILTINS:
                    color = theme.builtin
            if color is not None:
                start = line_offsets[token.start[0]] + token.start[1]
                end = line_offsets[token.end[0]] + token.end[1] + end_offset
                yield start, end, color
    except (SyntaxError, tokenize.TokenError):
        pass
    yield None, None, theme.reset


def _apply_colors(value, theme, keywords):
    output = ''
    if value:
        __, end, c_reset = next(colors := gen_colors(value, theme=theme, keywords=keywords))

        while (last_pos := end) is not None:
            start, end, color = next(colors)
            if start is None:
                output += _escape(value[last_pos:])
            else:
                output += _escape(value[last_pos:start]) + color + _escape(value[start:end]) + c_reset
    return output


def _escape(value):
    if value.isascii():
        return value
    result = ''
    for char in value:
        if char > '\x7f' and unicodedata.category(char)[:1] == 'C':
            char = rf'\u{ord(char):04x}'
        result += char
    return result


def color_python(value):
    """Colorize Python syntax."""
    return _apply_colors(value, THEME(), KEYWORDS)


def color_repr(value):
    """Colorize string representation."""
    return _apply_colors(value, THEME(), CONSTANTS)


def color_json(value):
    """Colorize JSON representation."""
    return _apply_colors(value, THEME(), J_SPECIAL)


def patch_colors(module):
    """Set functions to color output."""
    global THEME
    try:  # Python >= 3.14
        from _pyrepl.utils import BUILTINS, THEME
        BUILTINS |= {'Client', 'client', 'env'}
    except ImportError:
        pass

    module.color_repr = color_repr
    if module.color_py is not str:  # Python >= 3.14
        return {'color_repr': color_repr}
    theme = THEME()
    module.color_py = color_python
    module.color_bold = f'{theme.definition}{{}}{theme.reset}'.format
    module.color_comment = f'{theme.comment}{{}}{theme.reset}'.format
    decolor = odooly.partial(re.compile(r'\x1b\[[;\d]+m').sub, '')
    return {'color_py': color_python, 'color_repr': color_repr, 'decolor': decolor}


def main():
    args = odooly.get_parser().parse_args()

    if args.config:
        odooly.Client._config_file = odooly.Path.cwd() / args.config
    if args.list_env:
        print('Available settings:  ' + ' '.join(odooly.read_config()))
        return

    global_vars = odooly.Client._set_interactive()
    if odooly.color_py is not str or (os.getenv('FORCE_COLOR') and not os.getenv('NO_COLOR')):
        global_vars.update(patch_colors(odooly))

    print(odooly.color_repr(odooly.USAGE))
    odooly.connect_client(args)
    odooly._interact(global_vars)


if __name__ == '__main__':
    main()
