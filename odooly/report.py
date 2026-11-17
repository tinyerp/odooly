import json
from pathlib import Path
from urllib.parse import urlencode

from .exceptions import Error
from .helpers import secure_filename


def ask_filename(filename):
    # Ask filename, and do not overwrite existing file(s)
    default_fname = secure_filename(filename or "")
    fname = input(f'Enter filename [{default_fname}]: ') or default_fname
    fpath = Path.cwd() / fname
    fpath_stem, fpath_index = fpath.stem, 0
    while fpath.exists():
        fpath_index += 1
        fpath = fpath.with_stem(f"{fpath_stem}_({fpath_index})")
    # Create parent directories
    fpath.parent.mkdir(parents=True, exist_ok=True)
    return fpath


def render_pdf(report_name, records, data=None):
    """Render a PDF report for the record(s)."""
    env = records.env
    is_interactive = env.client._is_interactive()
    ir_actions_report = env._get('ir.actions.report', False)
    report = None
    if report_name:
        domain = [("model", "=", records._name), ("report_name", "like", report_name)]
        try:
            [report] = ir_actions_report.search(domain)
        except ValueError:
            pass
    if not report and is_interactive:
        domain = [
            ("model", "=", records._name),
            ("report_type", "in", ("qweb-html", "qweb-pdf")),
        ]
        limit = 20
        reports = ir_actions_report.search(domain)
        descriptions = reports[:limit].read("{name}    ({report_name} `{report_type}`)")
        print('Available reports:')
        for idx, desc in enumerate(descriptions, start=1):
            print(f' {idx}. {desc}')
        if len(reports) > limit:
            print(' ...')
        print()
        while reports:
            ans = input('Select a report: ')
            try:
                report = reports[int(ans) - 1]
                break
            except Exception:
                pass
    if not report:
        raise Error(f"Missing report: {report_name!r}" if report_name else "No report found")
    params = {"context": json.dumps(env.context)}
    if data:
        params["options"] = json.dumps(data)
    ids = "/" + ",".join(str(res_id) for res_id in records.ids) if records else ""
    if len(records) > 1:
        # Use standard method:
        result = env.client.report.pdf(f"{report.report_name}{ids}", data=params)
    else:
        # Use report_download in order to have a specific filename
        report_url = f"/report/pdf/{report.report_name}{ids}?{urlencode(params)}"
        result = env.client.report.download(data=json.dumps([report_url, 'qweb-pdf']))
    if not result.name:
        result.name = f"{report.name}.pdf"

    ans = input('Save? [Y/n] ') if is_interactive else 'n'
    if ans and ans[:1].lower() != 'y':
        return result
    fpath = ask_filename(result.name)
    fpath.write_bytes(result.getvalue())
    return fpath
