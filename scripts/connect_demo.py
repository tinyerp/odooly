#!/usr/bin/env python
"""Connect to an Odoo server, either from runbot.odoo.com or demo.odoo.com.

These are the supported environments:
 - 'demo' - Spawn a demo server on https:/demo.odoo.com
            (Last stable version, with Enterprise add-ons)
 - 'test'/'test+e' - Connect to a Nightly build server on Runbot
 - 'saas'/'saas+e' - Connect to a Saas server on Runbot
 - '19.0'/'19.0+e' - Connect to newest '19.0' server on Runbot
 - etc...

Suffix '+e' means Enterprise. Otherwise, it is Community edition.
Each Runbot server proposes a database selector: with more or less modules installed

To connect to the same server in the browser, URL can be printed::

    >>> client
    <Client 'https://4567-saas-18-3.runbot109.odoo.com/web?db=4567-saas-18-3-base'>
    >>> client.server_version
    'saas~18.3+e'

"""
import argparse
from pathlib import Path

from odooly import __version__
from odooly._demo import _retrieve_servers, RUNBOT_HOST
from odooly.colorize import setup_colors
from odooly.run import InteractiveClient as Client, setup_signal_handler, _interact


def main():
    parser = argparse.ArgumentParser(description=f"Connect to {RUNBOT_HOST} or demo.odoo.com.")
    parser.add_argument('env', nargs='?', default='demo', metavar='ENV', help='environment')
    parser.add_argument('-u', '--user', default='demo', help='\'demo\' or \'admin\'')
    parser.add_argument('-d', '--db', default=None, help='database')
    parser.add_argument('-v', '--verbose', default=0, action='count', help='verbose')
    parser.add_argument('-c', '--config', default=None)
    parser.add_argument('--api-key', dest='api_key', default=None, help='API Key')

    args = parser.parse_args()
    version = args.env

    if args.config:
        Client._config_file = Path.cwd() / args.config

    Client._saved_config_demo = _retrieve_servers(user=args.user)
    all_envs = {*Client._saved_config_demo, *Client.read_config()}

    # Interactive mode
    Client.connect.__doc__ = __doc__
    Client._globals = {
        "__name__": "odooly",
        "__version__": __version__,
        "__doc__": __doc__,
        "Client": Client,
    }
    setup_colors(Client._globals)
    setup_signal_handler()

    if version.startswith('http'):
        print(f"Connect to {version} ...")
        Client(version, user=args.user, api_key=args.api_key, verbose=args.verbose)
    else:
        print("Available Odoo builds: " + ", ".join(Client._saved_config_demo))
        try:
            while version not in all_envs:
                version = input("Choose one: ")
        except (KeyboardInterrupt, EOFError):
            raise SystemExit("")
        print(f"Connect to Odoo {version} ...")
        Client.from_config(version, verbose=args.verbose)

    return _interact(Client._globals)


if __name__ == "__main__":
    main()
