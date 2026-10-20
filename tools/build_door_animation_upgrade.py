"""Stage a bounded door-registration repair; never write the installed mod."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile

from build_horse_trader_test import rewrite
from door_animation_upgrade import plan
from upgrade_map import digest, read


def build(mod, output):
    mod, output = Path(mod), Path(output)
    if output.exists():
        raise FileExistsError('Choose a fresh staging directory')
    changes, report = plan(mod)
    if not changes:
        return dict(report, already_current=True)
    baseline = {n: digest(mod/n) for n in changes}
    package = output/'package'
    package.mkdir(parents=True)
    shutil.copyfile(mod/'mod.manifest', package/'mod.manifest')
    for relative, replacements in changes.items():
        rewrite(mod/relative, package/relative, replacements)
        with zipfile.ZipFile(mod/relative) as before, zipfile.ZipFile(package/relative) as after:
            if after.testzip() is not None:
                raise ValueError('Door repair archive failed CRC validation')
            expected = set(before.namelist()) | set(replacements)
            if set(after.namelist()) != expected:
                raise ValueError('Door repair changed archive membership')
            for name in before.namelist():
                if name not in replacements and read(before,name) != read(after,name):
                    raise ValueError('Unrelated archive resource changed: ' + name)
        if digest(mod/relative) != baseline[relative]:
            raise ValueError('Installed baseline changed while staging')
    # A mount-only repair reads the unchanged original level for this check.
    from door_animation_upgrade import refresh
    from seating_animations import ANIMATIONS, HELPERS
    lp='Data/Levels/kcd1_travel/level.pak'
    level_path=package/lp if (package/lp).exists() else mod/lp
    with zipfile.ZipFile(level_path) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml',HELPERS,ANIMATIONS)}
    if refresh(files)[0] != files:
        raise ValueError('Door repair is not idempotent')
    report.update(baseline=baseline,files={n:digest(package/n) for n in changes},
                  replacements={n:list(v) for n,v in changes.items()},
                  other_archive_entries_unchanged=True,installed=False)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    report=build(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))
