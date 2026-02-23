#!/usr/bin/env python
"""Execute SQL on the server, from API.

Leverage "ir.actions.server" and "ir.logging" in order to execute SQL commands on the server.

Example::

    >>> env.sql("SHOW server_version; SHOW timezone; SELECT pg_postmaster_start_time()::text;")
    {'queries': ['SHOW server_version',
                 'SHOW timezone',
                 'SELECT pg_postmaster_start_time()::text'],
     'result': [{'server_version': '16.11 (Ubuntu 16.11-0ubuntu0.24.04.1)'},
                {'TimeZone': 'GMT'},
                {'pg_postmaster_start_time': '2026-01-02 06:17:53.549373+00'}]}
"""
import collections
import datetime
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
DEFAULT_USER = "admin"
ACTION_CODE = """\
sql_queries = env.context.get("__sql") or []
result = env.cr.connection.notices

if not env.su:
    raise UserError("Not allowed")

for query in sql_queries:
    env.cr.execute(query)
    if not env.cr.description:
        result.append(env.cr.statusmessage)
    elif not env.cr.rowcount:
        result.append({c.name: () for c in env.cr.description})
    else:
        columns = [c.name for c in env.cr.description]
        result.extend(dict(zip(columns, values)) for values in env.cr.fetchall())

log(str({'queries': sql_queries, 'result': result}))
result[:] = []
"""


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


def get_action(env, xml_id):
    action = env['ir.actions.server'].get(xml_id)
    if not action:
        action = env['ir.actions.server'].create({
            'name': 'SQL Execute',
            'state': 'code',
            'model_id': env['ir.model'].get('base.model_base').id,
        }).ensure_one()
        action._set_external_id(xml_id)
    return action.with_context(lang=None)


def sql_execute(env, queries):
    qlist = []
    for query in queries.split(";"):
        query = query.strip()
        if query:
            qlist.append(query)

    if not qlist:
        return None

    sql_action = get_action(env, "__odooly__.sql")
    vals = {"name": f"SQL Execute - {datetime.datetime.now()}"}
    if sql_action.code != ACTION_CODE:
        vals["code"] = ACTION_CODE
    sql_action.write(vals)
    sql_action.sudo().with_context(__sql=qlist).run()

    logg = env['ir.logging'].get([f"func = {vals['name']}"])
    return eval(logg.message, {"datetime": datetime}) if logg else None


def main():
    description = "Connect to runbot.odoo.com, demo.odoo.com or any instance."
    parser = optparse.OptionParser(usage='%prog [options] ENV', description=description)
    parser.add_option('-u', '--user', default=DEFAULT_USER, help='\'demo\' or \'admin\'')
    parser.add_option('-v', '--verbose', default=0, action='count', help='verbose')
    parser.add_option('-c', '--config', default=None)
    parser.add_option('--api-key', dest='api_key', default=None, help='API Key')

    [opts, args] = parser.parse_args()
    [version] = args or ['demo']

    if opts.config:
        odooly.Client._config_file = odooly.Path.cwd() / opts.config
    _retrieve_servers(user=opts.user)
    global_vars = odooly.Client._set_interactive()
    global_vars['__doc__'] = __doc__

    if version.startswith('http'):
        print(f"Connect to {version} ...")
        odooly.Client(version, user=opts.user, api_key=opts.api_key, verbose=opts.verbose)
    else:
        print("Available Odoo builds: " + ", ".join(ODOO_SERVERS))
        try:
            while version not in ODOO_SERVERS:
                version = input("Choose one: ")
        except KeyboardInterrupt:
            raise SystemExit("")
        print(f"Connect to Odoo {version} ...")
        odooly.Client.from_config(version, user=opts.user, verbose=opts.verbose)

    odooly.Env.sql = sql_execute
    odooly._interact(global_vars)


if __name__ == "__main__":
    main()
