import argparse
import atexit
import os
import shlex
import signal
import sys
from configparser import ConfigParser
from pathlib import Path

from . import __doc__, __version__
from .client import Client
from .environment import ADMIN_USER, DEMO_USER, Env
from .helpers import format_exception
from .colorize import color_bold, color_repr, install_colors
from .exceptions import Error
from .printer import Printer, convert_to_width, pp, set_output_width

CONF_FILE = 'odooly.ini'
HIST_FILE = '~/.odooly_history'

USAGE = """\
Usage (some commands):
    env[name]                       # Return a Model instance
    env[name].keys()                # List field names of the model
    env[name].fields(names=None)    # Return details for the fields
    env[name].field(name)           # Return details for the field
    env[name].browse(ids=())
    env[name].search(domain)
    env[name].search(domain, offset=0, limit=None, order=None)
                                    # Return a RecordList

    rec = env[name].get(domain)     # Get the Record matching domain
    rec.some_field                  # Return the value of this field
    rec.read(fields=None)           # Return values for the fields

    client.login(user)              # Login with another user
    client.connect(env_name)        # Connect to another env.
    client.connect(server=None)     # Connect to another server
    env.models(name)                # List models matching pattern
    env.modules(name)               # List modules matching pattern
    env.install(module1, module2, ...)
    env.upgrade(module1, module2, ...)
                                    # Install or upgrade the modules
    env.upgrade_cancel()            # Reset failed upgrade/install
"""


class InteractiveClient(Client):
    """Connection to an Odoo instance.  Interactive client."""
    _config_file = None
    _saved_config = {}
    _saved_config_demo = {}
    _globals = None

    def __init__(self, server, db=None, user=None, password=None, api_key=None, verbose=False):
        self._printer = Printer()
        self.verbose = verbose
        super().__init__(server, db=db, user=user, password=password, api_key=api_key)

    @property
    def verbose(self):
        return self._printer.width

    @verbose.setter
    def verbose(self, cols):
        self._printer.width = convert_to_width(cols)

    def save(self, environment=None, skip=False):
        """Save environment settings with this name, or current name"""
        self.env.name = environment or self.env.name or self.env.db_name
        if not skip and self.env.uid:
            config = (self._server, self.env.db_name, self.env.user.login, None, self.env._api_key)
            self._saved_config[self.env.name] = config
        if self._globals and self._globals.get('client', self) is self:
            self._set_prompt()
        return self

    @classmethod
    def get_config(cls, environment):
        """Retrieve the settings for this environment.

        It can be in memory, if it was saved before with :meth:`InteractiveClient.save`.
        If not, it will parse ``odooly.ini`` file, where it searches for the
        section ``[ <environment> ]``.

        See :meth:`InteractiveClient.read_config` for details of the configuration file format.
        """
        assert environment
        saved_config = {**cls._saved_config, **cls._saved_config_demo}
        if environment in saved_config:
            return saved_config[environment]
        try:
            cls._saved_config[environment] = cls.read_config(environment)
        except Exception:
            envs = [env for env in cls.read_config() if env not in saved_config]
            err_msg = "No such environment.\nAvailable: " + " ".join(envs)
            if saved_config:
                err_msg += "\n  " + " ".join(saved_config)
            raise Error(err_msg)
        return cls._saved_config[environment]

    @classmethod
    def from_config(cls, environment, *, user=None, database=None, verbose=False):
        """Create a connection to a defined environment.

        See :meth:`InteractiveClient.get_config`
        Return a connected :class:`InteractiveClient`.
        """
        (server, db, conf_user, password, api_key) = cls.get_config(environment)
        if skip_save := user and user != conf_user:
            password = None
        try:
            client = Env._cache[Env, db, server].client
            client.verbose = verbose
            client.login(user or conf_user, password=password, database=database, api_key=api_key)
        except KeyError:
            client = cls(server, database or db, user or conf_user,
                         password=password, api_key=api_key, verbose=verbose)
        return client.save(environment, skip=skip_save)

    @classmethod
    def read_config(cls, section=None):
        """Read the environment settings from the configuration file.

        Config file ``odooly.ini`` contains a `section` for each environment.
        Each section provides parameters for the connection: ``server``,
        ``username`` and (optional) ``database``, ``password`` and ``api_key``.
        As an alternative, server can be declared with 4 parameters:
        ``scheme / host / port / protocol``.
        Default values are read from the ``[DEFAULT]`` section.  If the ``password``
        is not set or is empty, it is requested on login.
        Return tuple ``(server, db or None, user, password or None, api_key or None)``.
        Without argument, it returns the list of configured environments.
        """
        if not cls._config_file or not cls._config_file.is_file():
            if section is None:
                return []
            raise FileNotFoundError(cls._config_file)
        with cls._config_file.open() as f:
            (p := ConfigParser()).read_file(f)
        if section is None:
            return p.sections()
        server = (env := dict(p.items(section))).get('server')
        if (scheme := env.get('scheme', 'http')) == 'local':
            server = shlex.split(server or env.get('options', ''))
        elif not server:
            protocol = env.get('protocol', 'web')
            server = f"{scheme}://{env['host']}:{env['port']}/{protocol}"
        return (
            server,
            env.get('database', ''),
            env['username'],
            env.get('password'),
            env.get('api_key'),
        )

    def _select_database(self, db_list, limit=20):
        database = super()._select_database(db_list)
        if database or not db_list or not self._is_interactive():
            return database
        print('Available databases:')
        for idx, name in enumerate(db_list[:limit], start=1):
            print(f' {idx}. {name!r}')
        if len(db_list) > limit:
            print(' ...')
        print()
        while db_list:
            ans = input('Select a database: ')
            try:
                return db_list[int(ans) - 1]
            except Exception:
                pass

    def login(self, user, password=None, database=None, api_key=None):
        """Switch `user` and (optionally) `database`."""
        if not self._is_interactive():
            return super().login(user, password=password, database=database, api_key=api_key)
        try:
            register = super().login(user, password=password, database=database, api_key=api_key)
        except Error as exc:
            print(exc)
            register = 'client' not in self._globals
        # Register the globals()
        register and self.connect()

    def connect(self, env_name=None, *, server=None, database=None, user=None):
        """Connect to another environment and replace the globals()."""
        assert self._is_interactive(), 'Not available'
        if env_name:
            self.from_config(env_name, user=user, database=database, verbose=self.verbose)
        elif server:
            if not user and self.env.uid:
                user = self.env.user.login
            self.__class__(server, db=database, user=user, verbose=self.verbose)
        else:
            assert not user, f"Use client.login({user!r}) instead"
            self._globals['client'] = self.env.client
            self._globals['env'] = env = self.env
            self._set_prompt()
            # Logged in?
            if env.uid:
                print(f"Logged in as '{color_bold(env.user.login)}' "
                      f"with {env._execute_kw._protocol_name}")

    def _set_prompt(self):
        # Tweak prompt
        sys.ps1 = f'{self.env.name or self.env.db_name} >>> '
        sys.ps2 = '... '.rjust(len(sys.ps1))

    @classmethod
    def _is_interactive(cls):
        return cls._globals is not None


def _interact(global_vars, use_pprint=True, usage=USAGE):
    import builtins

    if use_pyrepl := not os.getenv("PYTHON_BASIC_REPL"):
        try:
            from _pyrepl.main import CAN_USE_PYREPL as use_pyrepl
        except ImportError:
            use_pyrepl = False

    if use_pyrepl:  # Python >= 3.13
        from _pyrepl.console import InteractiveColoredConsole as Console
        from _pyrepl.simple_interact import run_multiline_interactive_console as run
        from _pyrepl import readline
    else:
        from code import InteractiveConsole as Console
        builtins.clear = type('', (), {'__repr__': lambda s: os.system('clear') or ''})()
        try:
            import readline
            import rlcompleter  # noqa
            readline.parse_and_bind('tab: complete')
        except ImportError:
            pass

    hist_file = Path(os.getenv("ODOOLY_HISTFILE", HIST_FILE)).expanduser()
    if hist_file:
        try:
            if hist_file.exists():
                readline.read_history_file(hist_file)
            if readline.get_history_length() < 0:
                readline.set_history_length(int(os.getenv('HISTSIZE', 500)))
            # better append instead of replace?
            atexit.register(readline.write_history_file, hist_file)
        except Exception:
            pass  # No history in case of error

    if use_pprint:
        def displayhook(value, _printer=pp, _builtins=builtins):
            # Pretty-format the output
            if value is not None:
                _printer(value)
                _builtins._ = value
        sys.displayhook = displayhook

    def excepthook(exc_type, exc, tb):
        # Print readable errors
        msg = ''.join(format_exception(exc_type, exc, tb, chain=False, **exfmt))
        print(color_repr(msg.rstrip()))
    sys.excepthook = excepthook

    builtins.usage = type('Usage', (), {'__call__': lambda s: print(usage),
                                        '__repr__': lambda s: usage})()

    console = Console(global_vars, filename="<stdin>")
    exfmt = {"colorize": console.can_colorize} if use_pyrepl else {}
    run(console) if use_pyrepl else console.interact('', '')


def get_parser():
    parser = argparse.ArgumentParser(description='Interact with Odoo')
    parser.add_argument('args', nargs='*', help='URL of the server')
    parser.add_argument(
        '-l', '--list', action='store_true', dest='list_env',
        help='list sections of the configuration')
    parser.add_argument(
        '--env',
        help='read connection settings from the given section')
    parser.add_argument(
        '-c', '--config', default=None, type=Path,
        help=f'specify alternate config file (default: {CONF_FILE})')
    parser.add_argument(
        '--server', default=None,
        help='full URL of the server')
    parser.add_argument('-d', '--db', default=None, help='database')
    parser.add_argument('-u', '--user', default=None, help='username')
    parser.add_argument(
        '-p', '--password', default=None, metavar='PASS',
        help='password, or it will be requested on login')
    parser.add_argument(
        '--api-key', dest='api_key', default=None,
        help='API Key for JSON-2 or JSON-RPC')
    parser.add_argument(
        '--demo', dest='demo', nargs='?', const="demo",
        help='connect to demo or runbot server (default: demo, demo.odoo.com)')
    parser.add_argument(
        '--test', dest='demo', nargs='?', const="test+e",
        help='connect to demo or runbot server (default: test+e, on master branch)')
    parser.add_argument(
        '-v', '--verbose', default=0, action='count',
        help='verbose')

    parser.add_argument('--version', action='version', version=__version__)
    return parser


def connect_client(args):
    # Argument 'args' is argparse Namespace with mandatory attributes:
    #   args, env, config, server, db, user, password, api_key, demo, verbose
    if (env_name := args.demo or args.env):
        kwargs = {
            "user": args.user,
            "database": args.db,
            "verbose": args.verbose,
        }
        client = InteractiveClient.from_config(env_name, **kwargs)
    else:
        if args.server:
            server = args.server
        elif not args.config:
            server = ' '.join(args.args)
        elif args.args:
            server = ['-c', args.config] + args.args
        else:
            server = ['-c', args.config]
        kwargs = {
            "password": args.password,
            "api_key": args.api_key,
            "verbose": args.verbose,
        }
        client = InteractiveClient(server, args.db, args.user or ADMIN_USER, **kwargs)
    return client


def handle_resize(signum, frame):
    term = os.get_terminal_size()
    if not term.columns:
        return
    client = InteractiveClient._globals.get('client')
    if client and client.verbose:
        client.verbose = term.columns
    set_output_width(term.columns)


def install_signal_handler():
    assert InteractiveClient._is_interactive()
    signal.signal(signal.SIGWINCH, handle_resize)
    signal.raise_signal(signal.SIGWINCH)


def main(interact=_interact):
    """Configure client, and decide if interactive.

    If it is not interactive, execute script received on standard input.
    """
    aparser = get_parser()
    args = aparser.parse_args()

    client_class = InteractiveClient
    client_class._config_file = Path.cwd() / (args.config or CONF_FILE)

    if args.demo:
        from ._demo import _retrieve_servers

        client_class._saved_config_demo = _retrieve_servers(user=args.user or DEMO_USER)
    if args.list_env:
        print('Available settings:  ' + ' '.join(client_class.read_config()))
        if args.demo:
            print(' ' + ' '.join(client_class._saved_config_demo))
        return
    if not (args.args or args.server or args.config or args.env or args.demo):
        aparser.error("missing argument")

    is_interactive_shell = sys.stdin.isatty()
    if not is_interactive_shell:  # Read and execute commands from standard input
        client = connect_client(args)
        exec(compile(sys.stdin.read(), '<stdin>', 'exec'), {'client': client, 'env': client.env})
        return

    # Interactive mode
    client_class._globals = {
        "__name__": "odooly",
        "__version__": __version__,
        "__doc__": __doc__,
        "Client": client_class,
    }
    if not interact:
        return connect_client(args)._globals
    usage = os.getenv('ODOOLY_USAGE', USAGE)
    install_colors(client_class._globals)
    install_signal_handler()
    print(color_repr(usage))
    return interact(connect_client(args)._globals, usage=usage)
