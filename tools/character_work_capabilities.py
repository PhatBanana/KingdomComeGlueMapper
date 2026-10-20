"""Resolve source work branches before assigning a native job."""
from functools import lru_cache
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read


def housework_phases(tree, actor_class):
    # This is a lowering of the source selector, not a list of actor exceptions.
    branches = [n for n in tree.findall('Root/OnInit/Sequence/IfElseCondition')
                if n.get('condition', '').strip('"').replace(' ', '') ==
                '$b_soul.gender==$enum:humanGender.female']
    if len(branches) != 1 or actor_class not in ('NPC', 'NPC_Female'):
        raise ValueError('Unsupported source housework phase selector')
    branch = branches[0].find('Then' if actor_class == 'NPC_Female' else 'Else')
    if branch is None or any(n.tag != 'Expression' for n in branch):
        raise ValueError('Unsupported source housework phase initialization')
    assignments = [m for n in branch for m in re.finditer(
        r"\$houseworks\[(\d+)\]\.name\s*=\s*'([^']+)'", n.get('expressions', ''))]
    if [int(m[1]) for m in assignments] != list(range(len(assignments))) or not assignments:
        raise ValueError('Ambiguous source housework phases')
    return [m[2] for m in assignments]


@lru_cache(maxsize=8)
def source_housework(scripts_path, actor_class):
    with zipfile.ZipFile(scripts_path) as archive:
        root = E.fromstring(read(archive, 'Libs/AI/final/sa_home.xml'))
    tree = root.find("BehaviorTree[@name='housework']")
    if tree is None:
        raise ValueError('Source housework behavior is missing')
    return housework_phases(tree, actor_class)


def allowed_housework(archive, actor_class):
    scripts = Path(archive.filename).parents[2] / 'Scripts.pak'
    return source_housework(str(scripts), actor_class)


def repair_housework_bindings(files, schedules, archive):
    """Migrate only owned jobs which contradict the source activity selector.

    Retain arrival, clock intervals, home links, and all other activities.
    Unsupported phases remain explicitly pending, as on a clean conversion.
    """
    from campaign_entity_links import guid_value
    from character_schedule_world import ARRIVAL_TEMPLATE
    from character_sweeping_routes import TEMPLATE
    from upgrade_map import xml
    mission = E.fromstring(files['objects_mission0.xml'])
    scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    reports = []
    for person, entries in schedules.items():
        actor = next(e for e in mission if e.get('Name') == person)
        for entry in entries:
            behavior = entry['behavior']
            if (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) != (
                    'final/sa_home.xml', 'housework'):
                continue
            phases = allowed_housework(archive, actor.get('EntityClass'))
            if 'houseSweeping' in phases:
                continue
            name = 'gm_schedule_' + person + '_' + entry['arrival']['EntityId']
            jobs = [e for e in mission if e.get('Name') == name]
            if len(jobs) != 1:
                raise ValueError('Cannot identify owned housework job: ' + name)
            job = jobs[0]
            properties = job.find('Properties')
            if properties is None:
                raise ValueError('Owned housework job has no properties')
            current = properties.get('guidSmartObjectType')
            if current == ARRIVAL_TEMPLATE:
                continue
            if current != TEMPLATE or job.get('EntityClass') != 'SmartObjectHolder':
                raise ValueError('Cannot replace a different live job: ' + name)
            target = str(guid_value(job.get('EntityGuid')))
            owner = str(guid_value(actor.get('EntityGuid')))
            uses = [(r, l) for r in scheduler.find('Schedulers') for l in r.findall('Links/S_ActivityLink')
                    if l.get('TargetGuid') == target]
            if not uses or any(r.get('EntityGuid') != owner or
                    l.find('Parameters') is None or l.find('Parameters').get('BehaviorName') != 'use'
                    for r, l in uses):
                raise ValueError('Housework job has unexpected owners or activity links: ' + name)
            properties.set('guidSmartObjectType', ARRIVAL_TEMPLATE)
            reports.append(dict(person=person, job=name, source_phases=phases, pending=phases,
                                correction='source housework branch excludes sweeping', runtime_verified=False))
    result = dict(files)
    if reports:
        result['objects_mission0.xml'] = xml(mission)
    return result, reports
