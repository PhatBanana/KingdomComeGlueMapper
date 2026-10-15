"""Stage a native menu entry for an already installed converted opening.

Does not install, replace save files, or rebuild world assets. The existing
native intro_new_game movie override must already be installed in this test build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from retail_menu import menu_assets
from upgrade_map import read


def resolve_level(blob, level):
    rows = [r for r in ET.fromstring(blob).iter('LevelData') if r.get('LevelName') == level]
    if len(rows) != 1:
        raise ValueError('Expected one destination level registration')
    value = int(rows[0].get('LevelId'))
    if value < 1:
        raise ValueError('Invalid destination level ID')
    return value


def stage(game, package, output, level):
    game, package, output = map(Path, (game, package, output))
    if output.exists():
        raise ValueError('Output exists; preserve the previous stage')
    with zipfile.ZipFile(package / 'Data/kingdomcomegluemapper.pak') as z:
        level_id = resolve_level(read(z, 'Libs/Tables/level__kingdomcomegluemapper.xml'), level)
    if not (package / 'Data/Levels' / level / 'level.pak').is_file():
        raise ValueError('Destination world is not installed')
    with zipfile.ZipFile(game / 'Data/IPL_GameData.pak') as z:
        assets, source = menu_assets(z, read)
    runtime = Path(__file__).resolve().parents[1] / 'runtime/campaign_menu.lua'
    lua = ('KingdomComeGlueMapper = KingdomComeGlueMapper or {}\n'
           'KingdomComeGlueMapper.startProbe = true\n'
           f'KingdomComeGlueMapper.campaignLevelId = {level_id}\n'
           'KingdomComeGlueMapper.campaignMenuLabel = "New Game Debug Sasau region"\n'
           'KingdomComeGlueMapper.campaignDescription = "Start the converted KCD1 opening. Campaign conversion is in progress."\n'
           + runtime.read_text(encoding='utf-8'))
    # The native loader selects the manifest's modid, not arbitrary Lua files.
    assets['Scripts/Mods/kingdomcomegluemapper.lua'] = lua.encode()
    output.mkdir(parents=True)
    pak = output / 'gluemapper_campaign_menu.pak'
    with zipfile.ZipFile(pak, 'x', zipfile.ZIP_STORED) as z:
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    report = dict(level=level, level_id=level_id, source=source,
                  sha256=hashlib.sha256(pak.read_bytes()).hexdigest(),
                  runtime_verified=False,
                  prerequisite='Accepted opening scene and intro_new_game movie package already installed')
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game', type=Path, required=True)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--level', required=True)
    a = p.parse_args()
    print(json.dumps(stage(a.game, a.package, a.output, a.level), indent=2))
