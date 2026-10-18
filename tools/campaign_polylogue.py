"""Lower source multi-NPC conversations to KCD2's SpeakTrigger/ForcedDialog ABI."""
import copy
import posixpath
import re
import xml.etree.ElementTree as ET
from campaign_quest_graph import xml

MODULE = 'Quests/Final/Barbora/utils/speech/SpeakTrigger.xml'
TRIGGER = 'Quests/Final/Barbora/utils/speech/SpeakTrigger/speaktrigger.xml'


def adapt(files, container_path, dialogue_path, participants, templates):
    """Participants are resolved source soul2role memberships, including silent roles.

    No actor, quest, topic, item or position is selected by this adapter.
    The source entry predicate and once-only history gate are retained by the
    native technical interaction. The original dialogue retains all effects.
    """
    if len(set(participants)) < 2: return files, False
    root = ET.fromstring(files[dialogue_path]); dialog = root.find('Skald')[0]
    if dialog.tag != 'FaderDialog': return files, False
    parent = ET.fromstring(files[container_path]); host = parent.find('Skald')[0]
    name = dialog.get('Name'); stem = name + '_source_participants'
    if host.find("Nodes/*[@Name='"+stem+"']") is not None: return files, False
    entry = dialog.find('./Dialogue/Decision/Sequences')
    if entry is None or len(entry) != 1:
        raise ValueError('Multi-participant entry requires a single source entry sequence')
    source_entry = entry[0]; condition = source_entry.get('EntryCondition', 'true')
    history = re.findall(r"SequenceUsed\('([^']+)'\)", condition)
    if any(n != source_entry.get('Name') for n in history):
        raise ValueError('Cross-sequence entry history requires an explicit history adapter')
    module_root, trigger_root = (ET.fromstring(templates[k]) for k in (MODULE, TRIGGER))
    module, trigger = module_root.find('Skald')[0], trigger_root.find('Skald')[0]
    module.set('Name', stem); trigger.set('Name', stem+'_interaction')
    # Namespace the native utility so different source conditions cannot collide.
    module.find('Definitions/Definition').set('File', stem+'/interaction.xml')
    instance = module.find("Nodes/speaktrigger")
    instance.tag = trigger.get('Name')
    seq = trigger.find('./Dialogue/Decision/Sequences/Sequence')
    seq.set('Name', source_entry.get('Name'))
    seq.set('Visibility', 'Internal')
    seq.set('EntryCondition', "Port('IsActive') AND ("+condition+")")
    for port in dialog.findall("Ports/Port[@Direction='In'][@Type='bool']"):
        pname = port.get('Name')
        if pname in ('IsActive', 'isactive', 'speakers'): raise ValueError('Native interaction port collision')
        module.find('Ports').append(copy.deepcopy(port)); trigger.find('Ports').append(copy.deepcopy(port))
        ET.SubElement(instance, 'Edge', From=pname, To=pname)
    # Keep the native module's runtime speaker-membership check and Talk action.
    nodes = host.find('Nodes'); original = nodes.find("*[@Name='"+name+"']")
    if original is None: raise ValueError('Missing dialogue instance')
    assets = host.find('Assets')
    if assets is None: assets = ET.SubElement(host, 'Assets')
    ET.SubElement(assets, 'SoulAsset', Name=stem, SharedSoulGuids=' '.join(sorted(set(participants))))
    utility = ET.SubElement(nodes, stem, Name=stem)
    ET.SubElement(utility, 'Asset', Name='speakers', Alias=stem)
    for edge in original.findall('Edge'):
        if edge.get('To') in {p.get('Name') for p in dialog.findall("Ports/Port[@Direction='In'][@Type='bool']")}:
            utility.append(copy.deepcopy(edge))
    active = original.find("Edge[@To='active']")
    if active is None: raise ValueError('Missing source activation binding')
    ET.SubElement(utility, 'Edge', From=active.get('From'), To='isactive')
    params = ET.SubElement(nodes, 'Function', Name=stem+'_params',
        MethodName='wh::dialogmodule::CreateDialogParams', DeclaringType='wh::dialogmodule')
    ET.SubElement(params, 'Asset', Name='Participants', Alias=stem)
    ET.SubElement(original, 'Edge', From=stem+'.onspoke', To='EnqueueDialogue')
    ET.SubElement(original, 'Edge', From=stem+'_params.DialogParams', To='DialogParams')
    dialog.tag = 'ForcedDialog'
    settings = dialog.find('Dialogue'); settings.set('Initiator', 'NonPlayer')
    settings.set('AllowGreeting', 'false'); settings.attrib.pop('Priority', None)
    directory = posixpath.dirname(container_path)
    relative = stem+'.xml'
    ET.SubElement(host.find('Definitions'), 'Definition', File=relative)
    out = dict(files)
    out[container_path], out[dialogue_path] = xml(parent), xml(root)
    out[posixpath.join(directory, relative)] = xml(module_root)
    out[posixpath.join(directory, stem, 'interaction.xml')] = xml(trigger_root)
    return out, True
