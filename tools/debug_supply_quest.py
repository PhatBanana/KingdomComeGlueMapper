"""Persistent, region-local forest cache objective using native stash events."""
import xml.etree.ElementTree as ET
from region_travel_visit import edge, ensure
from upgrade_map import xml, read

NAME = 'gm_debug_forest_supplies'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
PATH = 'Quests/GlueTravel/entry/debug_supplies.xml'


def attach(resources, items, scripts):
    resources = dict(resources)
    entry = ET.fromstring(resources[ENTRY])
    level = entry.find('Skald/Level')
    if level.find(f"Nodes/*[@Name='{NAME}']") is not None:
        raise ValueError('Debug supplies already registered')
    ET.SubElement(ensure(level, 'Definitions'), 'Definition', File='debug_supplies.xml')
    instance = ET.SubElement(level.find('Nodes'), NAME, Name=NAME)
    edge(instance, 'OnWake', 'arrive')
    edge(instance, 'OnLevelSwitched', 'arrive')
    edge(instance, 'gm_neuhof_horse_sales.getting_started_talked', 'talked_to_seller')
    dialog = level.find("Nodes/*[@Name='gm_neuhof_horse_sales']")
    if dialog is not None: edge(dialog, NAME+'.visit_seller_active', 'getting_started_active')
    assets = ensure(level, 'Assets')
    ET.SubElement(assets, 'StashAsset', Name='debug_supply_chest')
    ET.SubElement(assets, 'TriggerAreaAsset', Name='debug_supply_search')
    root = ET.Element('Database', Name='brambora')
    quest = ET.SubElement(ET.SubElement(root, 'Skald'), 'Quest', Name=NAME, Type='Side')
    ports = ET.SubElement(quest, 'Ports')
    ET.SubElement(ports, 'Port', Name='arrive', Direction='In', Type='trigger')
    ET.SubElement(ports, 'Port', Name='talked_to_seller', Direction='In', Type='trigger')
    ET.SubElement(ports, 'Port', Name='visit_seller_active', Direction='Out', Type='bool')
    definitions = ET.SubElement(quest, 'Definitions')
    for helper in ('HasItems_Stash', 'hasitems'):
        filename = 'debug_supplies/' + helper + '.xml'
        ET.SubElement(definitions, 'Definition', File=filename)
        resources['Quests/GlueTravel/entry/' + filename] = read(
            scripts, 'Quests/Final/Barbora/utils/item/' + helper + '.xml')
    nodes = ET.SubElement(quest, 'Nodes')
    progress = ET.SubElement(nodes, 'State', Name='progress', TypeT='wh::questmodule::QuestProgress')
    ET.SubElement(progress, 'Constant', Name='DefaultValue', Value='None')
    start = ET.SubElement(nodes, 'If', Name='start_once')
    edge(start, 'arrive', 'Exec'); edge(start, 'progress.None', 'Condition')
    edge(progress, 'start_once.True', 'SetActive')
    trigger = ET.SubElement(nodes, 'StashTrigger', Name='chest_events')
    ET.SubElement(trigger, 'Asset', Name='Stash', Alias='debug_supply_chest')
    edge(trigger, 'objective.Active', 'IsActive')
    # Every supplied type must be removed; opening or taking only the money
    # must not complete the objective. Chain binary native boolean operators.
    if not items: raise ValueError('Expected supplies')
    previous = None
    for i, item in enumerate(items):
        check = ET.SubElement(nodes, 'HasItems_Stash', Name='has_' + str(i), Namespace='')
        ET.SubElement(check, 'Asset', Name='stash', Alias='debug_supply_chest')
        ET.SubElement(check, 'Constant', Name='itemclass', Value=item['Id'])
        ET.SubElement(check, 'Constant', Name='amount', Value='1')
        current = 'has_' + str(i) + '.hasitems'
        if previous is not None:
            remaining = ET.SubElement(nodes, 'Function', Name='remaining_'+str(i),
                MethodName='math::boolean::Or', DeclaringType='math::boolean')
            edge(remaining, previous, 'A'); edge(remaining, current, 'B')
            current = 'remaining_'+str(i)+'.bool'
        previous = current
    empty = ET.SubElement(nodes, 'Function', Name='all_collected',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(empty, previous, 'Value')
    finished = ET.SubElement(nodes, 'If', Name='finish_after_looting')
    edge(finished, 'chest_events.OnClosed', 'Exec')
    edge(finished, 'all_collected.bool', 'Condition')
    output = ET.SubElement(nodes, 'Output', Name='Output')
    edge(output, 'progress.State', 'Progress')
    edge(output, 'visit_seller.Active', 'visit_seller_active')
    objective = ET.SubElement(nodes, 'State', Name='objective', TypeT='GMTravelVisitProgress')
    ET.SubElement(objective, 'Constant', Name='DefaultValue', Value='None')
    edge(objective, 'start_once.True', 'SetActive')
    edge(objective, 'finish_after_looting.True', 'SetDone')
    visit = ET.SubElement(nodes, 'State', Name='visit_seller', TypeT='GMTravelVisitProgress')
    ET.SubElement(visit, 'Constant', Name='DefaultValue', Value='None')
    edge(visit, 'finish_after_looting.True', 'SetActive')
    # Keep the original state names so an already emptied chest does not need
    # to refill or be looted again when upgrading the one-step test quest.
    old_done = ET.SubElement(nodes, 'If', Name='upgrade_old_completed_quest')
    edge(old_done, 'arrive', 'Exec'); edge(old_done, 'progress.Done', 'Condition')
    new_step = ET.SubElement(nodes, 'If', Name='upgrade_only_once')
    edge(new_step, 'upgrade_old_completed_quest.True', 'Exec')
    edge(new_step, 'visit_seller.None', 'Condition')
    edge(progress, 'upgrade_only_once.True', 'SetActive')
    edge(visit, 'upgrade_only_once.True', 'SetActive')
    talked = ET.SubElement(nodes, 'If', Name='seller_introduction')
    edge(talked, 'talked_to_seller', 'Exec'); edge(talked, 'visit_seller.Active', 'Condition')
    edge(visit, 'seller_introduction.True', 'SetDone')
    edge(progress, 'seller_introduction.True', 'SetDone')
    edge(ET.SubElement(nodes, 'find_supplies', Name='journal'), 'objective.State', 'Progress')
    edge(ET.SubElement(nodes, 'meet_zora', Name='seller_journal'), 'visit_seller.State', 'Progress')
    ET.SubElement(quest, 'QuestName', StringName=NAME+'_title', Text='Getting started')
    obj = ET.SubElement(ET.SubElement(quest, 'Objectives'), 'Objective', Name='find_supplies', TypeT='GMTravelVisitProgress')
    ET.SubElement(obj, 'LocalizedName', StringName=NAME+'_objective', Text='Find the forest chest and collect your supplies.')
    logs = ET.SubElement(obj, 'Logs')
    ET.SubElement(logs, 'EnumLog', Name='None', Type='None')
    active = ET.SubElement(logs, 'EnumLog', Name='Active', Type='Started', Marker='debug_supply_search')
    ET.SubElement(active, 'Log', StringName=NAME+'_active', Text='A wooden chest is hidden among the trees near the coachman\u2019s camp. Search the marked area and take the money, sword and clothing. These supplies are yours.')
    done = ET.SubElement(logs, 'EnumLog', Name='Done', Type='Completed')
    ET.SubElement(done, 'Log', StringName=NAME+'_done', Text='I recovered the supplies from the forest chest.')
    obj = ET.SubElement(quest.find('Objectives'), 'Objective', Name='meet_zora', TypeT='GMTravelVisitProgress')
    ET.SubElement(obj, 'LocalizedName', StringName=NAME+'_seller_objective', Text='Visit Zora, the horse seller at Neuhof.')
    logs = ET.SubElement(obj, 'Logs')
    ET.SubElement(logs, 'EnumLog', Name='None', Type='None')
    active = ET.SubElement(logs, 'EnumLog', Name='Active', Type='Started', Marker='horse_seller')
    ET.SubElement(active, 'Log', StringName=NAME+'_seller_active', Text='With money in my purse and a blade at my side, I am ready to travel. Zora runs the stables at Neuhof. I should introduce myself and ask about her horses.')
    done = ET.SubElement(logs, 'EnumLog', Name='Done', Type='Completed')
    ET.SubElement(done, 'Log', StringName=NAME+'_seller_done', Text='I met Zora at Neuhof. She showed me where to find her horses and explained how to buy one or trade in my current mount. I can choose a horse when I am ready.')
    resources[ENTRY], resources[PATH] = xml(entry), xml(root)
    # Only our GlueTravel journals are changed; native campaign quests retain
    # their authored classification and saved state paths.
    for path, blob in list(resources.items()):
        if path.startswith('Quests/GlueTravel/') and path.endswith('.xml'):
            doc = ET.fromstring(blob)
            for journal in doc.findall('Skald/Quest'): journal.set('Type', 'Side')
            resources[path] = xml(doc)
    strings = ET.Element('Table')
    for element in root.iter():
        if element.get('StringName'):
            row = ET.SubElement(strings, 'Row')
            for value in (element.get('StringName'), element.get('Text'), element.get('Text')):
                ET.SubElement(row, 'Cell').text = value
    return resources, xml(strings)
