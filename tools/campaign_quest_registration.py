"""Register an emitted source quest project in a native level.

Types and objective value types go to the destination project; the quest
definition and its instance go to the Level entry, because a quest declared
under a Project shows "Different region" in the journal.
"""
import copy
import xml.etree.ElementTree as ET

from campaign_quest_graph import identifier, xml

QUEST_TYPES = {'Side-Activity': 'Activity'}


def _section(owner, tag):
    found = owner.find(tag)
    return found if found is not None else ET.SubElement(owner, tag)


def _shape(node):
    return node.tag, sorted(node.attrib.items()), [_shape(child) for child in node]


def register(project_blob, entry_blob, emitted_project_blob, quest_blob, quest_path,
             *, model=None, souls=None, group=None, shared_types=False):
    """Return (project_blob, entry_blob, quest_blob, report).

    souls maps a soul GUID to the SoulAsset alias declared in the project.
    With a model, bind_markers then attaches journal markers to those assets.
    group is the source quest group; unknown groups are refused.
    shared_types lets a further quest of the same emitted project reuse a type
    the project already holds, when it is identical; a different one is refused.
    """
    project_root, entry_root = ET.fromstring(project_blob), ET.fromstring(entry_blob)
    emitted_root, quest_root = ET.fromstring(emitted_project_blob), ET.fromstring(quest_blob)
    project = project_root.find('./Skald/Project')
    level = entry_root.find('./Skald/Level')
    emitted = emitted_root.find('./Skald/Project')
    quest = quest_root.find('./Skald/Quest')
    if project is None or level is None or emitted is None or quest is None:
        raise ValueError('Expected a project, level entry, emitted project and quest definition')
    name = identifier(quest.get('Name'))
    if quest_path.startswith('/') or ':' in quest_path or '\\' in quest_path:
        raise ValueError('Quest definition path must be relative')
    if group is not None and group not in QUEST_TYPES:
        raise ValueError('Unsupported source quest group: ' + repr(group))

    definitions, nodes = _section(level, 'Definitions'), _section(level, 'Nodes')
    if any(n.get('Name') == name or n.tag == name for n in nodes):
        raise ValueError('Quest name already registered: ' + name)
    if any(d.get('File') == quest_path for d in definitions):
        raise ValueError('Quest file already registered: ' + quest_path)

    types = _section(project, 'Types')
    copied_types = []
    for node in emitted.findall('Types/Type'):
        held = [t for t in types if t.get('TypeName') == node.get('TypeName')]
        if held:
            if not shared_types or len(held) != 1 or _shape(held[0]) != _shape(node):
                raise ValueError('Quest type already registered: ' + str(node.get('TypeName')))
            continue
        types.append(copy.deepcopy(node))
        copied_types.append(node.get('TypeName'))
    log_types = _section(project, 'ObjectiveValueTypes')
    copied_logs = []
    for node in emitted.findall('ObjectiveValueTypes/ObjectiveValueType'):
        if not any(n.get('Type') == node.get('Type') for n in log_types):
            log_types.append(copy.deepcopy(node)); copied_logs.append(node.get('Type'))

    ET.SubElement(definitions, 'Definition', File=quest_path)
    ET.SubElement(nodes, name, Name=name)

    quest_type = QUEST_TYPES.get(group)
    if quest_type:
        if quest.get('Type') not in (None, quest_type):
            raise ValueError('Conflicting quest type: ' + quest.get('Type'))
        quest.set('Type', quest_type)

    assets = _section(project, 'Assets')
    declared = []
    for guid, alias in sorted((souls or {}).items()):
        identifier(alias)
        if any(a.get('SharedSoulGuids') == guid for a in assets.findall('SoulAsset')):
            continue
        if any(a.get('Name') == alias for a in assets):
            raise ValueError('Soul asset alias already used: ' + alias)
        ET.SubElement(assets, 'SoulAsset', Name=alias, SharedSoulGuids=guid)
        declared.append(alias)

    project_out, quest_out = xml(project_root), xml(quest_root)
    markers = None
    if model is not None:
        from campaign_quest_people import bind_markers
        project_out, quest_out, markers = bind_markers(project_out, quest_out, model, set(souls or {}))
    report = dict(quest=name, quest_path=quest_path, quest_type=quest_type, types=copied_types,
                  objective_value_types=copied_logs, soul_assets=declared, markers=markers)
    return project_out, xml(entry_root), quest_out, report
