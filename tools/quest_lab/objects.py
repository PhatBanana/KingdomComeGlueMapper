"""Explicit object snapshots for native reads. Never invent state or effects.

Each object has declared native type facets, properties and exact argument-keyed
query results. Queries are observations, not implementations of native systems.
"""
import copy
import json

from . import Unsupported
from .collections import validate


SOUL = 'wh::rpgmodule::I_Soul'
COMBAT = 'wh::rpgmodule::I_CombatSoul'
INVENTORY = 'wh::entitymodule::Inventory'
PROPERTIES = {
    SOUL: ('I_Soul', {'Inventory':'ref', 'CombatSoul':'ref', 'IsDead':'bool',
                      'IsBleeding':'bool', 'IsDrunk':'bool', 'EquipmentManager':'ref'}),
    COMBAT: ('I_CombatSoul', {'Target':'ref', 'IsUnarmed':'bool', 'HasMissileWeapon':'bool', 'HasMeleeWeapon':'bool'}),
    'wh::entitymodule::Stash': ('Stash', {'Inventory':'ref'}),
}
# Receiver port, required query arguments, optional query arguments, output, type.
QUERIES = {
    (SOUL, 'GetState'): ('Soul', {'State'}, set(), 'Value', 'float'),
    (SOUL, 'GetDerivedStat'): ('Soul', {'DerivedStat'}, {'Context'}, 'Value', 'float'),
    (SOUL, 'GetStatLevel'): ('Soul', {'Stat'}, set(), 'Value', 'float'),
    (SOUL, 'GetSkillLevel'): ('Soul', {'Skill'}, set(), 'Value', 'float'),
    (SOUL, 'IsBodyPartBleeding'): ('Soul', {'BodyPart'}, set(), 'Value', 'bool'),
    (COMBAT, 'HasWeaponInHand'): ('Target', {'Weapon'}, set(), 'bool', 'bool'),
    (INVENTORY, 'GetMoney'): ('Inventory', set(), set(), 'Amount', 'uint'),
    (INVENTORY, 'Items'): ('Inventory', set(), set(), 'Items', 'items'),
}


def describe(element):
    if any(edge.get('To') == 'Exec' for edge in element.findall('Edge')): return None
    typ = element.get('DeclaringType')
    if element.tag == 'ObjectProperties' and typ in PROPERTIES:
        receiver, outputs = PROPERTIES[typ]
        return dict(receiver=receiver, inputs={receiver}, required={receiver}, outputs=outputs, typ=typ)
    key = (typ, element.get('MethodName'))
    if element.tag == 'MemberFunction' and key in QUERIES:
        receiver, args, optional, port, value_type = QUERIES[key]
        return dict(receiver=receiver, inputs={receiver} | args | optional,
                    required={receiver} | args, outputs={port:value_type}, typ=typ, method=key[1])


def checked(value, typ):
    if typ == 'ref':
        if value is not None and (not isinstance(value, str) or not value):
            raise Unsupported('Object reference must be an explicit identity or null')
    elif typ == 'items':
        if not isinstance(value, dict) or any(not isinstance(k,str) or not k or type(v) is not int or v < 0
                                              for k,v in value.items()):
            raise Unsupported('Items snapshot requires item-class/nonnegative-count pairs')
    else: validate(value, typ)


def key(method, arguments):
    return json.dumps([method, arguments], sort_keys=True, allow_nan=False)


class Objects:
    def __init__(self, graph, records):
        self.graph = graph
        self.enabled = records is not None
        self.records = copy.deepcopy({} if records is None else records)
        self.validate(self.records)

    @staticmethod
    def validate(records):
        if not isinstance(records, dict): raise ValueError('Objects must map explicit identities to native facets')
        for identity, facets in records.items():
            if not isinstance(identity, str) or not identity or not isinstance(facets, dict):
                raise ValueError('Invalid object identity/facets')
            for typ, facet in facets.items():
                if not isinstance(typ,str) or not isinstance(facet,dict) or set(facet) - {'properties','queries'}:
                    raise ValueError('Invalid native facet')
                properties, queries = facet.get('properties', {}), facet.get('queries', [])
                if not isinstance(properties,dict) or not isinstance(queries,list): raise ValueError('Invalid native facet data')
                for name, value in properties.items():
                    schema = PROPERTIES.get(typ, (None,{}))[1]
                    if name not in schema: raise ValueError('Unmodeled object property: ' + typ + '.' + name)
                    checked(value, schema[name])
                seen = set()
                for query in queries:
                    if not isinstance(query,dict) or set(query) != {'method','arguments','result'}:
                        raise ValueError('Query requires method, arguments and result')
                    if not isinstance(query['method'],str): raise ValueError('Native query method must be a string')
                    spec = QUERIES.get((typ,query['method']))
                    if spec is None: raise ValueError('Unmodeled native query: ' + str(query['method']))
                    args = query['arguments']
                    if not isinstance(args,dict) or not spec[1] <= set(args) <= spec[1] | spec[2]:
                        raise ValueError('Query arguments do not match native interface')
                    if any(not isinstance(v,str) or not v for v in args.values()):
                        raise ValueError('Query arguments require explicit nonempty names/identities')
                    identity_key = key(query['method'], args)
                    if identity_key in seen: raise ValueError('Duplicate object query snapshot')
                    seen.add(identity_key); checked(query['result'], spec[4])

    def replace(self, identity, facets):
        if not self.enabled or identity not in self.records:
            raise ValueError('Object update must replace a declared snapshot identity')
        self.validate({identity:facets})
        self.records[identity] = copy.deepcopy(facets)
        self.graph.record('object_snapshot', identity=identity, facets=copy.deepcopy(facets), boundary='explicit_engine_observation')

    def read(self, name, spec, port, args):
        if port not in spec['outputs']: raise Unsupported('Unmodeled object output: ' + name + '.' + port)
        if not spec['required'] <= set(args) <= spec['inputs']:
            raise Unsupported('Native query arguments do not match interface: ' + name)
        receiver = args[spec['receiver']]
        if not isinstance(receiver,str) or not receiver: raise Unsupported('Native query requires an explicit receiver: ' + name)
        facet = self.records.get(receiver, {}).get(spec['typ'])
        if facet is None: raise Unsupported('Missing object snapshot: ' + receiver + ' as ' + spec['typ'])
        arguments = {k:v for k,v in args.items() if k != spec['receiver']}
        if 'method' in spec:
            wanted = key(spec['method'], arguments)
            matches = [q for q in facet.get('queries', []) if key(q['method'], q['arguments']) == wanted]
            if len(matches) != 1: raise Unsupported('Missing exact query observation: ' + receiver + ' ' + wanted)
            value = matches[0]['result']
        else:
            if port not in facet.get('properties', {}): raise Unsupported('Missing property observation: ' + receiver + '.' + port)
            value = facet['properties'][port]
        checked(value, spec['outputs'][port])
        self.graph.record('object_read', node=name, receiver=receiver, declaring_type=spec['typ'],
                          method=spec.get('method'), arguments=copy.deepcopy(arguments), port=port,
                          value=copy.deepcopy(value), boundary='explicit_engine_observation')
        return copy.deepcopy(value)
