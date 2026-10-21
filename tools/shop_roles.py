"""Give converted shopkeepers the native haggle and shop-ending roles.

KCD2 does not attach haggling to a shop. When the player confirms a trade it
looks for the haggle and negotiation dialogues through roles on the seller,
and the farewell through the shop-ending roles. A converted keeper only has
its own role, so confirming a sale did nothing: the player kept the items and
received no money (retail 1.5.6, 2026-10-21).

The roles come from the native Storm operations in IPL_GameData.pak
Libs/Storm/common/roles_operations.xml. Only the haggle and negotiation roles
of addShopRoles_essential_* are used: its OBCHODNIK_Z_CHATU and
OBCHODNIK_Z_DIALOGU_* roles open trade themselves and would add a second
Trade option beside the keeper's converted one.
"""
import xml.etree.ElementTree as ET

from upgrade_map import xml

HAGGLE = {'man': ('SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ'), 'woman': ('SMLOUVANI_ZENA', 'VYJEDNAVANI_ZENA')}
ENDING = {'man': 'addShopRoles_ending_man', 'woman': 'addShopRoles_ending_woman'}
ROLE_FILES = 'libs/storm/roles/'


def keepers(mission):
    """{person name: 'man' | 'woman'} for every NPC linked to a Shop as its shopKeeper."""
    root = ET.fromstring(mission)
    shops = {e.get('EntityGuid') for e in root.iter('Entity') if e.get('EntityClass') == 'Shop'}
    result = {}
    for entity in root.iter('Entity'):
        if entity.get('EntityClass') not in ('NPC', 'NPC_Female'):
            continue
        if any(link.get('Name') == 'shopKeeper' and link.get('TargetGuid') in shops
               for link in entity.findall('EntityLinks/Link')):
            result[entity.get('Name')] = 'woman' if entity.get('EntityClass') == 'NPC_Female' else 'man'
    return result


def add_haggle_roles(role_files, people):
    """Add the haggle, negotiation and ending roles to each keeper's own roles rule.

    role_files maps Storm role file names to their bytes. A keeper's own rule is
    the person rule named <file stem>_roles in Libs/Storm/roles/<file stem>.xml
    that selects exactly that person by name and adds a role. Every person
    stage writes that shape (character_person, horse_trader, the Rattay
    innkeeper and miller), so all ten keepers of a real package have one.
    Dialogue namespaces also select a keeper by name (ska_blanka in
    gm_tavern_dialog.xml, rule gm_tavern_dialog_<soul>), and those rules are
    left alone whatever order the files sort in. Returns the changed files and
    a report; running it again changes nothing.
    """
    changed, added, done = {}, [], set()
    for name in sorted(role_files):
        if not name.lower().startswith(ROLE_FILES) or not name.lower().endswith('.xml'):
            continue
        own_rule = name.rsplit('/', 1)[1][:-len('.xml')] + '_roles'
        root = ET.fromstring(role_files[name])
        touched = False
        for rule in root.iter('rule'):
            selected = [s.get('name') for s in rule.findall('selectors/hasName')]
            operations = rule.find('operations')
            if rule.get('name') != own_rule or len(selected) != 1 or selected[0] not in people or selected[0] in done:
                continue
            if operations is None or operations.find('addRole') is None:
                continue
            person = selected[0]; sex = people[person]; done.add(person)
            present = {(o.tag, o.get('name')) for o in operations}
            wanted = [('addRole', role) for role in HAGGLE[sex]] + [(ENDING[sex], None)]
            new = [(tag, role) for tag, role in wanted if (tag, role) not in present]
            for tag, role in new:
                ET.SubElement(operations, tag, {'name': role} if role else {})
            if new:
                touched = True; added.append(person)
        if touched:
            changed[name] = xml(root)
    return changed, dict(version=1, keepers=len(people), added=sorted(added),
                         without_roles_rule=sorted(set(people) - done), runtime_verified=False)
