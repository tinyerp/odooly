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
import collections
import optparse
import re

import odooly
import requests

RUNBOT_HOST = "runbot.odoo.com"
RUNBOT_URL = f"https://{RUNBOT_HOST}/runbot/submit?update_triggers=1&trigger_1=on&trigger_122=on"
RUNBOT_REGEX = (
    # (<Community or Enterprise>, <URL without http>, <build number>, <Odoo version>)
    r"<span>(\w+) Run</span>.*?"
    r"href=.https?:(//(\d+)-([^.]+).runbot\d+.odoo.com/web)/database/selector."
)
ODOO_SERVERS = {"demo": "https://demo.odoo.com/"}
DEFAULT_USER = "demo"


def _retrieve_servers(url=RUNBOT_URL, regex=RUNBOT_REGEX, user=DEFAULT_USER):
    test_servers = collections.defaultdict(set)
    overview = requests.get(url)
    builds = re.findall(regex, overview.text, re.DOTALL)
    for edition, odoo_url, build, ver in builds:
        suffix = "+e" if edition == "Enterprise" else ""
        if "saas" in ver:
            test_servers[f"saas{suffix}"].add((int(build), f"https:{odoo_url}"))
        elif "master" in ver:
            test_servers[f"test{suffix}"].add((int(build), f"https:{odoo_url}"))
        ver = ver.replace("saas-", "").replace("-", ".") + suffix
        # Get the newest for each Odoo version
        if ver not in ODOO_SERVERS:
            ODOO_SERVERS[ver] = f"https:{odoo_url}"
    # For test servers, get the oldest
    for ver in test_servers:
        ODOO_SERVERS[ver] = min(test_servers[ver])[1]
    # Inject into Odooly known configs
    odooly.Client._saved_config.update(
        {name: (server, None, user, user, None)
         for name, server in ODOO_SERVERS.items()}
    )
    print(f"Found {len(set(builds))} builds on {RUNBOT_HOST}")


def main():
    description = "Connect to runbot.odoo.com or demo.odoo.com."
    parser = optparse.OptionParser(usage='%prog [options] ENV', description=description)
    parser.add_option('-u', '--user', default=DEFAULT_USER, help='\'demo\' or \'admin\'')
    parser.add_option('-v', '--verbose', default=0, action='count', help='verbose')

    [opts, args] = parser.parse_args()
    [version] = args or ['demo']

    _retrieve_servers(user=opts.user)

    print("Available Odoo builds: " + ", ".join(ODOO_SERVERS))
    try:
        while version not in ODOO_SERVERS:
            version = input("Choose one: ")
    except KeyboardInterrupt:
        raise SystemExit("")

    print(f"Connect to Odoo {version} ...")
    global_vars = odooly.Client._set_interactive({'__doc__': __doc__})
    odooly.Client.from_config(version, user=opts.user, verbose=opts.verbose)
    odooly._interact(global_vars)


if __name__ == "__main__":
    main()
