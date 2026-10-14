"""Final generic spatial conversion stage for the private setup workspace."""
import argparse
import shutil
from game_paths import GameLibrary
from rebuild_spatial_hlod import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=GameLibrary, required=True)
    parser.add_argument('--level', default='setup_world')
    parser.add_argument('--source-level', default='rataje')
    args = parser.parse_args()
    for name in (args.level, args.source_level):
        if not name.replace('_', '').isalnum():
            raise ValueError('Invalid level name')
    root = args.library / 'KCD2Mod'
    level = root / 'Data/Levels' / args.level
    stage = root / 'spatial-streaming'
    result = build(args.library, level, stage,
                   args.library / 'KingdomComeDeliverance2/Data/Levels/trosecko',
                   source_level=args.source_level)
    # Conversion workspace only; installation uses the setup transaction later.
    for index, name in enumerate(result['asset_archives']):
        shutil.copyfile(stage / 'packages' / name,
                        root / 'Data' / f'gluemapper_spatial_{index:03d}.pak')
    for name in ('level.pak', 'terrain.pak'):
        shutil.copyfile(stage / 'packages' / name, level / name)


if __name__ == '__main__':
    main()
