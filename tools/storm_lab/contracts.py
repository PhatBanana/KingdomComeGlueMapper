"""Service contracts and package findings over evaluated Storm results.

A service contract is a role set a native C++ service looks up on an NPC. A
missing role makes the service silently do nothing, so each contract row
cites where its requirement comes from. Role names are derived from the
native customOperation macros wherever possible, not hard-coded.
"""
import re
import xml.etree.ElementTree as E

from .tables import parse

GENDER = {'NPC': 'man', 'NPC_Female': 'woman'}
SUFFIX = {'man': 'MUZ', 'woman': 'ZENA'}

TRADE_SOURCE = ('8edd58f (tools/shop_roles.py): trade confirmation needs SMLOUVANI_<g>, VYJEDNAVANI_<g> and the '
                'addShopRoles_ending_<g> roles; found and fixed in game 2026-10-21. The remaining '
                'addShopRoles_essential_<g> roles open a second Trade option.')
MERCHANT_ROLE = re.compile(r'^(SMLOUVANI|VYJEDNAVANI|OPRAVAR|OBCHODNIK|OBCHODNICE|PODKONI)(_|$)')


def keepers(mounts):
    """{entity name: dict(gender, level)} for NPCs linked to a Shop as shopKeeper, from mod mission files."""
    result = {}
    for member in mounts.names('levels/', 'mod'):
        if not member.endswith('objects_mission0.xml'): continue
        root = parse(mounts.read(member, 'mod'))
        shops = {e.get('EntityGuid') for e in root.iter('Entity') if e.get('EntityClass') == 'Shop'}
        for entity in root.iter('Entity'):
            if entity.get('EntityClass') not in GENDER: continue
            if any(l.get('Name') == 'shopKeeper' and l.get('TargetGuid') in shops
                   for l in entity.findall('EntityLinks/Link')):
                result[entity.get('Name')] = dict(gender=GENDER[entity.get('EntityClass')], level=member)
    return result


def macro_roles(program, name):
    """Role names a customOperation adds (recursively); None if the macro is not defined."""
    bodies = program.custom_operations.get(name)
    if not bodies: return None
    roles = []
    for child in bodies[0][1]:
        if not isinstance(child.tag, str): continue
        if child.tag == 'addRole': roles.append(child.get('name'))
        else:
            nested = macro_roles(program, child.tag)
            if nested: roles.extend(nested)
    return roles


def merchant_side_roles(program):
    """Roles that make an NPC act as a seller/repairer: all addShopRoles_*/repairmen macro roles except
    the customer-side gossip roles, plus haggle/negotiation/repair role names."""
    roles = set()
    for name in program.custom_operations:
        if name.startswith('addShopRoles_') or name.startswith('addGenericRepairmenRoles'):
            roles |= set(macro_roles(program, name) or [])
    return roles


def trade_contract(program, tables, results, shop_keepers):
    rows = []
    for person, info in sorted(shop_keepers.items()):
        g = info['gender']
        haggle = ['SMLOUVANI_' + SUFFIX[g], 'VYJEDNAVANI_' + SUFFIX[g]]
        ending = macro_roles(program, 'addShopRoles_ending_' + g)
        essential = macro_roles(program, 'addShopRoles_essential_' + g)
        row = dict(contract='trade', soul=person, gender=g, source=TRADE_SOURCE)
        result = results.get(person)
        if ending is None or essential is None:
            row.update(status='UNSUPPORTED', detail='native shop macros not found in the Storm program')
        elif result is None:
            row.update(status='FAIL', detail='shopKeeper entity has no soul row in the package')
        else:
            required = haggle + ending
            forbidden = [r for r in essential if r not in haggle]
            missing = [r for r in required if r not in result.roles]
            conditional = [r for r in required if r in result.roles and not result.roles[r].definite]
            duplicate = [r for r in forbidden if r in result.roles]
            row.update(required=required, forbidden=forbidden, missing=missing, conditional=conditional,
                       duplicate_trade=duplicate,
                       negotiation_metarole=dict(
                           storm='VYJEDNAVANI' in result.metaroles,
                           role_table=any(tables.roles.get(r, {}).get('metarole_name') == 'VYJEDNAVANI'
                                          for r in result.roles)))
            if missing or any(result.roles[r].definite for r in duplicate):
                row['status'] = 'FAIL'
            elif conditional or duplicate:
                row['status'] = 'UNSUPPORTED'
            else:
                row['status'] = 'PASS'
        rows.append(row)
    return rows


def findings(program, tables, results, shop_keepers):
    out = []

    def add(kind, severity, soul, detail, **extra):
        out.append(dict(kind=kind, severity=severity, soul=soul, detail=detail, **extra))

    merchant = merchant_side_roles(program)
    for name, r in sorted(results.items()):
        soul = r.soul
        if not soul.converted: continue
        # Character and voice references.
        character = soul.get('skald_character_name')
        if character and character not in tables.characters:
            add('missing-character', 'error', name, 'skald_character_name %s is not in any skald_character table' % character)
        elif character:
            vid = tables.characters[character].get('voice_id')
            if vid and vid not in tables.voices:
                add('missing-voice', 'error', name, 'character %s voice_id %s is not in any voice table' % (character, vid))
        if soul.get('voice_group_name') and not character:
            native_same = sum(n for (has_char, group), n in tables.native_shapes.items() if group and not has_char)
            native_total = sum(n for (_, group), n in tables.native_shapes.items() if group)
            add('voice-group-without-character', 'review', name,
                'voice_group_name=%s with no skald character: %d of %d native souls with a voice group have this shape. '
                'voice_group_name is written by the offline Storm characters task (characters/voiceGroups.xml), '
                'not read by any runtime selector modeled here.' % (soul.get('voice_group_name'), native_same, native_total),
                voice_group=soul.get('voice_group_name'))
        # Merchant-side roles on souls that are not linked shop keepers.
        if name not in shop_keepers:
            leaked = sorted(role for role in r.roles if role in merchant or MERCHANT_ROLE.match(role))
            for role in leaked:
                st = r.roles[role]
                add('merchant-role-on-non-keeper', 'review', name,
                    '%s (%s) without a shopKeeper link' % (role, 'definite' if st.definite else 'conditional'),
                    role=role, sources=st.sources)
        # Role targets exist.
        for role, st in sorted(r.roles.items()):
            if role not in tables.roles:
                mod = any(s['layer'] == 'mod' for s in st.sources)
                add('unknown-role', 'error' if mod else 'review', name, 'role %s is not in any role table' % role,
                    role=role, sources=st.sources)
        # Inventory preset targets exist.
        for op in r.operations:
            if op['op'] in ('setInventory', 'addInventory', 'setLootInventory') and op['status'] != 'NO':
                preset = op['attrs'].get('preset')
                if preset and preset not in tables.presets:
                    add('unknown-inventory-preset', 'error' if op['layer'] == 'mod' else 'review', name,
                        '%s preset %s does not exist' % (op['op'], preset), operation=op)
        # Native rules that select this converted soul by name.
        for path, layer, pattern in sorted(r.name_hits):
            if layer == 'native':
                add('native-name-capture', 'review', name, 'native %s hasName "%s" matches this converted soul' % (path, pattern),
                    file=path, pattern=pattern)
        # Order-sensitive hasRole readers.
        table_metaroles = {tables.roles.get(role, {}).get('metarole_name') for role in r.roles}
        for alt in r.alternatives:
            if alt.get('with_final_roles') == 'APPLIES':
                ops = alt['operations']
                # role.xml maps each role to a metarole; when every skipped
                # operation only adds a metarole the table already gives this
                # soul's roles, the late order is most likely harmless.
                redundant = ops and all(o['op'] == 'addMetarole' and o.get('name') in table_metaroles for o in ops)
                add('order-sensitive-rule', 'info' if redundant else 'review', name,
                    '%s rule %s reads hasRole before a later source adds the role; with the final role set it would '
                    'apply (%s)%s' % (alt['file'], alt['rule'], ', '.join(o.get('name') or o['op'] for o in ops),
                                     '; role.xml already maps the added roles to that metarole' if redundant else ''),
                    rule=alt)
    # Mod rules whose hasName selects no soul anywhere.
    known = {s.name.lower() for s in tables.souls} | {n.lower() for n in tables.native_soul_names}
    for task, sources in program.tasks:
        for source in sources:
            if source.layer != 'mod': continue
            for rule in source.rules:
                for h in rule.iter('hasName'):
                    pattern = h.get('name') or h.get('Name') or ''
                    if not any(ch in pattern for ch in '*?[') and pattern.lower() not in known:
                        add('mod-rule-selects-no-soul', 'review', pattern,
                            '%s rule %s selects %s, which no soul table defines' % (source.path, rule.get('name'), pattern))
    for missing in program.missing:
        if not missing['tolerated']:
            add('missing-mod-storm-source', 'error', None, 'storm.xml lists %s, present in neither layer' % missing['path'])
    return out
