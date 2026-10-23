"""Map imported source item identities to their authored inventory artwork."""
import io
import re
import zipfile
import xml.etree.ElementTree as E
from pathlib import Path
from PIL import Image
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from item_icon_atlas import atlas_index, texture
from upgrade_map import read, xml

ARCHIVE = 'Data/gluemapper_item_icons.pak'
ITEM_TABLE = re.compile(r'libs/tables/item/item(?:__[^/]+)?\.xml', re.I)


def resolve(row, players, names):
    """Use exact source IDs, converter identities or names plus source UI keys."""
    identity = row.get('Id','').lower()
    if identity in players: return players[identity].get('icon_id')
    match = re.search(r'_item_([0-9a-f_]{36})$',row.get('Name','').lower())
    if match and match[1].replace('_','-') in players:
        return players[match[1].replace('_','-')].get('icon_id')
    # Character garments have namespaced IDs; require both authoring name and
    # localization identity instead of guessing from armor category or color.
    name, ui = row.get('Name','').lower(), row.get('UIName','').lower()
    matches = {players[i].get('icon_id') for i,n in names.items() if i in players
               and n and name.endswith('_'+n.lower())
               and players[i].get('ui_name')
               and (ui == players[i]['ui_name'].lower() or ui.endswith('_'+players[i]['ui_name'].lower()))}
    if len(matches)>1: raise ValueError('Ambiguous source item icon: '+name)
    return next(iter(matches), None)


def convert(files, players, names, index, image_loader):
    changes, textures, report = {}, {}, []
    for path, blob in files.items():
        root = E.fromstring(blob); changed=False
        for row in root.findall('ItemClasses/*'):
            icon = resolve(row,players,names)
            if not icon or icon=='0': continue
            if icon not in index: raise ValueError('Missing source inventory icon '+icon+' for '+row.get('Name',''))
            target = 'gm_kcd1_item_'+icon
            texture_path = 'Libs/UI/Textures/Icons/Items/'+target+'_icon.dds'
            if texture_path not in textures:
                atlas, rect = index[icon]
                textures[texture_path] = texture(image_loader(atlas),rect) if atlas else texture(Image.new('RGBA',(64,64)),(0,0,64,64))
            if row.get('IconId') != target:
                report.append(dict(item=row.get('Id'),source_icon=icon,previous=row.get('IconId'),icon=target))
                row.set('IconId',target); changed=True
        if changed: changes[path]=xml(root)
    return changes,textures,report


def upgrade(package, source):
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    package=Path(package)
    archives={}
    for pak in sorted((package/'Data').glob('*.pak')):
        if pak.name==Path(ARCHIVE).name: continue
        with zipfile.ZipFile(pak) as z:
            files={n:read(z,n) for n in z.namelist() if ITEM_TABLE.fullmatch(n)}
        if files: archives[pak]=files
    if not archives: return {},{}
    source=Path(source)
    with RetailSourceReader(source) as reader:
        tables=SourceTables(source,reader)
        players={r['item_id']:r for r in tables.get('item/player_item')['rows']}
        names={r['item_id']:r['item_name'] for r in tables.get('item/item')['rows']}
    plans=[];textures={};report=[];images={}
    with zipfile.ZipFile(source/'Data/GameData.pak') as original:
        index=atlas_index(read(original,'Libs/UI/ico_items.gfx'))
        def image(path):
            if path not in images:
                images[path]=Image.open(io.BytesIO(read(original,path))).convert('RGBA')
            return images[path]
        for pak,files in archives.items():
            changes,assets,rows=convert(files,players,names,index,image)
            textures.update(assets);report.extend(rows)
            if changes: plans.append((pak.relative_to(package).as_posix(),changes))
    # Resolve every referenced icon before changing any table archive.
    changed={}
    if textures:
        destination=package/ARCHIVE
        same=False
        if destination.exists():
            with zipfile.ZipFile(destination) as z:
                same=set(z.namelist())==set(textures) and all(read(z,n)==b for n,b in textures.items())
        if not same:
            pending=destination.with_suffix('.upgrade-pending')
            with zipfile.ZipFile(pending,'x',zipfile.ZIP_DEFLATED) as z:
                for name,data in sorted(textures.items()): z.writestr(name,data)
            with zipfile.ZipFile(pending) as z:
                if z.testzip() is not None: raise ValueError('Invalid item icon archive')
            pending.replace(destination)
        changed[ARCHIVE]=digest(destination)
    for relative,changes in plans:
        # Training records own exact imported item bytes. Only advance those
        # hashes for the icon edits this stage has just resolved, after checking
        # the old bytes; never bless unrelated changes to equipment tables.
        import hashlib, json
        record=package/'quest-training.json'
        training=json.loads(record.read_text(encoding='utf-8')) if record.exists() else None
        owned=training.get('resources',{}).get(relative,{}) if training else {}
        updates={name:hashlib.sha256(blob).hexdigest() for name,blob in changes.items() if name in owned}
        if updates:
            with zipfile.ZipFile(package/relative) as original:
                for name in updates:
                    if hashlib.sha256(read(original,name)).hexdigest()!=owned[name]:
                        raise ValueError('Training item changed before icon conversion: '+name)
        rewrite(package,relative,changes);changed[relative]=digest(package/relative)
        if updates:
            owned.update(updates)
            pending=record.with_suffix('.json.pending');pending.write_text(json.dumps(training,indent=2),encoding='utf-8');pending.replace(record)
            changed['quest-training.json']=digest(record)
    return changed,dict(version=1,icons=len(textures),changed_items=report,runtime_verified=False)
