"""Stage smithing supplies in the existing test chest without changing the forge."""
import argparse
import json
from pathlib import Path
import zipfile
from build_horse_trader_test import digest, rewrite
from smithing_supplies import supplies, extend_preset
from upgrade_map import read

PRESET='Libs/Tables/item/InventoryPreset__kingdomcomegluemapper.xml'


def build(game,mod,output):
    if output.exists():raise FileExistsError(output)
    travel='Data/gluemappertravel.pak'
    with zipfile.ZipFile(game/'Data/Tables.pak') as tables:items=supplies(tables)
    with zipfile.ZipFile(mod/travel) as z:preset=extend_preset(read(z,PRESET),items)
    updates={travel:{PRESET:preset}}
    report=dict(items=items,baseline={},packages={},installed=False)
    for relative,replacements in updates.items():
        report['baseline'][relative]=digest(mod/relative)
        dest=output/'package'/relative;rewrite(mod/relative,dest,replacements)
        with zipfile.ZipFile(mod/relative) as a,zipfile.ZipFile(dest) as b:
            assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in replacements}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in replacements}
            for n,v in replacements.items():assert read(b,n)==v
        report['packages'][relative]=digest(dest)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(items=items,installed=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('game','mod','output'):p.add_argument('--'+key,type=Path,required=True)
    build(**vars(p.parse_args()))
