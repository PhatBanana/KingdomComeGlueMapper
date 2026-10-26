"""Soul rows and the native/mod lookup tables Storm selectors read.

Table patch files follow the KCD2 convention: ``<table>.xml`` plus any
``<table>__<suffix>.xml``. Rows are merged by primary key, mod after native,
so a mod row replaces a native row with the same key (recorded in
``overrides``). That merge rule is the documented modding convention, not a
reading of the engine binary.
"""
from collections import Counter
from dataclasses import dataclass, field
import posixpath
import re
import xml.etree.ElementTree as E

_DOCTYPE = re.compile(rb'<!DOCTYPE[^>]*>')
_DECL = re.compile(r'^\s*<\?xml[^>]*\?>')


def parse(data):
    """Parse native XML that may declare us-ascii while holding Latin-1 bytes."""
    data = _DOCTYPE.sub(b'', data)
    try:
        return E.fromstring(data)
    except E.ParseError:
        text = data.decode('utf-8-sig', errors='replace')
        return E.fromstring(_DECL.sub('', text))


@dataclass
class Soul:
    name: str
    attrs: dict
    origin: str          # 'mod' or 'native'
    file: str
    converted: bool = False

    def get(self, key, default=None):
        return self.attrs.get(key, default)


@dataclass
class Tables:
    souls: list = field(default_factory=list)
    archetypes: dict = field(default_factory=dict)     # id -> row
    social_classes: dict = field(default_factory=dict)  # id -> name
    genders: dict = field(default_factory=dict)         # id -> name
    characters: dict = field(default_factory=dict)      # skald_character_name -> row
    voices: dict = field(default_factory=dict)          # voice_id -> row
    factions: dict = field(default_factory=dict)        # name -> dict(parent, labels)
    roles: dict = field(default_factory=dict)           # role_name -> row
    presets: set = field(default_factory=set)           # InventoryPreset names
    overrides: list = field(default_factory=list)
    files: dict = field(default_factory=dict)           # table -> [(layer, member)]
    native_soul_names: set = field(default_factory=set)
    native_shapes: Counter = field(default_factory=Counter)  # (has character, voice_group_name) -> rows

    def voice_of(self, soul):
        """Resolve soul -> skald character -> voice row. Returns (status, row).

        status: 'no-character' | 'missing-character' | 'no-voice' | 'missing-voice' | 'ok'
        """
        name = soul.get('skald_character_name')
        if not name: return 'no-character', None
        character = self.characters.get(name)
        if character is None: return 'missing-character', None
        voice_id = character.get('voice_id')
        if not voice_id: return 'no-voice', None
        voice = self.voices.get(voice_id)
        if voice is None: return 'missing-voice', None
        return 'ok', voice

    def group_voices(self, group):
        """Voices whose voice_groups list contains ``group`` (all voices if group is None)."""
        if group is None: return list(self.voices.values())
        return [v for v in self.voices.values() if group in (v.get('voice_groups') or '').split(';')]

    def faction_chain(self, name):
        chain, seen = [], set()
        while name and name not in seen:
            seen.add(name); chain.append(name)
            name = self.factions.get(name, {}).get('parent')
        return chain


def _table_members(mounts, directory, table):
    """[(layer, member)] for table.xml and table__*.xml, native first then mod."""
    prefix = 'libs/tables/' + directory + '/'
    pattern = re.compile(re.escape(prefix + table.lower()) + r'(__[^/]*)?\.xml$')
    found = []
    for layer in ('native', 'mod'):
        for member in mounts.names(prefix, layer):
            if pattern.match(member): found.append((layer, member))
    return found


def _rows(mounts, directory, table, element, tables):
    tables.files[table] = _table_members(mounts, directory, table)
    for layer, member in tables.files[table]:
        root = parse(mounts.read(member, layer))
        for row in root.iter(element):
            yield layer, member, row


def _merge(target, key, row, layer, member, tables, table):
    if key in target and target[key][1] != layer:
        tables.overrides.append(dict(table=table, key=key, by=member))
    target[key] = (row, layer)


def load(mounts, native_souls=False):
    t = Tables()
    merged = {}
    for name, (directory, element, key) in dict(
            soul_archetype=('rpg', 'soul_archetype', 'soul_archetype_id'),
            social_class=('rpg', 'social_class', 'social_class_id'),
            gender=('rpg', 'gender', 'gender_id'),
            skald_character=('skald', 'skald_character', 'skald_character_name'),
            voice=('skald', 'voice', 'voice_id'),
            role=('rpg', 'role', 'role_name')).items():
        merged[name] = {}
        for layer, member, row in _rows(mounts, directory, name, element, t):
            if row.get(key) is None: continue
            _merge(merged[name], row.get(key), dict(row.attrib), layer, member, t, name)
    t.archetypes = {k: v for k, (v, _) in merged['soul_archetype'].items()}
    t.social_classes = {k: v.get('social_class_name') for k, (v, _) in merged['social_class'].items()}
    t.genders = {k: v.get('gender_name') for k, (v, _) in merged['gender'].items()}
    t.characters = {k: v for k, (v, _) in merged['skald_character'].items()}
    t.voices = {k: v for k, (v, _) in merged['voice'].items()}
    t.roles = {k: v for k, (v, _) in merged['role'].items()}
    # FactionTree nests <Faction> under <Children>; the parent is structural.
    t.files['FactionTree'] = _table_members(mounts, 'rpg', 'FactionTree')
    for layer, member in t.files['FactionTree']:
        root = parse(mounts.read(member, layer))

        def walk(node, parent):
            for child in node:
                if child.tag == 'Faction':
                    name = child.get('Name')
                    labels = set((child.get('Labels') or '').replace(',', ';').replace(' ', ';').split(';')) - {''}
                    previous = t.factions.get(name)
                    entry = dict(parent=parent, labels=labels, layer=layer)
                    if previous and previous['parent'] and not parent:
                        # A mod patch that re-declares a faction at top level
                        # to add relations keeps the native parent.
                        entry['parent'] = previous['parent']; entry['labels'] = previous['labels'] | labels
                    t.factions[name] = entry
                    walk(child, name)
                elif child.tag in ('Children', 'FactionTree'):
                    walk(child, parent)
        walk(root, None)
    t.files['InventoryPreset'] = _table_members(mounts, 'item', 'InventoryPreset')
    for layer, member in t.files['InventoryPreset']:
        for row in parse(mounts.read(member, layer)).iter('InventoryPreset'):
            if row.get('Name'): t.presets.add(row.get('Name'))
    # Souls: every soul table row of the mod layer is a converted soul. Native
    # rows are loaded only for the self-check (they are the no-oracle baseline).
    t.files['soul'] = _table_members(mounts, 'rpg', 'soul')
    by_name = {}
    for layer, member in t.files['soul']:
        for row in parse(mounts.read(member, layer)).iter('soul'):
            name = row.get('soul_name')
            if not name: continue
            if layer == 'native':
                t.native_soul_names.add(name)
                t.native_shapes[(bool(row.get('skald_character_name')), row.get('voice_group_name'))] += 1
                if not native_souls: continue
            soul = Soul(name, dict(row.attrib), layer, posixpath.basename(member), converted=(layer == 'mod'))
            if name in by_name:
                t.overrides.append(dict(table='soul', key=name, by=member))
            by_name[name] = soul
    t.souls = sorted(by_name.values(), key=lambda s: (not s.converted, s.name.lower()))
    return t

