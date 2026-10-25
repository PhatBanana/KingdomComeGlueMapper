"""Resolve equipment occupancy from KCD2 RPG tables, independently of visuals.

ArmorType selects a visual family; ArmorArchetypeId determines equipment
occupancy. Native leaf components can override their family's archetype.
Never copy a numeric archetype or layer ID between the games.
"""
from character_person import native_xml
from upgrade_map import read


class NativeEquipment:
    def __init__(self, tables):
        self.types = {r['armor_archetype_id']: r['armor_archetype_name']
                      for r in tables['armor_archetype']}
        self.names = {}
        for identity, name in self.types.items():
            if name in self.names:
                raise ValueError('Ambiguous native equipment archetype: ' + name)
            self.names[name] = identity
        parts = {r['equipment_part_id']: r['equipment_part_name'] for r in tables['equipment_part']}
        subparts = {r['body_subpart_id']: parts[r['equipment_part_id']] for r in tables['body_subpart']}
        self.layers = {identity: set() for identity in self.types}
        self.exclusive = {identity: set() for identity in self.types}
        for row in tables['armor_archetype2body_subpart']:
            identity, subpart, layer = (row[k] for k in ('armor_archetype_id', 'body_subpart_id', 'body_layer_id'))
            self.layers[identity].add((subparts[subpart], layer))
            if row['is_exclusive'].lower() in ('true', '1'):
                self.exclusive[identity].add((subpart, layer))

    @classmethod
    def from_archive(cls, archive):
        names = ('armor_archetype', 'armor_archetype2body_subpart', 'body_subpart', 'equipment_part')
        return cls({name: [dict(n.attrib) for n in native_xml(read(archive,
                    'Libs/Tables/item/' + name + '.xml')).iter(name)] for name in names})

    def source_contract(self, part, source_tables, default_archetype, region):
        source = source_tables.row('item/armor_archetype', 'armor_archetype_id', part['armor_archetype_id'])
        name = source['armor_archetype_name']
        identity = self.names.get(name)
        if identity is None:
            # The existing visual-family policy supplies renamed native roles
            # (e.g. footwear). This is explicit in evidence, not a new ID guess.
            identity = default_archetype
            resolution = 'native_visual_family_default'
        else:
            resolution = 'source_archetype_name'
        layers = {layer for native_region, layer in self.layers[identity] if native_region == region}
        if len(layers) != 1:
            raise ValueError('Missing or ambiguous native equipment layer: ' + name + ' / ' + region)
        return dict(archetype=identity, layer=next(iter(layers)), source_name=name,
                    native_name=self.types[identity], resolution=resolution)
