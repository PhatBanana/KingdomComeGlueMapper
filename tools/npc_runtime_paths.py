"""Read-only check of the level-local AI mount contract in an existing log.

Lua initialization success is not proof that the serialized AI LevelPath can
resolve navigation and scheduler data. Compare that path with the engine's
reported level mount, without changing the game or interpreting FPS as AI health.
"""
import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read


def normalized(path):
    return path.replace('\\', '/').strip('/').lower()


def audit(level_pak, log):
    with zipfile.ZipFile(level_pak) as archive:
        declared = E.fromstring(read(archive, 'whdata_0')).findtext('AI/LevelPath')
    if not declared:
        raise ValueError('Level is missing its serialized AI/LevelPath')
    declared = normalized(declared)
    level = declared.rsplit('/', 1)[-1]
    mounts = []
    for line in log.splitlines():
        match = re.search(r"Pak '([^']+)' is opened, root: '([^']+)'", line, re.I)
        if match and normalized(match[1]).endswith('/' + level + '/level.pak'):
            mounts.append(normalized(match[2]))
    if not mounts:
        return dict(level=level, declared_ai_path=declared, status='no_level_mount_in_log',
                    runtime_verified=False)
    mounted = mounts[-1]
    return dict(level=level, declared_ai_path=declared, mounted_path=mounted,
                status='matching_mount' if mounted == declared else 'ai_level_path_mismatch',
                runtime_verified=False,
                limitation='Mount agreement does not verify scheduler execution or walking.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--level-pak', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.level_pak, args.log.read_text(encoding='utf-8', errors='replace'))
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result['status'] == 'ai_level_path_mismatch' else 0)
