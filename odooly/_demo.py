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
import os
import re
from pathlib import Path

from .http import HTTPSession


RUNBOT_HOST = "runbot.odoo.com"
RUNBOT_URL = f"https://{RUNBOT_HOST}/"
RUNBOT_HEADERS = {"Cookie": "trigger_display_1=1-122"}
RUNBOT_REGEX = (
    # (<Community or Enterprise>, <domain>, <build number>, <Odoo version>)
    r"<span>([CE]\w+) Run</span>.{,200}<build-options-dropdown.{,400}"
    r" data-domain=.((\d+)-([^.]+).runbot\d+.odoo.com). "
)
ODOO_SERVERS = {"demo": "https://demo.odoo.com/"}


def _retrieve_servers(url=RUNBOT_URL, regex=RUNBOT_REGEX, user=None, headers=RUNBOT_HEADERS):
    test_servers = collections.defaultdict(set)
    overview = HTTPSession().request(url, method='GET', headers=headers)
    builds = re.findall(regex, overview, re.DOTALL)
    if not builds and os.getenv("ODOOLY_DEBUG"):
        fdump = Path.cwd() / "runbot_odoo_com.html"
        fdump.write_text(overview)
        raise SystemExit(f"Could not parse content of {RUNBOT_HOST}:\n  check here \"{fdump}\"")
    for edition, domain, build, ver in builds:
        suffix = "+e" if edition == "Enterprise" else ""
        odoo_url = f"https://{domain}/web"
        if "saas" in ver:
            test_servers[f"saas{suffix}"].add((int(build), odoo_url))
        elif "master" in ver:
            test_servers[f"test{suffix}"].add((int(build), odoo_url))
        ver = ver.replace("saas-", "").replace("-", ".") + suffix
        # Get the newest for each Odoo version
        if ver not in ODOO_SERVERS:
            ODOO_SERVERS[ver] = odoo_url
    # For test servers, get the oldest
    for ver in test_servers:
        ODOO_SERVERS[ver] = min(test_servers[ver])[1]
    print(f"Found {len({*builds})} builds on {RUNBOT_HOST}")
    return {name: (server, None, user, user, None) for name, server in ODOO_SERVERS.items()}
