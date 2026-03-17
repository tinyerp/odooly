#!/usr/bin/env python
"""Connect to an Odoo server."""
# Colorize command-line output for Python <= 3.13
import builtins
import keyword
import io
import os
import pathlib
import re
import token as T
import tokenize
import unicodedata

import odooly

BUILTINS = {str(name) for name in dir(builtins) if name[:1] != '_'}
T_STRING = {getattr(T, tk) for tk in dir(T) if 'STRING' in tk}
T_MIDDLE = {getattr(T, tk) for tk in dir(T) if 'STRING_MIDDLE' in tk}

issoftkeyword = getattr(keyword, 'issoftkeyword', lambda t: False)


class THEME:  # Default theme
    keyword = '\x1b[1;34m'
    builtin = '\x1b[36m'
    comment = '\x1b[31m'
    string = '\x1b[32m'
    number = '\x1b[33m'
    op = '\x1b[0m'  # No color
    definition = '\x1b[1m'
    reset = '\x1b[0m'


def gen_colors(value, theme=THEME()):
    """Generate color tuples (start, end, color, reset_color)."""
    sio = io.StringIO(value)
    line_lengths = [0] + [len(line) for line in sio.readlines()]
    for i in range(1, len(line_lengths)):
        line_lengths[i] += line_lengths[i-1]

    sio.seek(0)
    bracket_level = is_def_name = 0
    try:
        for token in tokenize.generate_tokens(sio.readline):
            if token.start == token.end:
                continue
            color, end_offset = None, -1
            if token.type in T_STRING:
                if token.type in T_MIDDLE and token.string.endswith(('{', '}')):
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
                if is_def_name:
                    is_def_name = False
                    color = theme.definition
                elif keyword.iskeyword(token.string):
                    if token.string in ('def', 'class'):
                        is_def_name = True
                    color = theme.keyword
                elif issoftkeyword(token.string) and not bracket_level:
                    color = theme.keyword  # soft_keyword
                elif token.string in BUILTINS:
                    color = theme.builtin
            if color is not None:
                start = line_lengths[token.start[0] - 1] + token.start[1]
                end = line_lengths[token.end[0] - 1] + token.end[1] + end_offset
                yield start, end, color, theme.reset
    except (SyntaxError, tokenize.TokenError):
        pass
    yield None, None, None, None


def colorize(value):
    """Colorize Python syntax."""
    output = ''
    if value:
        start, end, color, c_reset = next(colors := gen_colors(value))

        for idx, char in enumerate(value):
            if start == idx:
                output += color

            if char > '\x7f' and unicodedata.category(char)[:1] == 'C':
                char = rf'\u{ord(char):04x}'
            output += char

            if end == idx:
                output += c_reset
                start, end, color, c_reset = next(colors)
    return output


def patch_colors(module):
    """Set functions to color output."""
    module.colorize = colorize
    module.color_bold = f'{THEME.definition}{{}}{THEME.reset}'.format
    module.color_comment = f'{THEME.comment}{{}}{THEME.reset}'.format
    decolor = odooly.partial(re.compile(r'\x1b\[[;\d]+m').sub, '')
    return {'colorize': colorize, 'decolor': decolor}


def main():
    args = odooly.get_parser().parse_args()

    if args.config:
        odooly.Client._config_file = odooly.Path.cwd() / args.config
    if args.list_env:
        print('Available settings:  ' + ' '.join(odooly.read_config()))
        return

    global_vars = odooly.Client._set_interactive()
    if os.getenv('FORCE_COLOR') and not os.getenv('NO_COLOR') and odooly.colorize is str:
        global_vars.update(patch_colors(odooly))  # Python <= 3.13

    print(odooly.colorize(odooly.USAGE))
    odooly.connect_client(args)
    odooly._interact(global_vars)


if __name__ == '__main__':
    main()
