"""Let converted shopkeepers talk through the native shop dialogue.

Every converted source trader's talk screen was a generated FaderDialog
(`region_travel_merchant.dialogue`, registered by
`campaign_merchant_work.add_trade_dialogue` as `<namespace>_trade` in the entry
Level). It turns greetings and farewells off and its Responses carry no Text,
so neither the trader nor Henry says anything; trading itself works through
its Shop/OpenShop sequences (29 and 31 Oct 2026, every Skalitz market trader).

Retail traders talk through Storm roles instead. `addShopRoles_greeting_*`
adds OBCHODNIK(CE)_ZDRAVI_JINDRU_NEBO_BOHUTU for the native greeting
(open_world/shop/greeting_obchodnika_*.xml), and OBCHODNIK_Z_DIALOGU_MUZ /
OBCHODNICE_Z_DIALOGU_ZENA select the spoken trade dialog
(open_world/shop/nakupovani_z_dialogu_*.xml: Henry asks to trade, the trader
answers, then Shop/OpenShop, or ShopDenied for a branded player). Both live in
the native `shop` module the package already registers, and their recordings
are already relocated. `shop_roles` left OBCHODNIK_Z_DIALOGU out on purpose so
a keeper would not get a second Trade option beside the generated one.

This step swaps the two for the generated source-shop dialogs: it adds the
spoken-trade role and the greeting operation to the keeper's own Storm rule
and removes the generated dialog's registration and file. It only acts when
the native dialog can offer trade: the native Shop sequence requires
`Port('seller_in_shop')`, i.e. the keeper's entity context
`shop_sellerReadyToSell`, which the keeper's work behavior tree must set.
Keepers without such a job, without their own roles rule, or whose dialog has
been edited away from the generated shape are reported and keep the generated
dialog. Other generated trade dialogs (tavern, charcoal) are reported only.
"""
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read, xml

VERSION = 1
TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'Data/Levels/kcd1_travel/level.pak'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
ROLE_FILES = 'libs/storm/roles/'
# Generated dialogs this step replaces; the rest are reported.
SCOPE = re.compile(r'gm_source_shop_\d+_trade')
TRADE_ROLE = {'man': 'OBCHODNIK_Z_DIALOGU_MUZ', 'woman': 'OBCHODNICE_Z_DIALOGU_ZENA'}
GREETING = {'man': 'addShopRoles_greeting_man', 'woman': 'addShopRoles_greeting_woman'}
GREETING_ROLE = {'man': 'OBCHODNIK_ZDRAVI_JINDRU_NEBO_BOHUTU', 'woman': 'OBCHODNICE_ZDRAVI_JINDRU_NEBO_BOHUTU'}
NATIVE_DIALOG = {'man': 'quests/final/barbora/open_world/shop/nakupovani_z_dialogu_muz.xml',
                 'woman': 'quests/final/barbora/open_world/shop/nakupovani_z_dialogu_zena.xml'}
READY = 'shop_sellerReadyToSell'


def generated(blob):
    """(keeper soul, keeper role) when the dialog is the silent generated trade shape, else None."""
    root = ET.fromstring(blob)
    host = root.find('Skald/FaderDialog')
    dialogue = None if host is None else host.find('Dialogue')
    if dialogue is None or dialogue.get('AllowGreeting') != 'false':
        return None
    if any(r.find('Text') is not None for r in dialogue.iter('Response')):
        return None
    shops = [s for s in dialogue.iter('Sequence') if s.get('Type') == 'Shop'
             and s.find("Decision/Sequences/Sequence[@Type='OpenShop']") is not None]
    souls = [s for s in dialogue.findall('SelectedSouls/SelectedSoul') if s.get('Soul')]
    if len(shops) != 1 or len(souls) != 1 or souls[0].get('Role') != dialogue.get('NonSpeakerRoles'):
        return None
    return souls[0].get('Soul'), souls[0].get('Role')


def native_contract(scripts, gamedata):
    """Check the native dialogs, roles and operations this step hands the keepers to."""
    names = {n.lower(): n for n in scripts.namelist()}
    for sex, path in NATIVE_DIALOG.items():
        if path not in names:
            raise ValueError('Missing native spoken trade dialog: ' + path)
        dialog = ET.fromstring(read(scripts, names[path]))
        roles = {r.get('Role') for r in dialog.iter('Response')}
        shop = [s for s in dialog.iter('Sequence') if s.get('Type') == 'Shop']
        if TRADE_ROLE[sex] not in roles or len(shop) != 1 or "Port('seller_in_shop')" not in (shop[0].get('EntryCondition') or ''):
            raise ValueError('Native spoken trade dialog changed: ' + path)
    names = {n.lower(): n for n in gamedata.namelist()}
    operations = {o.get('name'): [a.get('name') for a in o]
                  for o in ET.fromstring(read(gamedata, names['libs/storm/common/roles_operations.xml'])).iter('customOperation')}
    for sex, operation in GREETING.items():
        if GREETING_ROLE[sex] not in operations.get(operation, []):
            raise ValueError('Native shop greeting operation changed: ' + operation)


def ready_trees(travel, tables, scripts, wanted):
    """Smart object type id -> True when one of its behavior trees sets the seller-ready context.

    Only the ids in `wanted` (the keepers' jobs) are resolved; each archive is indexed once.
    """
    wanted = {w.lower() for w in wanted if w}
    indexes = [(a, {n.lower(): n for n in a.namelist()}) for a in (travel, tables, scripts)]
    trees, cache, result = indexes[0::2], {}, {}

    def tree_sets_ready(file_name, tree_name):
        key = (file_name.lower(), tree_name)
        if key not in cache:
            cache[key] = False
            for archive, names in trees:
                path = ('ai/' + file_name).lower()
                if path in names:
                    tree = ET.fromstring(read(archive, names[path])).find(f"BehaviorTree[@name='{tree_name}']")
                    cache[key] = tree is not None and tree.find(f".//EntityContextElement[@context='{READY}']") is not None
                    break
        return cache[key]

    for archive, names in indexes[:2]:
        for lower, name in names.items():
            if len(result) == len(wanted):
                return result
            if not lower.startswith('libs/tables/ai/smartentity/') or not lower.endswith('.xml'):
                continue
            blob = read(archive, name)
            if not any(w.encode() in blob.lower() for w in wanted - set(result)):
                continue
            for template in ET.fromstring(blob).iter('SmartEntityTemplate'):
                identity = (template.get('DatabaseId') or '').lower()
                if identity in wanted and identity not in result:
                    result[identity] = any(tree_sets_ready(l.get('FileName', ''), l.get('TreeName', ''))
                                           for l in template.findall('BehaviorTemplates/SmartBehaviorTemplate/TreeLocation'))
    return result


def own_rule(role_files, person):
    """(file, root, rule) of the keeper's own roles rule, the shape shop_roles writes, or None."""
    for name in sorted(role_files):
        if not name.lower().startswith(ROLE_FILES) or not name.lower().endswith('.xml'):
            continue
        root = ET.fromstring(role_files[name])
        for rule in root.iter('rule'):
            selected = [s.get('name') for s in rule.findall('selectors/hasName')]
            if (rule.get('name') == name.rsplit('/', 1)[1][:-4] + '_roles' and selected == [person]
                    and rule.find('operations/addRole') is not None):
                return name, root, rule
    return None


def keeper_job_ids(mission, dialogs):
    """Smart object type ids of the schedule jobs of every generated dialog's keeper."""
    people = {shape[0] for shape in map(generated, dialogs.values()) if shape}
    return {(e.find('Properties').get('guidSmartObjectType') or '').lower() for e in mission
            if e.find('Properties') is not None and any((e.get('Name') or '').startswith('gm_schedule_' + p + '_') for p in people)}


def plan(package, target):
    """Return (travel replacements, removed travel entries, report) without writing."""
    from shop_roles import keepers
    package, target = Path(package), Path(target)
    with zipfile.ZipFile(package / LEVEL) as level:
        mission = ET.fromstring(read(level, 'objects_mission0.xml'))
    people = keepers(ET.tostring(mission))
    with zipfile.ZipFile(package / TRAVEL) as travel, zipfile.ZipFile(target / 'Data/Scripts.pak') as scripts, \
            zipfile.ZipFile(target / 'Data/IPL_GameData.pak') as gamedata, zipfile.ZipFile(target / 'Data/Tables.pak') as tables:
        native_contract(scripts, gamedata)
        names = set(travel.namelist())
        if ENTRY not in names:
            raise ValueError('Missing entry Level graph: ' + ENTRY)
        entry_blob = read(travel, ENTRY)
        role_files = {n: read(travel, n) for n in names if n.lower().startswith(ROLE_FILES)}
        dialogs = {n: read(travel, n) for n in names
                   if posixpath.dirname(n) == posixpath.dirname(ENTRY) and n.endswith('_trade.xml')}
        ready = ready_trees(travel, tables, scripts, keeper_job_ids(mission, dialogs))
    entry = ET.fromstring(entry_blob)
    host = entry.find('Skald/Level')
    if host is None:
        raise ValueError('Entry graph is not a Level')
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    jobs = {}
    for entity in mission:
        properties = entity.find('Properties')
        if properties is not None and (entity.get('Name') or '').startswith('gm_schedule_'):
            jobs.setdefault(entity.get('Name'), (properties.get('guidSmartObjectType') or '').lower())
    changes, removed, rows = {}, [], []
    for path in sorted(dialogs):
        name = posixpath.basename(path)[:-4]
        shape = generated(dialogs[path])
        row = dict(dialog=name, person=shape[0] if shape else None)
        if not SCOPE.fullmatch(name):
            row['status'] = 'out_of_scope' if shape else 'not_generated'
            rows.append(row)
            continue
        if shape is None:
            row['status'] = 'not_generated'
            rows.append(row)
            continue
        person = shape[0]
        sex = people.get(person)
        row['sex'] = sex
        own = own_rule(role_files, person)
        keeper_jobs = [identity for job, identity in jobs.items() if job.startswith('gm_schedule_' + person + '_')]
        if re.search(r'From="' + re.escape(name) + r'\.', entry_blob.decode('utf-8', 'replace')):
            row['status'] = 'wired_dialog'
        elif sex is None:
            row['status'] = 'not_a_keeper'
        elif own is None:
            row['status'] = 'no_roles_rule'
        elif not keeper_jobs or not any(ready.get(identity) for identity in keeper_jobs):
            row['status'] = 'no_ready_to_sell_job'
        else:
            row['status'] = 'replaced'
        row['jobs_ready'] = [bool(ready.get(identity)) for identity in keeper_jobs]
        if row['status'] != 'replaced':
            rows.append(row)
            continue
        file_name, root, rule = own
        operations = rule.find('operations')
        present = {(o.tag, o.get('name')) for o in operations}
        wanted = [('addRole', TRADE_ROLE[sex]), (GREETING[sex], None)]
        added = [(tag, value) for tag, value in wanted if (tag, value) not in present]
        for tag, value in added:
            ET.SubElement(operations, tag, {'name': value} if value else {})
        if added:
            role_files[file_name] = xml(root)
            changes[file_name] = role_files[file_name]
        for definition in list(definitions if definitions is not None else []):
            if definition.get('File') == name + '.xml':
                definitions.remove(definition)
        for node in list(nodes if nodes is not None else []):
            if node.tag == name:
                nodes.remove(node)
        removed.append(path)
        row.update(roles_file=file_name, added=[value or tag for tag, value in added])
        rows.append(row)
    if removed:
        changes[ENTRY] = xml(entry)
    report = dict(version=VERSION, dialogs=rows, replaced=sorted(r['person'] for r in rows if r['status'] == 'replaced'),
                  native_dialogs=NATIVE_DIALOG, trade_roles=TRADE_ROLE, greeting=GREETING,
                  changed=sorted(changes), removed=sorted(removed), runtime_verified=False)
    return changes, removed, report


def upgrade(package, target, notify=lambda *a: None):
    """Idempotent: once the generated dialogs are gone a second run changes nothing."""
    if target is None:
        raise ValueError('Game folder required to hand shopkeepers to the native shop dialogue')
    package = Path(package)
    changes, removed, report = plan(package, target)
    if not changes and not removed:
        return {}, report
    label = 'Give converted shopkeepers the native shop dialogue'
    notify(label, 0, 1, ', '.join(report['replaced']))
    from setup_package_upgrade import rewrite
    gone = set(removed)
    rewrite(package, TRAVEL, changes, lambda name: name in gone)
    notify(label, 1, 1, f"{len(report['replaced'])} keepers")
    from setup_campaign import digest
    return {TRAVEL: digest(package / TRAVEL)}, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True, help='installed or staged package')
    parser.add_argument('--game', type=Path, required=True, help='KCD2 folder')
    arguments = parser.parse_args()
    print(json.dumps(plan(arguments.mod, arguments.game)[2], indent=2))
