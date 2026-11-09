import os.path
import sys

# Support running without installing, from wheel file:
# python odooly-2.7.0-py3-none-any.whl/odooly --help

_dir = os.path.dirname(__file__)
_wheel_dir = os.path.dirname(_dir)

if _wheel_dir not in sys.path and _dir in sys.path:
    sys.path[sys.path.index(_dir)] = _wheel_dir

from odooly.run import main  # noqa


main()
