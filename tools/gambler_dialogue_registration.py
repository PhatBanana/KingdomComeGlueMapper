"""Stage the native dice dialogue lifecycle without importing campaign/debug jobs.

All changes are returned in memory so setup can validate before committing either
archive. Native voice namespaces and the project-scoped fader holder are retained.
"""
import copy
import hashlib
import tempfile
import posixpath
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml
from world_gameplay_basis import package_dependencies, validate_dependency_scopes
from campaign_entity_links import append_links, native_guid

HOST = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
MINIH = 'Quests/GlueTravel/smithing_voice/minihry.xml'
NATIVE = 'Quests/Final/Barbora/open_world/minihry/kostky.xml'
ROOT = 'Quests/GlueTravel/smithing_voice/dice_dialogue/world/open_world.xml'
ALIAS = 'ch_dicePreMinigame'
SCENE = 'dice_preMinigameFader'


def one(items, label):
    items = list(items)
    if len(items) != 1: raise ValueError('Expected one ' + label)
    return items[0]


def semantic_xml(node):
    """Ignore formatting only; enum ordering, values and structure are contracts."""
    def content(value):
        return value if value and value.strip() else ''
    return (node.tag, tuple(sorted(node.attrib.items())), content(node.text),
            tuple((semantic_xml(child), content(child.tail)) for child in node))


def adapted_root(payload):
    root = E.fromstring(payload)
    module = root.find('Skald/Gameplay')
    port = one(module.findall('Ports/Port'), 'native dice campaign port')
    if port.attrib != dict(Name='m03', Direction='In', Type='wh::questmodule::QuestProgress'):
        raise ValueError('Changed dice campaign port contract')
    nodes = module.find('Nodes')
    gate = one(nodes.findall("IfFunction[@Name='SockyDone']"), 'campaign codex gate')
    reward = one(nodes.findall("AddReward[@Name='codexHry']"), 'campaign codex reward')
    if gate.find("Edge[@From='m03'][@To='ValueA']") is None or reward.find("Edge[@From='SockyDone.True']") is None:
        raise ValueError('Changed dice codex dependency')
    removed = {'SockyDone', 'codexHry', 'debug'}
    for n in list(nodes):
        if n.get('Name') in removed: nodes.remove(n)
    module.find('Ports').remove(port)
    definitions = module.find('Definitions')
    definitions.remove(one((d for d in definitions if d.get('File') == 'kostky/debug.xml'), 'debug definition'))
    # Refuse future native dependencies on the excluded branches.
    for edge in module.iter('Edge'):
        if edge.get('From', '').split('.')[0] in removed | {'m03'}:
            raise ValueError('Native dice branch depends on excluded campaign/debug data')
    return xml(root)


def closure(scripts):
    """Use the established namespace-aware packager with a private native view."""
    names = {n.lower(): n for n in scripts.namelist()}
    selected = {n for n in names if n.startswith('quests/final/barbora/open_world/minihry/kostky/')
                or n.startswith('quests/final/barbora/utils/')}
    selected.add(NATIVE.lower())
    hashes = {}
    entry = 'Quests/GlueTravel/smithing_voice/dice_dialogue/registration.xml'
    root = E.fromstring(adapted_root(read(scripts, names[NATIVE.lower()])))
    # Dependencies resolve relative to the native root before relocation.
    stub = E.Element('Database'); module = E.SubElement(E.SubElement(stub, 'Skald'), 'Module', Name='registration')
    E.SubElement(E.SubElement(module, 'Definitions'), 'Definition', File=posixpath.relpath(NATIVE, posixpath.dirname(entry)))
    E.SubElement(E.SubElement(module, 'Nodes'), 'kostky', Name='kostky')
    with tempfile.TemporaryDirectory(prefix='gm-dice-native-') as temp:
        archive = Path(temp)/'native.pak'
        with zipfile.ZipFile(archive, 'w') as z:
            for n in sorted(selected):
                payload = read(scripts, names[n]); hashes[n] = hashlib.sha256(payload).hexdigest()
                z.writestr(names[n], adapted_root(payload) if n == NATIVE.lower() else payload)
        with zipfile.ZipFile(archive) as native:
            result = package_dependencies({entry: xml(stub), NATIVE: xml(root)}, entry, NATIVE, native)
    result.pop(entry)
    copied_names={posixpath.basename(p) for p in result}
    hashes={p:h for p,h in hashes.items() if p==NATIVE.lower() or
            hashlib.sha256(p.encode()).hexdigest()[:24]+'.xml' in copied_names}
    return result, hashes


def prepare(package, target, files):
    """Return (map files, travel replacements, report); never mutate the package."""
    package, target = Path(package), Path(target)
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as travel:
        project = E.fromstring(read(travel, HOST))
        minih = E.fromstring(read(travel, MINIH))
        outer = E.fromstring(read(travel,'Quests/GlueTravel/smithing_voice/open_world.xml'))
    one(project.findall("Skald/Project/Definitions/Definition[@File='smithing_voice/open_world.xml']"),'voice namespace registration')
    one(project.findall("Skald/Project/Nodes/open_world[@Name='open_world']"),'voice namespace instance')
    one(outer.findall("Skald/Gameplay[@Name='open_world'][@VoiceNamespace='true']/Definitions/Definition[@File='minihry.xml']"),'minigame namespace registration')
    one(outer.findall("Skald/Gameplay/Nodes/minihry[@Name='minihry']"),'minigame namespace instance')
    one(minih.findall("Skald/Gameplay[@Name='minihry'][@VoiceNamespace='true']"),'native minigame voice namespace')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as scripts:
        definitions, hashes = closure(scripts)
        native_project = E.fromstring(read(scripts, 'Quests/Final/Barbora.xml')).find('Skald/Project')
    host = project.find('Skald/Project')
    assets = host.find('Assets')
    for alias in ('player', 'player_any'):
        template = one(native_project.findall("Assets/SoulAsset[@Name='"+alias+"']"), 'native '+alias)
        existing = assets.findall("*[@Name='"+alias+"']")
        if existing:
            bound = one(existing, 'inherited '+alias)
            if bound.tag != 'SoulAsset' or bound.get('SharedSoulGuids') != template.get('SharedSoulGuids'):
                raise ValueError('Conflicting native player binding')
        else: assets.append(copy.deepcopy(template))
    template = one(native_project.findall("Assets/CutsceneHolderAsset[@Name='"+ALIAS+"']"), 'native dice holder asset')
    existing = assets.findall("*[@Name='"+ALIAS+"']")
    if existing:
        if one(existing, 'dice holder alias').tag != 'CutsceneHolderAsset': raise ValueError('Dice asset type conflict')
    else: assets.append(copy.deepcopy(template))
    used_types = {v for b in definitions.values() for e in E.fromstring(b).iter()
                  for k,v in e.attrib.items() if k in ('Type','TypeT')}
    types = host.find('Types')
    if types is None: types = E.SubElement(host, 'Types')
    for t in native_project.findall('Types/Type'):
        if t.get('TypeName') not in used_types: continue
        old = types.findall("Type[@TypeName='"+t.get('TypeName')+"']")
        if not old: types.append(copy.deepcopy(t))
        elif semantic_xml(one(old,'native type')) != semantic_xml(t):
            raise ValueError('Conflicting inherited native dice type: '+t.get('TypeName'))
    module = minih.find('Skald/Gameplay')
    expected = posixpath.relpath(ROOT, posixpath.dirname(MINIH))
    registrations = module.findall("Nodes/*[@Name='kostky']")
    if registrations:
        if one(registrations,'dice registration').tag != 'kostky': raise ValueError('Dice registration conflict')
        one(module.findall("Definitions/Definition[@File='"+expected+"']"),'dice definition')
    else:
        E.SubElement(module.find('Definitions'),'Definition',File=expected)
        E.SubElement(module.find('Nodes'),'kostky',Name='kostky')
    with zipfile.ZipFile(target/'Data/Tables.pak') as tables:
        cutscenes=E.fromstring(read(tables,'Libs/Tables/ui/cutscene.xml'))
        one(cutscenes.findall(".//FaderCutscene[@Name='"+SCENE+"']"),'native dice fader scene')
    mission = E.fromstring(files['objects_mission0.xml'])
    owner = one((e for e in mission if e.get('Name')==host.get('Name') and e.get('EntityClass')=='SmartObjectHolder'), 'project holder')
    name='gm_native_dice_fader'
    guid=native_guid(int.from_bytes(hashlib.sha256(name.encode()).digest()[:8],'little'))
    existing=[e for e in mission if e.get('EntityGuid')==guid or e.get('Name')==name]
    if existing:
        holder=one(existing,'owned dice fader')
        if holder.get('EntityGuid')!=guid or holder.get('EntityClass')!='CutsceneHolder' or holder.find("Properties[@esCutsceneName='"+SCENE+"']") is None:
            raise ValueError('Owned dice fader conflict')
    else:
        holder=E.SubElement(mission,'Entity',Name=name,EntityGuid=guid,EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1),EntityClass='CutsceneHolder',Pos=owner.get('Pos'))
        E.SubElement(holder,'Properties',esCutsceneName=SCENE)
    label="asset['"+ALIAS+"']"
    links=owner.find('EntityLinks')
    if links is None:links=E.SubElement(owner,'EntityLinks')
    old=links.findall("Link[@Name=\""+label+"\"]")
    if old:
        if one(old,'dice holder link').get('TargetGuid')!=guid:raise ValueError('Dice holder link conflict')
    else:E.SubElement(links,'Link',Name=label,TargetId=holder.get('EntityId'),TargetGuid=guid)
    output=dict(files)
    output['objects_mission0.xml']=xml(mission)
    output['waitinglinks.xml']=append_links(files['waitinglinks.xml'],[(owner.get('EntityGuid'),guid,label)])
    definitions[HOST],definitions[MINIH]=xml(project),xml(minih)
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as native:
        graph_count=validate_dependency_scopes(definitions, ROOT, read(native,'Libs/concept/definitions.xml'))
    def check_assets(path, inherited):
        module=E.fromstring(definitions[path]).find('Skald')[0]
        scope=inherited | {a.get('Name') for a in module.findall('Assets/*')}
        missing={a.get('Alias') for a in module.iter('Asset')} - scope
        if missing:raise ValueError(f'Unbound native dice assets in {path}: {sorted(missing)}')
        for d in module.findall('Definitions/Definition'):
            check_assets(posixpath.dirname(path)+'/'+d.get('File'),scope)
    check_assets(ROOT,{a.get('Name') for a in assets})
    return output,definitions,dict(native_dependencies=hashes,excluded_native_branches=['debug','m03 codex reward'],
        holder_guid=guid,scene=SCENE,validated_graphs=graph_count,voice_namespace='open_world/minihry',runtime_verified=False)
