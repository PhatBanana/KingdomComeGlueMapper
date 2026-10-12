"""Stage native KCD2 animals at original KCD1 wildlife sites; no auto-install."""
import argparse
import copy
import json
from pathlib import Path
import zipfile

from upgrade_map import read
from wildlife import SPECIES, LEVEL_FILES, convert_level
from region_travel_ground import Heightfield


def build(source, target, level, output, species, limit, terrain=None):
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(terrain or level.with_name('terrain.pak')) as z:
        height = Heightfield(read(z, 'terrain/terrain.dat'))
    with zipfile.ZipFile(level) as z:
        files = {n: read(z, n) for n in LEVEL_FILES}
        changed, receipt = convert_level(files, source, target, height, species, limit)
        with zipfile.ZipFile(output / 'level.pak', 'x', zipfile.ZIP_DEFLATED) as dst:
            for entry in z.infolist():
                dst.writestr(copy.copy(entry), changed[entry.filename] if entry.filename in changed else read(z, entry.filename))
        with zipfile.ZipFile(output / 'level.pak') as dst:
            assert dst.namelist() == z.namelist()
            for entry in z.infolist():
                if entry.filename not in changed:
                    assert (entry.CRC, entry.file_size) == (dst.getinfo(entry.filename).CRC, dst.getinfo(entry.filename).file_size)
    (output / 'report.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
    parser.add_argument('--target', type=Path, default=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
    parser.add_argument('--level', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--terrain', type=Path, help='Target terrain package when using a backed-up level')
    parser.add_argument('--species', choices=SPECIES)
    parser.add_argument('--limit', type=int, default=1, help='Zero stages every selected site; default is one pilot')
    args = parser.parse_args()
    if args.limit < 0: parser.error('Limit must be nonnegative')
    receipt = build(args.source, args.target, args.level, args.output, args.species, args.limit, args.terrain)
    print(f"Staged {len(receipt['sites'])} of {receipt['source_sites']} source wildlife sites")
