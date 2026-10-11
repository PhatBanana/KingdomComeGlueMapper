"""Shared world-builder pickup conversion; no missing item is dropped."""
from contextlib import ExitStack
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from campaign_dependencies import DependencyImporter
from campaign_dependency_adapters import SourceTables, StaticAssetAdapter, ItemTextAdapter
from campaign_sources import RetailSourceReader
from world_item_inventory import collect
from world_item_definitions import native_items, WorldItemAdapter
from world_item_clothing import ClothingAdapter
from world_item_documents import DocumentImageAdapter
from world_item_placements import convert
from character_person import native_xml
from upgrade_map import read


def build(files, resources, source, target, output):
    source,target,output=map(Path,(source,target,output))
    if output.exists():raise FileExistsError('Choose a fresh pickup conversion directory')
    output.mkdir(parents=True);(output/'asset-cache').mkdir()
    with ExitStack() as stack:
        archive=stack.enter_context(zipfile.ZipFile(source/'Data/Levels/rataje/level.pak'))
        _,placements,audit=collect(archive)
        patches=[b for n,b in resources.items() if n.lower().startswith('libs/tables/item/item__') and n.endswith('.xml')]
        native=native_items(target,patches)
        with zipfile.ZipFile(target/'Data/Tables.pak') as z:
            classes=native_xml(read(z,'Libs/Tables/item/weapon_class.xml'))
        weapon_classes={n.get('id'):n.get('name') for n in classes[0]}
        reader=stack.enter_context(RetailSourceReader(source));tables=SourceTables(source,reader)
        assets=StaticAssetAdapter(stack,source.parent,'worlditems',output/'asset-cache')
        importer=DependencyImporter({'items':WorldItemAdapter(tables,'worlditems',native,weapon_classes),
            'clothing':ClothingAdapter(tables,assets,target,stack),
            'document_images':DocumentImageAdapter(source,reader,'worlditems'),
            'assets':assets,'strings':ItemTextAdapter(source,'worlditems','English')},
            registered={'items':{k:k for k in native}})
        for i,placement in enumerate(placements):
            importer.ensure('items',placement['item_id'],dict(source_id=placement['entity'].get('EntityId')))
            if i%500==0:print('Resolved pickup dependencies',i,'/',len(placements),flush=True)
        report=importer.report();report.update(placements=len(placements),inventory=audit)
        report['missing_items']=[r for r in report['jobs'] if r['group']=='items' and r['status']!='imported']
        report_path=output/'world-items-report.json'
        report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        if report['missing_items']:raise ValueError(str(len(report['missing_items']))+' pickup item definitions failed conversion')
        updated,world=convert(files,placements,importer.registered['items'])
        result=dict(resources);strings={};asset_files={}
        for name,data in importer.files.items():
            blob=data.read_bytes() if isinstance(data,Path) else data
            dest=output/'converted'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob)
            if name.startswith('Libs/Tables/'):
                if name in result:raise ValueError('Pickup resource collision: '+name)
                result[name]=blob
            elif name.lower().startswith('localization/english/'):
                strings.setdefault('text_ui_items.xml',ET.Element('Table')).extend(ET.fromstring(blob))
            else:asset_files[name]=dest
        report['world']=world;report['new_item_definitions']=sum(j['group']=='items' for j in report['jobs'])
        report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        return updated,result,{n:ET.tostring(r,encoding='utf-8') for n,r in strings.items()},asset_files,report


def pack_assets(path, assets):
    if sum(p.stat().st_size for p in assets.values())>1024**3-1024**2:
        raise ValueError('World item assets need another non-ZIP64 shard')
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'x',zipfile.ZIP_STORED,allowZip64=False) as z:
        for name,p in sorted(assets.items()):z.writestr(name,p.read_bytes())
