"""Stage selected static-world navigation without rebuilding the map or launching it."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import rewrite
from static_navigation_profiles import plan
from upgrade_map import digest, read


def build(source, target, mod, output, profiles):
    source, target, mod, output = map(Path, (source, target, mod, output))
    if output.exists():
        raise FileExistsError('Choose a fresh navigation staging directory')
    relative, changes, report = plan(mod, source, target, profiles)
    if not changes:
        return dict(report, already_current=True, installed=False)
    baseline = digest(mod/relative)
    rewrite(mod/relative, output/'package'/relative, changes)
    with zipfile.ZipFile(mod/relative) as before, zipfile.ZipFile(output/'package'/relative) as after:
        if after.testzip() is not None or before.namelist() != after.namelist():
            raise ValueError('Navigation archive failed CRC or membership validation')
        for name in before.namelist():
            if name not in changes and read(before, name) != read(after, name):
                raise ValueError('Unrelated navigation variant changed: ' + name)
    if digest(mod/relative) != baseline:
        raise ValueError('Installed navigation changed during staging')
    report.update(baseline={relative: baseline}, files={relative: digest(output/'package'/relative)},
                  replacements=list(changes), other_archive_entries_unchanged=True, installed=False)
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--profile', action='append', required=True, dest='profiles')
    report = build(**vars(parser.parse_args()))
    print(json.dumps(report, indent=2))
