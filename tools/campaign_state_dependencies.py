"""Import referenced RPG states without detaching actions from their quest gates.

The scan is a dependency preflight, not an execution schedule. It visits runtime
Roots only, preserving each source site and its ancestry. Helper documents may
contain unused trees; their presence never implies that they run at startup.
"""
import argparse
import json
from pathlib import Path

from campaign_buffs import BuffAdapter, native_contract
from campaign_dependencies import DependencyImporter
from campaign_dependency_adapters import SourceTables, LazyAdapter, ItemTextAdapter
from campaign_sources import RetailSourceReader
from quest_import import import_quest, literal


STATE_OPERATIONS = {'AddBuff', 'RemoveBuffs', 'SetExternalLock', 'ExternalLock',
                    'ExecuteLua', 'LuaGate', 'EnableProfile', 'ProfileLoadedGate',
                    'SetQuestObjective', 'SetQuest', 'Expression', 'VarOperation',
                    'CreateItem', 'EquipItem', 'UnEquipItem'}


def scan(model, importer):
    sites, variables = [], []
    for document, payload in model['behavior_documents'].items():
        for name, tree in payload['trees'].items():
            for variable in tree['variables']:
                if variable.get('isPersistent') == '1':
                    variables.append(dict(document=document, tree=name, variable=variable))

            def visit(node, path, ancestors):
                op, attrs = node['op'], node['attributes']
                site = dict(document=document, tree=name, path=path, operation=op,
                            arguments=attrs, ancestors=ancestors)
                if op in STATE_OPERATIONS:
                    if op in ('AddBuff', 'RemoveBuffs'):
                        identity = literal(attrs.get('BuffGUID', ''))
                        if identity and not identity.startswith('$'):
                            site['dependency'] = dict(group='buffs', source=identity,
                                target=importer.ensure('buffs', identity, dict(
                                    document=document, tree=name, path=path, operation=op)))
                        else:
                            site['unresolved'] = 'Dynamic or tag-selected buff needs runtime resolution'
                    sites.append(site)
                parent = dict(path=path, operation=op, arguments=attrs)
                for index, child in enumerate(node['children']):
                    visit(child, path + '/' + str(index), ancestors + [parent])
            visit(tree['root'], 'Root', [])
    return dict(quest=model['quest'], sites=sites, persistent_variables=variables,
                runtime_validated=False, executable=False,
                scope='All parsed runtime trees; branch reachability is not asserted')


def build(source, target, quest, output, namespace):
    output = Path(output)
    if output.exists():
        raise ValueError('State dependency output already exists')
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        model, _ = import_quest(source, quest, source_reader=reader)
        importer = DependencyImporter(dict(
            buffs=BuffAdapter(tables, native_contract(target), namespace),
            strings=LazyAdapter(lambda: ItemTextAdapter(source, namespace, 'English'))))
        report = scan(model, importer)
        report['dependencies'] = importer.report()
        output.mkdir(parents=True)
        for name, data in importer.files.items():
            path = output / 'native-fragments' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (output / 'state-dependencies.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return dict(quest=quest, state_sites=len(report['sites']),
                dependencies=report['dependencies']['counts'], executable=False,
                report=str(output / 'state-dependencies.json'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kcd1', type=Path, required=True)
    p.add_argument('--kcd2', type=Path, required=True)
    p.add_argument('--quest', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--namespace', required=True)
    a = p.parse_args()
    print(json.dumps(build(a.kcd1, a.kcd2, a.quest, a.output, a.namespace), indent=2))
