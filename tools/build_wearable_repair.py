"""Reconvert selected source wearables and stage changes in their owning PAKs."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import zipfile
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables, StaticAssetAdapter
from world_item_clothing import ClothingAdapter
from build_horse_trader_test import rewrite, digest


def build(source, target, mod, output, identifiers):
    source, target, mod, output = map(Path,(source,target,mod,output))
    output.mkdir(exist_ok=False)
    cache=output/'cache'; cache.mkdir()
    files={}; reports=[]
    with ExitStack() as stack:
        reader=stack.enter_context(RetailSourceReader(source))
        assets=StaticAssetAdapter(stack,source.parent,'wearablerepair',cache)
        adapter=ClothingAdapter(SourceTables(source,reader),assets,target,stack)
        for identity in sorted(set(identifiers)):
            print('Converting wearable',identity,flush=True)
            _,converted,report=adapter.convert(identity,adapter.plan(identity),{})
            files.update(converted); reports.append(dict(item=identity,**report))
        changes={}
        for path in (mod/'Data').glob('*.pak'):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name in files:changes.setdefault(path,{})[name]=files[name]
        owned={n for entries in changes.values() for n in entries}
        records=[]
        for path,entries in changes.items():
            destination=output/path.name
            rewrite(path,destination,{n:p.read_bytes() if isinstance(p,Path) else p for n,p in entries.items()})
            records.append(dict(path=path.relative_to(mod).as_posix(),staged=str(destination),
                                baseline=digest(path),sha256=digest(destination)))
        destination=output/'gluemapper_wearable_surface.pak'
        if (mod/'Data'/destination.name).exists():
            # Preserve unrelated previously repaired assets in repeat builds.
            with zipfile.ZipFile(mod/'Data'/destination.name) as archive:
                extra={n:archive.read(n) for n in archive.namelist()}
        else:extra={}
        for name,payload in files.items():
            if name not in owned:extra[name]=payload.read_bytes() if isinstance(payload,Path) else payload
        if extra:
            # This may already have been rewritten as an owner above.
            if destination.exists():
                with zipfile.ZipFile(destination) as archive:extra.update({n:archive.read(n) for n in archive.namelist()})
                records=[r for r in records if r['path']!='Data/'+destination.name]
            with zipfile.ZipFile(destination,'w',zipfile.ZIP_STORED) as archive:
                for name,payload in sorted(extra.items()):archive.writestr(name,payload)
            existing=mod/'Data'/destination.name
            records.append(dict(path='Data/'+destination.name,staged=str(destination),
                                baseline=digest(existing) if existing.exists() else None,sha256=digest(destination)))
    (output/'install-plan.json').write_text(json.dumps(records,indent=2))
    (output/'report.json').write_text(json.dumps(reports,indent=2))
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','target','mod','output','plan'):parser.add_argument('--'+key,type=Path,required=True)
    args=vars(parser.parse_args());plan=json.loads(args.pop('plan').read_text())
    print(json.dumps(build(**args,identifiers=plan['plan']['dependencies']),indent=2))
