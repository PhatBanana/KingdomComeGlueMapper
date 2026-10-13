"""Stage source RPG initialization at explicitly selected campaign lifecycle edges.

The binding JSON selects existing graph edges, not actor-specific game logic.
An installation step must verify the baseline hashes before replacing files.
"""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_initial_state import bind_before, quest_start_states, source_stats
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from build_horse_trader_test import rewrite, digest
from upgrade_map import read


def build(source, target, package, output, binding):
    if output.exists(): raise FileExistsError('Choose a fresh output directory')
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        soul = tables.row('rpg/soul', 'soul_id', binding['source_soul'])
        assignments = [r for r in tables.get('rpg/soul2skill')['rows'] if r['soul_id'] == soul['soul_id']]
        if assignments:
            raise ValueError('Authored soul2skill overrides require an explicit native skill merge; refusing default levels')
        behavior = reader(source, {'controller': ('Scripts.pak', binding['source_controller'])})['controller']
        states, state_report = quest_start_states(behavior['data'])
        required = {lock for record in state_report for lock in record['readiness_locks']}
        if required - set(binding['satisfied_readiness_locks']):
            raise ValueError('Entry lifecycle does not satisfy source readiness locks')
        provenance = dict(soul=tables.get('rpg/soul')['provenance'], controller=behavior['candidates'])
    minimum = binding['unassigned_skill_level']
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError('Invalid unassigned skill baseline')
    with zipfile.ZipFile(target / 'Data/Tables.pak') as archive:
        skills = {n.get('skill_name'): minimum for n in ET.fromstring(
            read(archive, 'Libs/Tables/rpg/skill.xml')).iter('skill')}
    with zipfile.ZipFile(target / 'Data/IPL_GameData.pak') as archive:
        definitions = read(archive, 'Libs/concept/definitions.xml')
    with zipfile.ZipFile(package) as archive:
        blob = read(archive, binding['graph'])
    reports = []
    for name, values in [('baseline', (source_stats(soul), skills, {})), ('quest_start', ({}, {}, states))]:
        selected = binding[name]
        blob, report = bind_before(blob, selected['destination'], selected['input'], selected['event'],
                                  binding['soul_asset'], binding['namespace'] + '_' + name,
                                  *values, definitions)
        reports.append(report)
    output.mkdir(parents=True)
    rewrite(package, output / package.name, {binding['graph']: blob})
    report = dict(binding=binding, provenance=provenance, states=state_report, operations=reports,
                  baseline=digest(package), package=digest(output / package.name),
                  installed=False, runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'target', 'package', 'output', 'binding'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    report = build(args.source, args.target, args.package, args.output,
                   json.loads(args.binding.read_text(encoding='utf-8')))
    print(json.dumps(dict(package=report['package'], installed=False)))
