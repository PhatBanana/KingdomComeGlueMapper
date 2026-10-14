"""Build facial dependencies for source recordings in an installed audio pack."""
import argparse
import json
from pathlib import Path
import zipfile

from dialogue_facials import FacialImporter, INDEX
from upgrade_map import read


def build(source, target, audio, output, existing=None):
    output.mkdir(parents=True,exist_ok=False)
    resources={}
    if existing:
        with zipfile.ZipFile(existing) as z: resources={n:read(z,n) for n in z.namelist()}
    importer=FacialImporter(source,target,resources.get(INDEX))
    try:
        with zipfile.ZipFile(audio) as z:
            candidates=[n for n in z.namelist() if n.lower().endswith('.ogg')]
        selected=[n for n in candidates if Path(n).stem.lower() in importer.source_headers]
        unmatched=sorted(set(candidates)-set(selected))
        if not selected:raise ValueError('No original recording identities found in audio pack')
        importer.add(selected);resources.update(importer.resources())
        report=importer.report();report['unmatched_recordings']=unmatched
        with zipfile.ZipFile(output/'gluemapper_dialogue_facials.pak','x',zipfile.ZIP_STORED) as z:
            for n,b in resources.items():z.writestr(n,b)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return dict(recordings=len(selected),unmatched=len(unmatched),databases=report['databases'])
    finally:importer.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','audio','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--existing',type=Path)
    a=p.parse_args();print(json.dumps(build(a.source,a.target,a.audio,a.output,a.existing)))
