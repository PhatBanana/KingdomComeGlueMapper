"""Resolve authored daycycles through source activity links and behavior tables.

Names, clocks, areas, routes and routines are source data. This planner does not
replace an unsupported routine with a walk-to-point or an idle animation.
"""
import re
import xml.etree.ElementTree as ET


def day_intervals(entries):
    if not entries: return []
    ordered = sorted(entries, key=lambda r: r['start_minute'])
    starts = [r['start_minute'] for r in ordered]
    if len(starts) != len(set(starts)) or any(not 0 <= s < 1440 for s in starts):
        raise ValueError('Invalid or duplicate daycycle start')
    result = []
    for index, row in enumerate(ordered):
        start = row['start_minute']; end = starts[(index + 1) % len(starts)]
        spans = [(0, 1440)] if len(ordered) == 1 else (
            [(start, end)] if end > start else [(start, 1440), (0, end)])
        for first, last in spans:
            if first != last:
                result.append(dict(activity=row['activity'], start_minute=first, end_minute=last))
    return sorted(result, key=lambda r: r['start_minute'])


def plan(person, tables):
    areas = {r['sa_smart_area_id']: r for r in tables.get('ai/sa_smart_area')['rows']}
    bindings = tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
    behaviors = {r['sa_behaviour_tag_id']: r for r in tables.get('ai/sa_behaviour_tag')['rows']}
    resolved, pending = [], []
    for interval in day_intervals(person['ai']['schedule']):
        links = [l for l in person['ai']['links'] if re.split(r'[\[,]', l['label'], maxsplit=1)[0].casefold()
                 == interval['activity'].casefold()]
        if not links:
            pending.append(dict(interval, reason='No source activity link')); continue
        for link in links:
            match = re.fullmatch(r"\w+\[\('([^']+)'\)\]", link['label'])
            if not match:
                pending.append(dict(interval, link=link['label'], reason='Unsupported activity link expression')); continue
            entity = ET.fromstring(link['source_xml'])
            props = entity.find('Properties')
            template = props.get('guidSmartAreaTemplate') if props is not None else None
            if template not in areas: raise ValueError('Unresolved source activity area template')
            candidates = [(b, behaviors[b['sa_behaviour_tag_id']]) for b in bindings
                          if b['sa_smart_area_id'] == template and
                          behaviors[b['sa_behaviour_tag_id']]['sa_behaviour_tag_name'] == match[1]]
            if len(candidates) != 1: raise ValueError('Missing or ambiguous source activity behavior: ' + match[1])
            binding, behavior = candidates[0]
            resolved.append(dict(interval, area=dict(entity.attrib), area_template=areas[template],
                behavior=dict(behavior), binding=dict(binding), source_link=link['label'],
                target_links=[dict(l.attrib) for l in entity.findall('EntityLinks/Link')],
                runtime_verified=False))
    return dict(person=person['name'], resolved=resolved, pending=pending, runtime_verified=False)


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    from character_person import resolve_person
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--person', action='append', required=True)
    parser.add_argument('--source-level', default='rataje')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with RetailSourceReader(args.source) as reader:
        tables = SourceTables(args.source, reader)
        reports = [plan(resolve_person(args.source, name, args.source_level), tables) for name in args.person]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(reports, stream, indent=2)
