"""Fresh/resumed package upgrade for native fence/wall vaulting ledges."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from ledges import PREFIX, LEVEL_FILES, convert
from upgrade_map import read

VERSION=1
RECORD='world-ledges.json'


def digest(data):return hashlib.sha256(data).hexdigest()


def owned_state(files):
    """Fingerprint only the ledge manager and its LedgeObjects; other world edits may coexist."""
    mission=E.fromstring(files['objects_mission0.xml'])
    owned=[e for e in mission.iter('Entity') if e.get('Name','').startswith(PREFIX)]
    ids={e.get('EntityId') for e in owned}
    if len(ids)!=len(owned) or any(e.get('EntityClass')!='LedgeObject' for e in owned):raise ValueError('Duplicate/changed ledge entity')
    manager=E.fromstring(files['whdata_1']).find('LedgeManager')
    if manager is None:raise ValueError('Missing converted ledge manager')
    if any(l.findtext('entityId') not in ids|{'0'} for l in manager.iter('Ledge')):raise ValueError('Dangling ledge entity reference')
    from gambler_dialogue_registration import semantic_xml
    return dict(entities=digest(b''.join(repr(semantic_xml(e)).encode() for e in owned)),
                manager=digest(repr(semantic_xml(manager)).encode()))


def validate(package,report):
    if report.get('version')!=VERSION:raise ValueError('Unsupported ledge upgrade receipt')
    with zipfile.ZipFile(Path(package)/report['level_pak']) as z:files={n:read(z,n) for n in LEVEL_FILES}
    if owned_state(files)!=report['owned_state']:raise ValueError('Changed owned native ledge world data')
    return report


def upgrade(package,source,target):
    from setup_campaign import RECEIPT,digest as file_digest
    from setup_package_upgrade import rewrite
    from region_travel import guid
    package=Path(package)
    if (package/RECORD).exists():
        return {},validate(package,json.loads((package/RECORD).read_text(encoding='utf-8')))
    if source is None or target is None:raise ValueError('Both source games are required for native ledges')
    source,target=map(Path,(source,target));receipt=json.loads((package/RECEIPT).read_text(encoding='utf-8'))
    source_level=receipt['campaign_level'].removeprefix('kcd1_');level=receipt['travel_bridge']['destination']
    if not all(re.fullmatch('[A-Za-z0-9_]+',s) for s in (source_level,level)):raise ValueError('Invalid ledge level identity')
    lp='Data/Levels/'+level+'/level.pak'
    with zipfile.ZipFile(package/lp) as z:files={n:read(z,n) for n in LEVEL_FILES if n in z.namelist()}
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as src, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        updated,report=convert(files,src,native,guid)
    report.update(version=VERSION,status='native_ledges',level_pak=lp,source_level=source_level,owned_state=owned_state(updated))
    rewrite(package,lp,{n:updated[n] for n in LEVEL_FILES})
    validate(package,report)
    pending=package/(RECORD+'.pending');pending.write_text(json.dumps(report,indent=2),encoding='utf-8');pending.replace(package/RECORD)
    return {p:file_digest(package/p) for p in (lp,RECORD)},report
