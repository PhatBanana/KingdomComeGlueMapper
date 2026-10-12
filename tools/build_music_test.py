"""Stage original adaptive music and native area bindings without installing."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import rewrite, digest
from region_travel import guid
from upgrade_map import read
from world_music import resources


def build(source,target,level,output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    with zipfile.ZipFile(level) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml','triggerareas.fubar')}
    changes,music,report=resources(files,source,target,guid)
    output.mkdir(parents=True)
    rewrite(level,output/'level.pak',changes)
    with zipfile.ZipFile(output/'music.pak','w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for name,data in sorted(music.items()):z.writestr(name,data)
    with zipfile.ZipFile(level) as before,zipfile.ZipFile(output/'level.pak') as after:
        old={i.filename:(i.CRC,i.file_size) for i in before.infolist() if i.filename not in changes}
        new={i.filename:(i.CRC,i.file_size) for i in after.infolist() if i.filename not in changes}
        if old!=new:raise ValueError('Unrelated level entries changed')
    report.update(baseline_sha256=digest(level),level_sha256=digest(output/'level.pak'),
                  music_sha256=digest(output/'music.pak'),preserved_level_entries=len(old))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'areas','recordings','bindings'}},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','level','output'):parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
