"""Create an SDK-only mod view without changing the installed retail manifest."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import xml.etree.ElementTree as ET

from setup_campaign import game_version

MARKER = '.gluemapper-sdk-view.json'


def is_junction(path):
    """Detect directory junctions on every supported Python version (3.11+)."""
    try:
        return path.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    except (FileNotFoundError, AttributeError):
        return False


def junction(path, source):
    def quoted(value):
        return "'" + str(value).replace("'", "''") + "'"
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "
        + quoted(path) + ' -Target ' + quoted(source) + ' | Out-Null'],
        check=True, capture_output=True, text=True)


def prepare(sdk, source):
    """The local manifest permits an explicit compatibility test, not a release."""
    if os.name != 'nt':
        raise ValueError('The public Modding Tools require Windows.')
    sdk, source = Path(sdk).resolve(), Path(source).resolve()
    if not (sdk/'Bin/Win64ReleaseSteamLTO_DLL/KingdomCome.exe').is_file():
        raise ValueError('Choose the public Modding Tools installation.')
    if sdk == source.parent.parent:
        raise ValueError('SDK and retail mod must be separate installations.')
    version = game_version(sdk)
    manifest = ET.fromstring((source/'mod.manifest').read_bytes())
    mod_id = manifest.findtext('info/modid', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', mod_id):
        raise ValueError('Invalid mod ID in the source manifest.')
    if not (source/'Data').is_dir():
        raise ValueError('The source mod has no Data directory.')
    mods = sdk/'Mods'
    if mods.resolve() != mods:
        raise ValueError('SDK Mods must be a local directory, not a junction.')
    view = mods/mod_id
    owner = dict(source=str(source), sdk_version=version, compatibility_test_only=True)
    # Migrate an explicitly matching whole-mod junction by detaching only the
    # link. Never write mod.manifest through it into the retail installation.
    if is_junction(view) or view.is_symlink():
        if view.resolve() != source:
            raise ValueError('Existing SDK mod points to a different source.')
        view.rmdir() if is_junction(view) else view.unlink()
    elif view.exists():
        marker = view/MARKER
        if not marker.is_file() or json.loads(marker.read_text()).get('source') != str(source):
            raise ValueError('Refusing to overwrite an unowned SDK mod directory.')
        for child in view.iterdir():
            if child.name not in (MARKER, 'mod.manifest', 'Data', 'Localization'):
                raise ValueError(f'Unexpected file in SDK view: {child.name}')
        for name in ('Data', 'Localization'):
            link = view/name
            if (link.exists() or is_junction(link) or link.is_symlink()) and (not is_junction(link) or link.resolve() != source/name):
                raise ValueError(f'Unexpected SDK asset link: {link}')
    view.mkdir(parents=True, exist_ok=True)
    (view/MARKER).write_text(json.dumps(owner, indent=2), encoding='utf-8')
    for name in ('Data', 'Localization'):
        if (source/name).is_dir() and not (view/name).exists():
            junction(view/name, source/name)
    for supports in list(manifest.findall('supports')):
        manifest.remove(supports)
    ET.SubElement(ET.SubElement(manifest, 'supports'), 'version').text = version
    # Atomic replacement also breaks an accidental hardlink to a source file.
    temporary = view/'mod.manifest.tmp'
    temporary.write_bytes(ET.tostring(manifest, encoding='utf-8', xml_declaration=True))
    temporary.replace(view/'mod.manifest')
    return dict(view=str(view), **owner, runtime_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--source', required=True, help='Installed retail mod directory')
    print(json.dumps(prepare(**vars(parser.parse_args())), indent=2))
