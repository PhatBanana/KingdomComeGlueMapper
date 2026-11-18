"""Service contracts and package findings over evaluated Storm results.

A service contract is a role set a native C++ service looks up on an NPC. A
missing role makes the service silently do nothing, so each contract row
cites where its requirement comes from. Role names are derived from the
native customOperation macros wherever possible, not hard-coded.
"""
import posixpath
import re
import xml.etree.ElementTree as E

from .tables import parse

GENDER = {'NPC': 'man', 'NPC_Female': 'woman'}
SUFFIX = {'man': 'MUZ', 'woman': 'ZENA'}

TRADE_SOURCE = ('8edd58f (tools/shop_roles.py): trade confirmation needs SMLOUVANI_<g>, VYJEDNAVANI_<g> and the '
                'addShopRoles_ending_<g> roles; found and fixed in game 2026-10-21. The remaining '
                'addShopRoles_essential_<g> roles open a second Trade option. The shop finds the haggle by its '
                'SMLOUVANI metarole, so any one role.xml row with that metarole meets the haggle requirement; '
                'a keeper on a ported KCD1 haggle role (kcd1_shop_install) has no ending roles, since KCD1 had '
                'no trade farewell and the native ending dialogs carry no scripts.')
HAGGLE_METAROLE = 'SMLOUVANI'
PORTED_TRADE_ROLE = 'GM_KCD1_OBCHODNIK'
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


def generated_trade_dialogs(mounts):
    """{soul: [FaderDialog names]} for mod trade dialogs a Skald Project, Level or Quest registers: a Shop
    sequence that hands off to an OpenShop sequence the soul responds in. Definition paths are relative to the
    registering file."""
    result = {}
    for member in mounts.names('quests/', 'mod'):
        data = mounts.read(member, 'mod')
        if b'<Definition ' not in data: continue
        for definition in parse(data).iter('Definition'):
            path = posixpath.normpath(posixpath.join(posixpath.dirname(member), definition.get('File', '')))
            dialog = mounts.read(path, 'mod')
            if not dialog or b'OpenShop' not in dialog: continue
            for fader in parse(dialog).iter('FaderDialog'):
                souls = {s.get('Role'): s.get('Soul') for s in fader.iter('SelectedSoul') if s.get('Soul')}
                for shop in fader.iter('Sequence'):
                    if shop.get('Type') != 'Shop': continue
                    for handoff in shop.iter('Sequence'):
                        if handoff.get('Type') != 'OpenShop': continue
                        for response in handoff.iter('Response'):
                            soul = souls.get(response.get('Role'))
                            if soul and fader.get('Name') not in result.setdefault(soul, []):
                                result[soul].append(fader.get('Name'))
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


def trade_contract(program, tables, results, shop_keepers, generated=None):
    """The essential macro's dialog roles (Z_DIALOGU/Z_CHATU) open the native trade dialog. They duplicate
    trade only when a generated trade FaderDialog already serves the keeper; otherwise they are its trade path."""
    generated = generated or {}
    rows = []
    for person, info in sorted(shop_keepers.items()):
        g = info['gender']
        native_haggle, negotiation = 'SMLOUVANI_' + SUFFIX[g], 'VYJEDNAVANI_' + SUFFIX[g]
        haggle = [native_haggle, negotiation]
        ending = macro_roles(program, 'addShopRoles_ending_' + g)
        essential = macro_roles(program, 'addShopRoles_essential_' + g)
        row = dict(contract='trade', soul=person, gender=g, source=TRADE_SOURCE)
        result = results.get(person)
        if ending is None or essential is None:
            row.update(status='UNSUPPORTED', detail='native shop macros not found in the Storm program')
        elif result is None:
            row.update(status='FAIL', detail='shopKeeper entity has no soul row in the package')
        else:
            # The shop finds the haggle by metarole: the native role, or any role mapped to SMLOUVANI.
            bound = [r for r in sorted(result.roles)
                     if r == native_haggle or tables.roles.get(r, {}).get('metarole_name') == HAGGLE_METAROLE]
            ported = [r for r in bound if r != native_haggle]
            required = (ported or [native_haggle]) + [negotiation] + ([] if ported else ending)
            forbidden = [r for r in essential if r not in haggle]
            missing = ([] if bound else [native_haggle]) + [r for r in required[1:] if r not in result.roles]
            conditional = [r for r in bound + required[1:] if r in result.roles and not result.roles[r].definite]
            dialogs = generated.get(person, [])
            native_path = [r for r in forbidden if r in result.roles]
            duplicate = native_path if dialogs else []
            row.update(required=required, forbidden=forbidden if dialogs else [], missing=missing,
                       conditional=conditional, duplicate_trade=duplicate, generated_trade_dialogs=dialogs,
                       native_trade_roles=native_path, haggle_roles=bound, ported_kcd1_haggle=bool(ported),
                       trade_path=PORTED_TRADE_ROLE if PORTED_TRADE_ROLE in result.roles else None,
                       negotiation_metarole=dict(
                           storm='VYJEDNAVANI' in result.metaroles,
                           role_table=any(tables.roles.get(r, {}).get('metarole_name') == 'VYJEDNAVANI'
                                          for r in result.roles)))
            if missing or len(bound) > 1 or any(result.roles[r].definite for r in duplicate):
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
