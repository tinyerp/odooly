"""Colorize command-line output"""
import keyword
import os
import re

__all__ = ["color_bold", "color_comment", "color_json", "color_python", "color_repr",
           "decolor", "install_colors", "THEME"]

KEYWORDS = {*keyword.kwlist}
J_SPECIAL = {'false', 'null', 'true'}
CONSTANTS = {'False', 'None', 'True'}
CSI = '\33['  # Control Sequence Introducer, same as ESC+[ or \x1b[
_decolor_re_sub = re.compile('(\233|\33\\[)[;0-9]*m').sub
_bold = _comment = str


class THEME:  # Default theme in Python 3.14+
    keyword = f'{CSI}1;34m'
    builtin = f'{CSI}36m'
    comment = f'{CSI}31m'
    string = f'{CSI}32m'
    number = f'{CSI}33m'
    op = ''  # No color
    definition = f'{CSI}1m'
    reset = f'{CSI}m'


def _apply_colors(text, theme, keywords):
    """Fallback, if NO_COLOR is set"""
    return str(text)


def _python(text):
    return _apply_colors(text, THEME(), KEYWORDS)


def color_python(text):
    """Colorize Python syntax."""
    return _python(text)


def color_repr(text):
    """Colorize string representation."""
    return _apply_colors(text, THEME(), CONSTANTS)


def color_json(text):
    """Colorize JSON representation."""
    return _apply_colors(text, THEME(), J_SPECIAL)


def color_bold(text):
    """Emphasize text."""
    return _bold(text)


def color_comment(text):
    """Colorize comments."""
    return _comment(text)


def decolor(text):
    """Remove coloring escape sequences."""
    return _decolor_re_sub('', text)


def _init_colors():
    global _apply_colors, _init_colors

    # Run once
    _init_colors = object

    import builtins
    import io
    import token as T
    import tokenize
    import unicodedata

    BUILTINS = {name for name in dir(builtins) if name[:1] != '_'}
    DEF_CLASS = {'def', 'class'}
    T_STRING = {getattr(T, tk) for tk in dir(T) if 'STRING' in tk}
    T_MIDDLE = {getattr(T, tk) for tk in dir(T) if 'STRING_MIDDLE' in tk}
    SOFTKEYW = {*getattr(keyword, 'softkwlist', ())}

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
        yield None, None, None

    def _apply_colors(text, theme, keywords):
        output = ''
        if text:
            __, end, c_reset = next(colors := gen_colors(text, theme=theme, keywords=keywords))

            while (last_pos := end) is not None:
                start, end, color = next(colors)
                output += _escape(text[last_pos:start])
                if color:
                    output += color + _escape(text[start:end]) + c_reset
                elif start is not None:
                    output += _escape(text[start:end])
        return output

    def _escape(text):
        if text.isascii():
            return text
        result = ''
        for char in text:
            if char > '\x7f' and unicodedata.category(char)[:1] == 'C':
                char = rf'\u{ord(char):04x}'
            result += char
        return result


def install_colors(global_vars):
    """Set functions to color output."""
    global THEME, _bold, _comment, _python

    if os.getenv('NO_COLOR'):
        return

    try:
        from _pyrepl import utils
        from _pyrepl.utils import disp_str, gen_colors, THEME
    except ImportError:
        if not os.getenv('FORCE_COLOR'):
            return
        utils = None

    # Initialize color_repr, color_python
    _init_colors()

    if utils:  # Python >= 3.14
        # Colorize Odooly globals as builtins
        utils.BUILTINS |= {'Client', 'client', 'env', 'clear'}

        def _python(text):
            # Apply configured theme instead of default theme
            return "".join(
                char for li in text.splitlines()
                for char in disp_str(li, colors=[*gen_colors(li)])[0] + ['\n']
            ).rstrip()
        _bold = _python('def _').split()[1].replace('_', '{}').format
        _comment = _python('#').replace('#', '{}').format
    else:  # Python <= 3.13
        theme = THEME()
        _bold = f'{theme.definition}{{}}{theme.reset}'.format
        _comment = f'{theme.comment}{{}}{theme.reset}'.format
    global_vars.update({'color_py': color_python, 'color_repr': color_repr, 'decolor': decolor})
