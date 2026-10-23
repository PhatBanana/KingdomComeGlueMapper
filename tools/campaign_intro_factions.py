"""Lower a source introduction's protected faction to a native scoped effect.

The selected controller must set the same constant faction in its profile
initialization and its introductory worker. More complex replacement/clear
programs use FactionBridge; they must not be flattened into this scope adapter.
"""
import hashlib
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_intro_activity import normalized
from campaign_quest_start_placement import unique
from campaign_temporary_factions import FactionBridge, OPTION
from campaign_quest_graph import constant, edge
from upgrade_map import read

NATIVE = 'Quests/Final/Barbora/klaster/klaster_hibernate_mode/npc_modifikace.xml'
VERSION = 2


def source_contract(blob, plan):
    root = normalized(blob)
    worker = unique(root.findall("BehaviorTree[@name='"+plan['tree']+"']"), 'intro faction worker')
    controller = unique(root.findall("BehaviorTree[@name='onUpdate']"), 'intro faction controller')
    guard = unique((g for g in controller.iter('QuestCondition')
                    if g.get('quest') == plan['parent_quest'] and g.get('function') == 'IsQuestCompleted'),
                   'intro faction parent lifetime')
    profile = unique(guard.findall('Else/ProfileLoadedGate'), 'intro faction profile gate')
    if profile.get('NegateTo') != 'false' or profile.get('RunLogic') != 'Halt':
        raise ValueError('Unsupported intro faction profile lifetime')
    seq = unique(profile.findall('Sequence'), 'intro faction initialization')
    actor_set = unique(seq.findall('SetTemporarySuperfaction'), 'intro controller faction')
    actor_ref = actor_set.get('soul')
    binding = unique((n for n in seq.iter('LinkDataFilter') if n.get('Child') == actor_ref), 'intro faction actor binding')
    if binding.get('tag') != 'QuestActor' or binding.get('condition') != "$QuestActor == '"+plan['actor_role']+"'":
        raise ValueError('Intro faction targets a different source actor')
    first = unique(worker.findall('Root/OnInit/Sequence/IfCondition'), 'intro first initialization')
    match = re.fullmatch(r'\$(\w+) < (\d+)', first.get('condition',''))
    if not match or first.get('failOnCondition') != 'false':
        raise ValueError('Unsupported intro faction initialization guard')
    variable = unique(worker.findall("Variables/Variable[@name='"+match[1]+"']"), 'intro persistent phase')
    if variable.get('isPersistent') != '1':
        raise ValueError('Intro faction phase is not persistent')
    worker_set = unique(first.findall('Sequence/SetTemporarySuperfaction'), 'intro worker faction')
    faction = actor_set.get('superfaction','')
    if (worker_set.get('soul') not in ('this.id','$this.id') or worker_set.get('superfaction') != faction
            or not re.fullmatch(r'\w+', faction)):
        raise ValueError('Intro faction is dynamic or differs between controller and worker')
    context = unique(first.findall('Sequence/ExecuteLua'), 'intro combat clearing protection')
    protection = re.fullmatch(r"Contexts.SetPersistentOption\(entity, '"+OPTION+r"', '(\w+)'\)", context.get('code',''))
    if not protection:
        raise ValueError('Unsupported intro combat clearing protection')
    # Never silently discard a source clear, replacement or handle release.
    if len(list(root.iter('SetTemporarySuperfaction'))) != 2 or list(root.iter('ClearTemporarySuperfaction')):
        raise ValueError('Intro faction has additional writers; use the full faction bridge')
    contexts = [n for n in root.iter('ExecuteLua') if OPTION in n.get('code','')]
    if contexts != [context]:
        raise ValueError('Intro faction has additional context lifecycle operations')
    from campaign_intro_preparation import contract as prepare
    return dict(version=VERSION, source_faction=faction, actor_role=plan['actor_role'],
                preparation=prepare(seq, worker, actor_ref, plan),
                source_profile=profile.get('LayerName'), source_parent=plan['parent_quest'],
                protection_handle=protection[1], source_sha256=hashlib.sha256(blob).hexdigest(),
                lifetime='converted_parent_quest_active',
                release='native effect deactivation exposes current underlying faction',
                worker_completion_releases=False, runtime_verified=False)


def resolve(source, target, archive, plan, quest):
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from character_factions import PATH
    with RetailSourceReader(source) as reader:
        item = reader(source, {'controller':('Scripts.pak','Libs/AI/quests/'+quest+'.xml')})['controller']
        contract = source_contract(item['data'], plan)
        groups = SourceTables(source, reader).get('rpg/superfaction')['rows']
    with zipfile.ZipFile(target/'Data/Scripts.pak') as native:
        native_blob = read(native,NATIVE)
        if contract['preparation']:
            from campaign_intro_preparation import validate_native
            with zipfile.ZipFile(target/'Data/Tables.pak') as tables:
                validate_native(native, tables)
    # Reuse the general bridge's strict source-name -> registered-native-group
    # resolution. The scope adapter needs no asynchronous signals or own slot.
    tree = read(archive,PATH)
    bridge = FactionBridge('gm_intro_faction_contract', {}, groups, tree, native_blob)
    contract['native_faction'] = bridge.groups[contract['source_faction']]
    contract['native_contract'] = NATIVE
    contract['native_contract_sha256'] = hashlib.sha256(native_blob).hexdigest()
    return contract


def effect(stem, contract, actor_alias, scope):
    if contract.get('version') != VERSION or contract.get('lifetime') != 'converted_parent_quest_active':
        raise ValueError('Missing current introductory faction contract')
    node = E.Element('TemporaryFactionEffect', Name=stem+'_temporary_faction')
    E.SubElement(node,'Asset',Name='Souls',Alias=actor_alias)
    constant(node,'Faction',contract['native_faction'])
    edge(node,scope,'IsActive')
    return node


def attach(entry_root, stem, plan, *, validate=False):
    """One idempotent effect per imported introduction; never alter base souls."""
    nodes = entry_root.find('Skald/Level/Nodes')
    quest = unique((n for n in nodes if n.tag == plan['parent_quest']), 'faction parent quest')
    contract = plan.get('temporary_faction',{})
    expected = effect(stem,contract,stem+'_actor',quest.get('Name')+'.started')
    if contract.get('source_parent') != plan['parent_quest'] or contract.get('actor_role') != plan['actor_role']:
        raise ValueError('Introductory faction scope/actor differs from its source')
    found = nodes.findall("*[@Name='"+expected.get('Name')+"']")
    if found:
        actual = unique(found,'intro faction effect')
        def canonical(n):
            return n.tag,dict(n.attrib),[canonical(c) for c in n]
        if canonical(actual) != canonical(expected):
            raise ValueError('Introductory faction effect differs from its source contract')
        from campaign_intro_preparation import attach as prepare
        return prepare(entry_root, stem, plan, validate=validate)
    if validate:
        raise ValueError('Introductory temporary faction is not connected')
    nodes.append(expected)
    from campaign_intro_preparation import attach as prepare
    prepare(entry_root, stem, plan)
    return True
