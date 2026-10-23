"""Repair inactive native lesson notifications in fresh and resumed builds."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from upgrade_map import read, xml


def guard_progress(scope):
    ports = {p.get('Name') for p in scope.findall('Ports/Port')}
    active = 'gm_active' if 'gm_active' in ports else 'active' if 'active' in ports else None
    if active is None: return 0
    nodes = scope.find('Nodes'); count = 0
    if nodes is None: return 0
    for n in list(nodes):
        typ = n.get('TypeT','')
        if n.tag != 'State' or typ in ('bool','int'): continue
        # Imported progress enums include ProgressFailable and the curriculum's
        # custom phase enumeration. Their explicit reset-to-None is the
        # lifecycle contract; boolean dialogue occupancy must remain live.
        if not (typ in ('Progress','ProgressFailable') or n.find("Edge[@To='SetNone']") is not None): continue
        for i,e in enumerate(n.findall('Edge')):
            to = e.get('To','')
            if not (to.startswith('Set') or to == 'Exec') or to == 'SetNone': continue
            origin = e.get('From',''); owner = origin.split('.')[0]
            existing = nodes.find("If[@Name='"+owner+"']")
            if existing is not None and existing.find("Edge[@From='"+active+"'][@To='Condition']") is not None: continue
            name = 'gm_progress_live_'+n.get('Name')+'_'+str(i)
            if nodes.find("*[@Name='"+name+"']") is not None: raise ValueError('Progress gate collision')
            gate = E.SubElement(nodes,'If',Name=name)
            E.SubElement(gate,'Edge',From=origin,To='Exec')
            E.SubElement(gate,'Edge',From=active,To='Condition')
            e.set('From',name+'.True'); count += 1
    return count


def upgrade(package, target):
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from setup_training_upgrade import validate, RECORD
    from setup_quest_invitation import validate as validate_invitation, RECORD as INVITATION
    package = Path(package)
    training = validate(package); invitation = validate_invitation(package)
    travel = 'Data/gluemappertravel.pak'; changes = {}; gates = 0; hidden = 0
    keys = set()
    with zipfile.ZipFile(package/travel) as z:
        for name in training['resources'][travel]:
            if not name.startswith('Quests/') or not name.endswith('.xml'): continue
            blob = read(z,name); root = E.fromstring(blob); scope = root.find('Skald/*')
            if scope is None: continue
            before = xml(root)
            # These are engine builtins, explicitly excluded from copied
            # Types. Older presentation builders nevertheless prefixed uses.
            for node in scope.iter():
                for attr in ('TypeT','ValueTypes'):
                    value=node.get(attr,'')
                    if value.endswith(('_presentation_Progress','_presentation_ProgressFailable')):
                        node.set(attr,value.rsplit('_',1)[1])
            gates += guard_progress(scope)
            # Controller-only imported quests have no source journal title or
            # objectives. Keep their internal state and outward logic ports.
            if scope.tag == 'Quest' and scope.find('QuestName') is None and scope.find('Objectives') is not None and not len(scope.find('Objectives')):
                for output in scope.findall('Nodes/Output'):
                    for e in list(output):
                        if e.tag == 'Edge' and e.get('To') == 'Progress': output.remove(e); hidden += 1
            types = {t.get('TypeName') for t in scope.findall('Types/Type')}
            for obj in scope.findall('Objectives/Objective'):
                typ = obj.get('TypeT'); matches = [t for t in types if t.endswith('_'+str(typ))]
                if typ not in types and len(matches)==1: obj.set('TypeT',matches[0])
                keys.update(n.get('StringName') for n in obj.iter() if n.get('StringName'))
            if xml(root)!=before: changes[name]=xml(root)
    # The mod replaces text_ui_quest.xml; carry over the exact native English
    # rows for the imported lesson, instead of displaying technical keys.
    localization = 'Localization/English_xml.pak'
    with zipfile.ZipFile(Path(target)/localization) as z: native=E.fromstring(read(z,'text_ui_quest.xml'))
    with zipfile.ZipFile(package/localization) as z: old=read(z,'text_ui_quest.xml')
    root=E.fromstring(old); table=next(n for n in root.iter() if n.tag.split('}')[-1]=='Table')
    def rows(doc):
        return {list(n)[0].text:n for n in doc.iter() if n.tag.split('}')[-1]=='Row' and len(n)}
    present=rows(root); originals=rows(native); added=0
    for key in sorted(keys):
        if key in present: continue
        if key not in originals: raise ValueError('Missing native objective localization: '+key)
        table.append(originals[key]); added+=1
    files={}
    if added:
        rewrite(package,localization,{'text_ui_quest.xml':xml(root)});files[localization]=digest(package/localization)
    if changes:
        rewrite(package,travel,changes);files[travel]=digest(package/travel)
        for name,blob in changes.items():
            value=hashlib.sha256(blob).hexdigest()
            training['resources'][travel][name]=value
            if name in invitation['resources']: invitation['resources'][name]=value
        for name,report in ((RECORD,training),(INVITATION,invitation)):
            pending=package/(name+'.pending');pending.write_text(json.dumps(report,indent=2),encoding='utf-8');pending.replace(package/name)
            files[name]=digest(package/name)
    validate(package);validate_invitation(package)
    return files,dict(version=1,guarded_transitions=gates,hidden_controllers=hidden,localized_objectives=added,runtime_verified=False)
