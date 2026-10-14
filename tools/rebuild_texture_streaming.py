"""Stage validated DDS repairs and generated-texture streaming for a mod.

Input archives are read-only. No game process or installed archive is modified.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import zipfile
from campaign_package import write_asset_shards
from texture_streaming import layout, validate_family, repair_family, split_generated, native_split, family_signature, SPLIT
from upgrade_map import read


def build(data, output, compiler=None, source_data=None):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    report={'repaired':[], 'streamed':[], 'unresolved':[], 'validated':0}
    with ExitStack() as stack:
        source_index={};source_families=defaultdict(dict)
        if source_data:
            paths=sorted(Path(source_data).glob('*.pak'),key=lambda p:('_HD' in p.name,p.name.lower()))
            paths.extend(sorted((Path(source_data)/'patch').glob('*.pak')))
            for path in paths:
                z=stack.enter_context(zipfile.ZipFile(path))
                for entry in z.infolist():
                    n=entry.filename.replace('\\','/').lower()
                    m=re.fullmatch(r'(.+\.dds)(\.(?:a|\d+a?))?',n)
                    if m:source_index[n]=(z,entry);source_families[m[1]][m[2] or '']=n
        index={};families=defaultdict(dict)
        for path in sorted(Path(data).glob('*.pak')):
            z=stack.enter_context(zipfile.ZipFile(path))
            for entry in z.infolist():
                name=entry.filename.replace('\\','/').lower()
                m=re.fullmatch(r'(.+\.dds)(\.(?:a|\d+a?))?',name)
                if m:index[name]=(z,entry);families[m[1]][m[2] or '']=name
        def load(name):
            z,e=index[name];return read(z,e.filename)
        bases={};hashes=defaultdict(list)
        for name,parts in families.items():
            if '' not in parts:continue
            z,e=index[name]
            # Small headers/tails are sufficient for finding identical donors.
            if e.file_size<65536:
                b=load(name);bases[name]=b
                try:signature=family_signature(b)
                except ValueError:continue
                hashes[hashlib.sha256(signature).hexdigest()].append(name)
        emitted={}
        for name,parts in sorted(families.items()):
            if '' not in parts:
                report['unresolved'].append({'name':name,'error':'missing base'});continue
            if name.startswith(('libs/ui/','textures/cubemaps/')):continue
            base=bases[name] if name in bases else load(name)
            try:
                info=layout(base)
            except ValueError as e:
                report['unresolved'].append({'name':name,'error':str(e)});continue
            # Do not load all external pixel data merely to check its byte count.
            members={k:range(index[v][1].file_size) for k,v in parts.items() if k and k!='.a'}
            if '.a' in parts:members['.a']=load(parts['.a'])
            try:validate_family(base,members)
            except ValueError as error:
                actual={k:load(v) for k,v in parts.items() if k}
                donors=[]
                for candidate in hashes.get(hashlib.sha256(family_signature(base)).hexdigest(),[]):
                    if candidate!=name:
                        donors.append((bases[candidate],{k:load(v) for k,v in families[candidate].items() if k}))
                try:
                    additions=repair_family(base,actual,donors)
                    emitted.update({name+k:v for k,v in additions.items()})
                    report['repaired'].append({'name':name,'members':sorted(additions)})
                except ValueError:
                    try:
                        basename=re.sub(r'^t\d+_','',Path(name).name)
                        candidates=[n for n in source_families if Path(n).name==basename]
                        if len(candidates)!=1:raise ValueError('No unique patched source family')
                        original=candidates[0];replacement={}
                        provenance={}
                        for suffix,n in source_families[original].items():
                            z,e=source_index[n];replacement[suffix]=read(z,e.filename);provenance[suffix]=str(z.filename)
                        if family_signature(replacement[''])!=family_signature(base):
                            raise ValueError('Patched source identity does not match imported header/tail')
                        validate_family(replacement[''],{k:v for k,v in replacement.items() if k})
                        emitted.update({name+k:v for k,v in replacement.items()})
                        report['repaired'].append({'name':name,'source':original,'members':sorted(replacement),
                                                  'method':'complete_patched_source_family','provenance':provenance})
                    except ValueError as failure:
                        report['unresolved'].append({'name':name,'error':str(error),'repair_error':str(failure)})
                continue
            report['validated']+=1
            if len(base)>1024*1024 and not info['flags'] & SPLIT:
                converted=native_split(base,compiler) if compiler else split_generated(base)
                emitted.update({name+k:v for k,v in converted.items()})
                report['streamed'].append({'name':name,'before':len(base),'resident':len(converted['']),'parts':len(converted)-1})
        packages,_=write_asset_shards(output,sorted(emitted.items()))
        report['packages']=packages
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rc',type=Path)
    p.add_argument('--source-data',type=Path)
    a=p.parse_args();r=build(a.data,a.output,a.rc,a.source_data)
    print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in r.items()}))
