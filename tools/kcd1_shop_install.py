"""Install the ported KCD1 shop conversation for the seven converted Skalitz traders and neu_zdena.

neu_zdena sits on one of KCD2's own characters (her KCD1 voice aric is that character's voice), so
her voice comes from retail's character table; her own rule is the horse-trader one, kept as it is.

kcd1_shop_conversation turns KCD1's greeting, farewell, trade choice and haggle
closures into KCD2 dialogs. This step puts them in the package, for the converted
KCD1 keepers in SCOPE only (native KCD2 shopkeepers keep the native dialogs):

- a `gm_kcd1_shop` Gameplay module in Quests/GlueTravel/kcd1_shop/, registered
  in the project-level open_world voice namespace (smithing_voice/open_world.xml)
  beside the prayer and barrier registrations. It holds the two greetings, the
  two farewells, the two haggle dialogs and the trade dialog. The greetings are
  wired to KCD2's greeting state node and once-a-day cooldown, as KCD2's common
  greeting is; the farewells to the same state node's reputation outputs, as
  KCD2's common farewell is.
  The haggle dialogs' denial buff, theft message and tutorial outputs are wired
  as in KCD2's haggle module. The module carries a private utils closure
  (native/) for those two utils graphs; entry/world/open_world.xml belongs to
  the crime step and is never written here;
- role rows: GM_KCD1_SMLOUVANI_* carry metarole SMLOUVANI, which the shop
  screen uses to find the haggle (and so the sale); GM_KCD1_ROZLOUCENI_* carry
  ROZLOUCENI, which plays the farewell after the talk screen closes; the
  greeting and trade roles carry NPC;
- each keeper's own Storm rule gains the four roles and loses the native
  haggle role, the native spoken-trade role (v1), the native shop greeting (v2)
  and the native post-purchase farewell. It also removes KCD2's common greeting
  and farewell, which the KCD1 ones replace, and every role retail's generic trader
  rules (roles/world/shop.xml) would add except negotiation: their haggle, spoken
  and chat trade, shop greeting, post-purchase endings and customer gossip. KCD1 had no trade farewell, and
  KCD1 NPCs keep only their KCD1 lines. Negotiation (VYJEDNAVANI) stays native:
  it is not a shop step;
- the keepers' generated trade dialogs leave the archive and the entry Level;
- the KCD1 recordings of the trader voices and Henry go to the module's audio
  scope, each with a dubbing row for its own stem. The text goes to
  text_ui_dialog, and every line's KCD1 facial record to the facial pak through
  the same FacialImporter (and rig adapter) main uses for Henry's tavern lines.
  Source headers are keyed by lowercase stem; KCD1 recording names are not.

Before writing it checks, as if the generic trader rules selected every keeper,
that exactly one role with metarole SMLOUVANI, one with ROZLOUCENI and one
Trade role (the port's own) bind to each keeper, audits the module's node types and asset aliases through their
packaged scopes, and copies the native Project Types the graphs use. It is
idempotent, so a saved -5 (v1) or -6 (v2) package and a fresh build end in the
same state. The pre-release layout under entry/world/ (step version 1, never
shipped) is refused, not migrated, because removing it would rewrite the crime
wrapper.
"""
from collections import defaultdict
import copy
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

import kcd1_shop_conversation as conversation
from upgrade_map import read, xml

VERSION = 3
TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'Data/Levels/kcd1_travel/level.pak'
ENGLISH = 'Localization/English.pak'
ENGLISH_XML = 'Localization/English_xml.pak'
FACIALS = 'Data/gluemapper_dialogue_facials.pak'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
HOST = 'Quests/GlueTravel/smithing_voice/open_world.xml'
FOLDER = 'Quests/GlueTravel/kcd1_shop/'
MODULE = 'gm_kcd1_shop'
AUDIO_SCOPE = 'dialog/open_world/gm_kcd1_shop/'
CRIME_HOST = 'Quests/GlueTravel/entry/world/open_world.xml'
OLD_FOLDER = 'Quests/GlueTravel/entry/world/kcd1_shop/'
OLD_AUDIO_SCOPE = 'dialog/kcd1_travel/open_world/gm_kcd1_shop/'
NATIVE_PROJECT = 'Quests/Final/Barbora.xml'
NATIVE_UTILS = 'quests/final/barbora/utils/'
STUB_ENTRY = 'gm_kcd1_shop_stub/entry.xml'
STUB_WRAPPER = 'quests/final/barbora/gm_kcd1_shop_stub.xml'
STUB_MODULE = 'quests/final/barbora/open_world/' + MODULE + '.xml'
ROLE_TABLE = 'Libs/Tables/rpg/role__gm_kcd1_shop.xml'
ROLE_FILES = 'libs/storm/roles/'
SCOPE = ('ska_merchant1', 'ska_merchant2', 'ska_merchant3', 'ska_merchant4', 'ska_woman20', 'ska_collierVarlet',
         'ska_blanka', 'neu_zdena', 'rato_innkeeper1', 'rat_pesek')
CHARACTER_TABLE = 'Libs/Tables/skald/skald_character__gm_kcd1_shop.xml'
DROP_ROLES = frozenset(('SMLOUVANI_MUZ', 'SMLOUVANI_ZENA', 'OBCHODNIK_Z_DIALOGU_MUZ', 'OBCHODNICE_Z_DIALOGU_ZENA'))
DROP_OPERATIONS = frozenset(('addShopRoles_greeting_man', 'addShopRoles_greeting_woman',
                             'addShopRoles_ending_man', 'addShopRoles_ending_woman'))
REMOVE_NATIVE = ('POZDRAV_MUZ', 'POZDRAV_ZENA', 'ROZLOUCENI_S_HRACEM_COMMON_MUZ', 'ROZLOUCENI_S_HRACEM_COMMON_ZENA')
# Retail's generic trader rules (IPL_GameData Libs/Storm/roles/world/shop.xml) give any open-world
# full or lighter trader with a merchant voice KCD2's haggle, spoken and chat trade, shop greeting,
# post-purchase endings and customer gossip. A ported keeper removes every role they add except
# negotiation (VYJEDNAVANI), whether or not the rule selects it: removing an absent role is a no-op
# (retail crime_bandit removes four roles no rule adds).
GENERIC_SHOP = 'Libs/Storm/roles/world/shop.xml'
GENERIC_SHOP_RULES = {sex: tuple(f'shop_{kind}{sex}' for kind in ('', 'isLightTrader_', 'isVeryLightTrader_',
                                                                  'isUltraLightTrader_'))
                      for sex in ('man', 'woman')}
KEPT_METAROLES = frozenset(('VYJEDNAVANI',))
# The KCD2 roles whose dialogs offer Trade in the talk screen, besides the port's own.
TRADE_STYLE = re.compile(r'OBCHODNI(?:K|CE)_Z_(?:DIALOGU_(?:MUZ|ZENA)|CHATU)')
NATIVE_HAGGLE_MODULE = 'Quests/Final/Barbora/open_world/shop/bribe_haggle_negotiation_vyjednavani_smlouvani_podplaceni.xml'
GREETING_STATE = {'hrac_je_spinavy', 'hrac_je_zakrvaceny', 'hrac_ma_alespon_vysoke_charisma', 'je_odpoledne', 'je_rano',
                  'je_vecer', 'nastvanost__klid', 'nastvanost__neklid', 'reputace_dobra', 'reputace_nizka',
                  'reputace_stredni'}


def roles_for(sex, trade=True):
    """The port's roles; trade=False for a keeper whose own rule already opens the shop (see own_trade)."""
    return ((conversation.TRADE_ROLE,) if trade else ()) + (conversation.GREETING_ROLE[sex], conversation.PORTED_ROLE[sex],
                                                            conversation.FAREWELL_ROLE[sex])


def shop_dialog_roles(quest_files, skip=()):
    """Roles bound by a talk-screen FaderDialog that opens a shop, outside the dialogs in skip."""
    roles = set()
    for path, blob in quest_files.items():
        if path in skip or b'OpenShop' not in blob or b'<FaderDialog' not in blob:
            continue
        for dialogue in ET.fromstring(blob).iter('Dialogue'):
            if any(s.get('Type') == 'OpenShop' for s in dialogue.iter('Sequence')) and dialogue.get('NonSpeakerRoles'):
                roles.update(dialogue.get('NonSpeakerRoles').split(','))
    return roles


def own_trade(rule, custom, shop_roles):
    """The roles in a keeper's own rule that already open its shop (e.g. the maintainer's rattay_miller)."""
    found = []
    for operation in rule.find('operations'):
        names = [operation.get('name')] if operation.tag == 'addRole' else custom.get(operation.tag, [])
        found += [n for n in names if n in shop_roles]
    return found


def role_rows():
    """The package role rows: only the haggle roles carry SMLOUVANI, only the farewells ROZLOUCENI."""
    root = ET.Element('database', name='barbora')
    roles = ET.SubElement(root, 'roles', version='1')
    names = [(conversation.TRADE_ROLE, 'NPC')]
    for sex in conversation.SEXES:
        names += [(conversation.GREETING_ROLE[sex], 'NPC'), (conversation.PORTED_ROLE[sex], 'SMLOUVANI'),
                  (conversation.FAREWELL_ROLE[sex], 'ROZLOUCENI')]
    for name, metarole in names:
        ET.SubElement(roles, 'role', _locked='false', _role_string_name='role_' + name, metarole_name=metarole, role_name=name)
    return xml(root)


def generated(blob):
    """(keeper soul, keeper role) of a silent generated trade dialog, else None (region_travel_merchant shape)."""
    root = ET.fromstring(blob)
    dialogue = root.find('Skald/FaderDialog/Dialogue')
    if dialogue is None or any(r.find('Text') is not None for r in dialogue.iter('Response')):
        return None
    shops = [s for s in dialogue.iter('Sequence') if s.get('Type') == 'Shop'
             and s.find("Decision/Sequences/Sequence[@Type='OpenShop']") is not None]
    souls = [s for s in dialogue.findall('SelectedSouls/SelectedSoul') if s.get('Soul')]
    if len(shops) != 1 or len(souls) != 1 or souls[0].get('Role') != dialogue.get('NonSpeakerRoles'):
        return None
    return souls[0].get('Soul'), souls[0].get('Role')


def own_rule(role_files, person):
    """(file, root, rule) of the keeper's own roles rule (<file stem>_roles selecting only the keeper), or None."""
    for name in sorted(role_files):
        if not name.lower().startswith(ROLE_FILES) or not name.lower().endswith('.xml'):
            continue
        root = ET.fromstring(role_files[name])
        for rule in root.iter('rule'):
            selected = [s.get('name') for s in rule.findall('selectors/hasName')]
            if rule.get('name') == name.rsplit('/', 1)[1][:-4] + '_roles' and selected == [person] \
                    and rule.find('operations/addRole') is not None:
                return name, root, rule
    return None


def generic_shop_roles(shop_blob, custom, metaroles):
    """{sex: roles retail's generic trader rules add, negotiation excepted}, custom operations expanded."""
    rules = {r.get('name'): r for r in ET.fromstring(shop_blob).iter('rule')}
    result = {}
    for sex, names in GENERIC_SHOP_RULES.items():
        missing = [n for n in names if n not in rules]
        if missing:
            raise ValueError('Retail generic shop rules changed: ' + ', '.join(missing))
        roles = []
        for name in names:
            for operation in rules[name].find('operations'):
                if operation.tag == 'addRole':
                    roles.append(operation.get('name'))
                elif operation.tag in custom:
                    roles += custom[operation.tag]
                else:
                    raise ValueError(f'Unknown operation {operation.tag} in retail shop rule {name}')
        result[sex] = sorted({r for r in roles if metaroles.get(r) not in KEPT_METAROLES})
    return result


def keeper_roles(rule, custom, generic):
    """A keeper's roles from its own rule on top of every generic shop role, own removals applied."""
    added, removed = list(generic), set()
    for operation in rule.find('operations'):
        if operation.tag == 'addRole':
            added.append(operation.get('name'))
        elif operation.tag == 'removeRole':
            removed.add(operation.get('name'))
        else:
            added += custom.get(operation.tag, [])
    return [r for r in dict.fromkeys(added) if r not in removed]


def port_rule(rule, sex, generic=(), trade=True):
    """Edit one keeper's operations in place; returns (added, removed) names.

    generic: the roles retail's generic trader rules give this sex (generic_shop_roles), removed too.
    trade: whether the keeper gets the port's "Let's talk trade." role.
    """
    operations = rule.find('operations')
    removed = []
    for operation in list(operations):
        if (operation.tag == 'addRole' and operation.get('name') in DROP_ROLES) or operation.tag in DROP_OPERATIONS:
            operations.remove(operation)
            removed.append(operation.get('name') or operation.tag)
    present = {(o.tag, o.get('name')) for o in operations}
    wanted = [('addRole', role) for role in roles_for(sex, trade)] + [('removeRole', role) for role in REMOVE_NATIVE]
    wanted += [('removeRole', role) for role in generic if role not in REMOVE_NATIVE]
    added = [(tag, role) for tag, role in wanted if (tag, role) not in present]
    for tag, role in added:
        ET.SubElement(operations, tag, name=role)
    return [f'{tag}:{role}' for tag, role in added], removed


def haggle_roles(rule, metaroles, custom, metarole='SMLOUVANI'):
    """Roles with the metarole (SMLOUVANI by default) that a rule adds, custom operations expanded."""
    found = []
    for operation in rule.find('operations'):
        names = [operation.get('name')] if operation.tag == 'addRole' else custom.get(operation.tag, [])
        found += [n for n in names if metaroles.get(n) == metarole]
    return found


def greeting_nodes(sex, ports):
    """Module nodes feeding one ported greeting, after KCD2's common greeting wiring."""
    dialog, role = conversation.GREETING_NAME[sex], conversation.GREETING_ROLE[sex]
    state, souls, greeted, cooldown = (f'{dialog}_{n}' for n in ('state', 'souls', 'greeted', 'cooldown'))
    nodes = []
    node = ET.Element('timeandplayerstate', Name=state, Namespace='utils.greetings_utils')
    ET.SubElement(node, 'Asset', Name='player', Alias='player_any')
    ET.SubElement(node, 'Edge', {'From': f'{dialog}.{role}', 'To': 'npc'})
    nodes.append(node)
    node = ET.Element('MakeArray', Name=souls, TypeT='wh::rpgmodule::Souls')
    ET.SubElement(node, 'Edge', {'From': f'{dialog}.{role}', 'To': 'A'})
    nodes.append(node)
    node = ET.Element('Function', Name=greeted, MethodName='wh::xgenaimodule::CheckEntityContext', DeclaringType='wh::xgenaimodule')
    ET.SubElement(node, 'Constant', Name='Context', Value='owcd_npc_playerGreeting')
    ET.SubElement(node, 'Edge', {'From': f'{souls}.Array', 'To': 'Souls'})
    nodes.append(node)
    node = ET.Element('addopenworldcooldown', Name=cooldown, Namespace='utils.general')
    ET.SubElement(node, 'Constant', Name='cooldowntype', Value='dialogPlayerGreeting')
    ET.SubElement(node, 'Edge', {'From': f'{dialog}.{role}', 'To': 'npc'})
    ET.SubElement(node, 'Edge', {'From': f'{dialog}.{conversation.COOLDOWN}', 'To': 'addcooldown'})
    nodes.append(node)
    node = ET.Element(dialog, Name=dialog)
    for port in ports:
        if port not in GREETING_STATE:
            raise ValueError('Greeting port without a KCD2 state output: ' + port)
        ET.SubElement(node, 'Edge', {'From': f'{state}.{port}', 'To': port})
    ET.SubElement(node, 'Edge', {'From': f'{greeted}.HasContext', 'To': conversation.GREETED})
    nodes.append(node)
    return nodes


def farewell_nodes(sex, ports):
    """Module nodes feeding one ported farewell, after KCD2's common farewell wiring (rozlouceni_na_konci_dialogu)."""
    dialog, role = conversation.FAREWELL_NAME[sex], conversation.FAREWELL_ROLE[sex]
    state = f'{dialog}_state'
    node = ET.Element('timeandplayerstate', Name=state, Namespace='utils.greetings_utils')
    ET.SubElement(node, 'Asset', Name='player', Alias='player')
    ET.SubElement(node, 'Edge', {'From': f'{dialog}.{role}', 'To': 'npc'})
    farewell = ET.Element(dialog, Name=dialog)
    for port in ports:
        if port not in GREETING_STATE:
            raise ValueError('Farewell port without a KCD2 state output: ' + port)
        ET.SubElement(farewell, 'Edge', {'From': f'{state}.{port}', 'To': port})
    return [node, farewell]


def haggle_nodes(native_module, sex):
    """The native haggle module's nodes for one dialog, cloned onto the ported dialog and role."""
    native_name = PurePosixPath(conversation.NATIVE_HAGGLE[sex]).stem
    ported, old_role, new_role = conversation.PORTED_NAME[sex], conversation.NATIVE_ROLE[sex], conversation.PORTED_ROLE[sex]
    nodes = ET.fromstring(native_module).find('Skald/Gameplay/Nodes')
    chosen = [n for n in nodes if n.tag != native_name and any(
        (e.get('From') or '').split('.')[0] == native_name for e in n.findall('Edge'))]
    if not chosen or nodes.find(native_name) is None:
        raise ValueError('Native haggle module changed: ' + native_name)
    rename = {n.get('Name'): f"{ported}_{n.get('Name')}" for n in chosen}
    referenced = {(e.get('From') or '').split('.')[0] for n in chosen for e in n.findall('Edge')}
    missing = referenced - set(rename) - {native_name}
    if missing:
        raise ValueError('Native haggle wiring depends on other nodes: ' + ', '.join(sorted(missing)))
    result = []
    for node in chosen:
        clone = copy.deepcopy(node)
        clone.set('Name', rename[node.get('Name')])
        for edge in clone.findall('Edge'):
            source, _, port = edge.get('From').partition('.')
            source = ported if source == native_name else rename[source]
            edge.set('From', f"{source}.{new_role if port == old_role else port}")
            for vertex in list(edge):
                edge.remove(vertex)
        result.append(clone)
    result.append(ET.Element(ported, Name=ported))
    return result


def dialog_names():
    return [conversation.TRADE_NAME] + [n for sex in conversation.SEXES
                                        for n in (conversation.GREETING_NAME[sex], conversation.PORTED_NAME[sex],
                                                  conversation.FAREWELL_NAME[sex])]


def module(native_module, greeting_ports, farewell_ports, utils=True):
    """The module graph; with utils it declares and instantiates its private native/utils.xml."""
    root = ET.Element('Database', Name='brambora')
    host = ET.SubElement(ET.SubElement(root, 'Skald'), 'Gameplay', Name=MODULE, VoiceNamespace='true')
    definitions, nodes = ET.SubElement(host, 'Definitions'), ET.SubElement(host, 'Nodes')
    for name in dialog_names():
        ET.SubElement(definitions, 'Definition', File=name + '.xml')
    if utils:
        ET.SubElement(definitions, 'Definition', File='native/utils.xml')
    for sex in conversation.SEXES:
        nodes.extend(greeting_nodes(sex, greeting_ports[sex]))
        nodes.extend(haggle_nodes(native_module, sex))
        nodes.extend(farewell_nodes(sex, farewell_ports[sex]))
    nodes.append(ET.Element(conversation.TRADE_NAME, Name=conversation.TRADE_NAME))
    if utils:
        ET.SubElement(nodes, 'utils', Name='utils')
    return xml(root)


def register(host_blob):
    """Project-level open_world wrapper with the module declared and instantiated once."""
    root = ET.fromstring(host_blob)
    skald = root.find('Skald')
    host = skald[0] if skald is not None and len(skald) == 1 else None
    if host is None or host.tag != 'Gameplay' or host.get('Name') != 'open_world' or host.get('VoiceNamespace') != 'true':
        raise ValueError('Project voice namespace wrapper changed: ' + HOST)
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    if definitions is None or nodes is None:
        raise ValueError('Project voice namespace wrapper has no definitions or nodes')
    file = posixpath.relpath(FOLDER + MODULE + '.xml', posixpath.dirname(HOST))
    declared = [d for d in definitions if posixpath.basename(d.get('File') or '') == MODULE + '.xml']
    instances = nodes.findall(MODULE)
    if len(declared) > 1 or any(d.get('File') != file for d in declared) or len(instances) > 1 \
            or any(i.get('Name') != MODULE or len(i) for i in instances):
        raise ValueError('Existing KCD1 shop module registration requires review')
    if not declared:
        ET.SubElement(definitions, 'Definition', File=file)
    if not instances:
        ET.SubElement(nodes, MODULE, Name=MODULE)
    return xml(root)


def check_project(project_blob):
    """The Project declares and instantiates the project-level open_world wrapper exactly once."""
    from gambler_dialogue_registration import one
    project = ET.fromstring(project_blob).find('Skald/Project')
    if project is None:
        raise ValueError('Project graph host changed: ' + PROJECT)
    one(project.findall("Definitions/Definition[@File='smithing_voice/open_world.xml']"), 'project voice namespace definition')
    one(project.findall("Nodes/open_world[@Name='open_world']"), 'project voice namespace instance')


def utils_closure(scripts, module_blob):
    """{path: graph} of the module's private utils shell, homed in FOLDER + 'native/'.

    world_gameplay_basis.package_dependencies only scans the nodes of copied
    children, so a native-looking copy of the module (its dialogs stripped) is
    put beside the native utils under a stub wrapper and entry; only the utils
    shell and the graphs it reaches are kept.
    """
    from world_gameplay_basis import package_dependencies
    names = {n.lower(): n for n in scripts.namelist()}
    copy_root = ET.fromstring(module_blob)
    definitions = copy_root.find('Skald/Gameplay/Definitions')
    nodes = copy_root.find('Skald/Gameplay/Nodes')
    for definition in list(definitions):
        definitions.remove(definition)
    for node in nodes.findall('utils'):
        nodes.remove(node)
    stub_wrapper = ET.Element('Database', Name='brambora')
    host = ET.SubElement(ET.SubElement(stub_wrapper, 'Skald'), 'Gameplay', Name='open_world', VoiceNamespace='true')
    ET.SubElement(ET.SubElement(host, 'Definitions'), 'Definition',
                  File=posixpath.relpath(STUB_MODULE, posixpath.dirname(STUB_WRAPPER)))
    ET.SubElement(ET.SubElement(host, 'Nodes'), MODULE, Name=MODULE)
    stub_entry = ET.Element('Database', Name='brambora')
    host = ET.SubElement(ET.SubElement(stub_entry, 'Skald'), 'Module', Name='entry')
    ET.SubElement(ET.SubElement(host, 'Definitions'), 'Definition',
                  File=posixpath.relpath(STUB_WRAPPER, posixpath.dirname(STUB_ENTRY)))
    ET.SubElement(ET.SubElement(host, 'Nodes'), 'open_world', Name='open_world')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as view:
        for name in sorted(n for n in names if n.startswith(NATIVE_UTILS)):
            view.writestr(names[name], read(scripts, names[name]))
        view.writestr(STUB_MODULE, xml(copy_root))
    with zipfile.ZipFile(buffer) as view:
        graphs = package_dependencies({STUB_ENTRY: xml(stub_entry), STUB_WRAPPER: xml(stub_wrapper)},
                                      STUB_ENTRY, STUB_WRAPPER, view)
    native = posixpath.dirname(STUB_ENTRY) + '/world/native/'
    if native + 'utils.xml' not in graphs:
        raise ValueError('KCD1 shop module needs no utils closure; module wiring changed')
    kept, pending = {}, ['utils.xml']
    while pending:
        name = pending.pop()
        if name in kept:
            continue
        path = native + name
        if path not in graphs:
            raise ValueError('Utils closure references a missing graph: ' + name)
        kept[name] = graphs[path]
        for definition in ET.fromstring(graphs[path]).iter('Definition'):
            file = definition.get('File')
            if '/' in file:
                raise ValueError('Utils closure reference leaves its folder: ' + file)
            pending.append(file)
    return {FOLDER + 'native/' + name: blob for name, blob in sorted(kept.items())}


def project_bindings(project_blob, native_project_blob, graphs):
    """Project with the native player assets and the native Types the graphs use; (blob, added names)."""
    from gambler_dialogue_registration import one, semantic_xml
    root = ET.fromstring(project_blob)
    project = root.find('Skald/Project')
    native = ET.fromstring(native_project_blob).find('Skald/Project')
    added = []
    assets = project.find('Assets')
    if assets is None:
        assets = ET.SubElement(project, 'Assets')
    for alias in ('player', 'player_any'):
        template = one(native.findall(f"Assets/SoulAsset[@Name='{alias}']"), 'native ' + alias)
        existing = assets.findall(f"*[@Name='{alias}']")
        if existing:
            bound = one(existing, 'inherited ' + alias)
            if bound.tag != 'SoulAsset' or bound.get('SharedSoulGuids') != template.get('SharedSoulGuids'):
                raise ValueError('Conflicting native player binding: ' + alias)
        else:
            assets.append(copy.deepcopy(template))
            added.append('asset:' + alias)
    used = {v for blob in graphs.values() for e in ET.fromstring(blob).iter()
            for k, v in e.attrib.items() if k in ('Type', 'TypeT')}
    types = project.find('Types')
    if types is None:
        types = ET.SubElement(project, 'Types')
    for native_type in native.findall('Types/Type'):
        name = native_type.get('TypeName')
        if name not in used:
            continue
        old = types.findall(f"Type[@TypeName='{name}']")
        if not old:
            types.append(copy.deepcopy(native_type))
            added.append('type:' + name)
        elif semantic_xml(one(old, 'project type ' + name)) != semantic_xml(native_type):
            raise ValueError('Conflicting inherited native type: ' + name)
    return (xml(root) if added else project_blob), added


def check_assets(graphs, path, inherited):
    """Every Asset alias from path down is bound by an enclosing Assets section; returns the graphs walked."""
    walked = 1
    host = ET.fromstring(graphs[path]).find('Skald')[0]
    scope = inherited | {a.get('Name') for a in host.findall('Assets/*')}
    missing = {a.get('Alias') for a in host.iter('Asset')} - scope
    if missing:
        raise ValueError(f'Unbound assets in {path}: {sorted(missing)}')
    for definition in host.findall('Definitions/Definition'):
        walked += check_assets(graphs, posixpath.dirname(path) + '/' + definition.get('File'), scope)
    return walked


def hosted(hosts, folder, native_project, native_definitions):
    """(folder graphs registered in the project-level wrapper, audit report); hosts holds PROJECT and HOST.

    Node types resolve through the folder's own scopes, asset aliases through
    the module's ancestors, and the crime wrapper is never part of the result.
    """
    from world_gameplay_basis import validate_dependency_scopes
    check_project(hosts[PROJECT])
    root = FOLDER + MODULE + '.xml'
    if any(not p.startswith(FOLDER) for p in folder):
        raise ValueError('KCD1 shop graphs outside ' + FOLDER)
    validated = validate_dependency_scopes(folder, root, native_definitions)
    desired = dict(folder)
    desired[HOST] = register(hosts[HOST])
    desired[PROJECT], added = project_bindings(hosts[PROJECT], native_project, folder)
    inherited = {a.get('Name') for a in ET.fromstring(desired[PROJECT]).findall('Skald/Project/Assets/*')}
    inherited |= {a.get('Name') for a in ET.fromstring(desired[HOST]).find('Skald')[0].findall('Assets/*')}
    walked = check_assets(desired, root, inherited)
    if CRIME_HOST in desired:
        raise ValueError('The crime wrapper must not be written by the KCD1 shop port: ' + CRIME_HOST)
    return desired, dict(validated_graphs=validated, asset_checked_graphs=walked, project_added=added)


def utils_libraries(closure):
    """Library namespaces the utils shell declares, e.g. ['general', 'greetings_utils']."""
    shells = [posixpath.basename(p) for p in closure if posixpath.basename(p).startswith('utils_')]
    return sorted(s[len('utils_'):-len('.xml')] for s in shells)


def old_layout(travel_names, crime_blob, english_names):
    """Pre-release (step version 1) traces: files under entry/world/, a crime-wrapper registration, audio."""
    found = sorted(n for n in travel_names if n.startswith(OLD_FOLDER))
    if crime_blob is not None:
        host = ET.fromstring(crime_blob).find('Skald')[0]
        if host.findall('Nodes/' + MODULE) or any(posixpath.basename(d.get('File') or '') == MODULE + '.xml'
                                                    for d in host.findall('Definitions/Definition')):
            found.append(CRIME_HOST + ' registers ' + MODULE)
    found += sorted(n for n in english_names if n.lower().startswith(OLD_AUDIO_SCOPE))
    return found


def voice_tables(travel_names, read_travel, target):
    """({voice_id: (abbreviation, groups)}, {character: [rows]}, {soul_name: character}).

    Retail's voice and skald_character tables, then the package's own rows, which win per character:
    a keeper may sit on one of KCD2's own characters (neu_zdena on char_GENERIC_WOMAN_MERCHANT_CZECH_03).
    """
    voices, characters, packaged, souls = {}, defaultdict(list), defaultdict(list), {}
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as tables:
        for v in ET.fromstring(read(tables, 'Libs/Tables/skald/voice.xml')).iter('voice'):
            voices[v.get('voice_id')] = (v.get('abbreviation'), (v.get('voice_groups') or '').split(';'))
        for name in tables.namelist():
            if name.startswith('Libs/Tables/skald/skald_character') and name.endswith('.xml'):
                for row in ET.fromstring(read(tables, name)).iter('skald_character'):
                    characters[row.get('skald_character_name')].append(dict(row.attrib))
    for name in travel_names:
        if name.startswith('Libs/Tables/rpg/soul__'):
            for soul in ET.fromstring(read_travel(name)).iter('soul'):
                souls[soul.get('soul_name')] = soul.get('skald_character_name')
        elif name.startswith('Libs/Tables/skald/skald_character__'):
            for row in ET.fromstring(read_travel(name)).iter('skald_character'):
                packaged[row.get('skald_character_name')].append(dict(row.attrib))
        elif name.startswith('Libs/Tables/skald/voice__'):
            for voice in ET.fromstring(read_travel(name)).iter('voice'):
                voices[voice.get('voice_id')] = (voice.get('abbreviation'), (voice.get('voice_groups') or '').split(';'))
    characters.update(packaged)
    return voices, characters, souls


def keeper_voices(travel_names, read_travel, target, people):
    """({person: voice abbreviation}, {person: voice groups}) from the package soul, character and voice tables."""
    voices, characters, souls = voice_tables(travel_names, read_travel, target)
    result, result_groups = {}, {}
    for person in people:
        ids = {row.get('voice_id') for row in characters.get(souls.get(person), [])}
        if len(ids) != 1 or next(iter(ids)) not in voices:
            raise ValueError(f'Cannot resolve the voice of {person}: {sorted(ids)}')
        result[person], result_groups[person] = voices[next(iter(ids))]
    return result, result_groups


def source_voices(source, people):
    """{person: KCD1 voice abbreviation} from KCD1's soul, v_soul_character_data and voice tables."""
    from campaign_sources import retail_sources
    files = retail_sources(source, dict(soul=('Tables.pak', 'Libs/Tables/rpg/soul.xml'),
                                        data=('Tables.pak', 'Libs/Tables/rpg/v_soul_character_data.xml'),
                                        abbr=('Tables.pak', 'Libs/Tables/text/v_voice_abbreviation.xml')))
    rows = {k: [r.attrib for r in ET.fromstring(v['data']).findall('./table/rows/row')] for k, v in files.items()}
    ids = {r['soul_name']: r['soul_id'] for r in rows['soul']}
    voice = {r['soul_id']: r['voice_id'] for r in rows['data']}
    abbreviation = {r['voice_id']: r['abbreviation'] for r in rows['abbr']}
    result = {}
    for person in people:
        found = abbreviation.get(voice.get(ids.get(person)))
        if found is None:
            raise ValueError('Cannot resolve the KCD1 voice of ' + person)
        result[person] = found
    return result


def switch_voices(soul_tables, character_table, voices, characters, switches):
    """Put each switched keeper on its KCD1 voice: (changed tables, report).

    switches: {person: KCD1 abbreviation}. The keeper's current character row (retail or packaged)
    is copied unchanged as gm_voice_<person> in the port's own character table, with only voice_id
    changed, and the soul row points at it. Nothing else about the character changes.
    """
    ids = {}
    for voice_id, (abbreviation, _) in voices.items():
        ids.setdefault(abbreviation, []).append(voice_id)
    table = ET.fromstring(character_table) if character_table else ET.Element('database', name='barbora')
    container = table.find('skald_characters')
    if container is None:
        container = ET.SubElement(table, 'skald_characters', version='1')
    changed, report = {}, []
    for person, abbreviation in sorted(switches.items()):
        if len(ids.get(abbreviation, [])) != 1:
            raise ValueError(f'KCD1 voice {abbreviation} of {person} is not a single KCD2 or imported voice')
        rows = [(path, root, soul) for path, root in soul_tables.items() for soul in root.iter('soul')
                if soul.get('soul_name') == person]
        if len(rows) != 1:
            raise ValueError('Expected one package soul row for ' + person)
        path, root, soul = rows[0]
        current = characters.get(soul.get('skald_character_name'), [])
        if len(current) != 1:
            raise ValueError(f'Missing or ambiguous character of {person}: {soul.get("skald_character_name")}')
        identity = 'gm_voice_' + person
        for old in container.findall("skald_character[@skald_character_name='" + identity + "']"):
            container.remove(old)
        ET.SubElement(container, 'skald_character', dict(current[0], skald_character_name=identity,
                                                         voice_id=ids[abbreviation][0]))
        report.append(dict(person=person, character=soul.get('skald_character_name'), now=identity,
                           voice=abbreviation, voice_id=ids[abbreviation][0],
                           previous_voice=voices.get(current[0].get('voice_id'), ('?',))[0]))
        soul.set('skald_character_name', identity)
        changed[path] = xml(root)
    if switches:
        changed[CHARACTER_TABLE] = xml(table)
    return changed, report


def recordings(source, lines):
    """{(voice, string, wave): ogg bytes} for the wanted KCD1 lines, from KCD1's English voice paks."""
    wanted = {}
    for line in lines:
        for voice in line['voices']:
            row = line['rows'].get(voice)
            if row is None:
                raise ValueError(f"KCD1 has no {voice} recording of {line['string']}")
            wanted['dialog/' + row['path'].zfill(6) + '/' + row['wave_file'] + '.ogg'] = (voice, line['string'], row['wave_file'])
    found = {}
    archives = sorted(p for p in (Path(source) / 'Localization').glob('*.pak')
                      if re.fullmatch(r'(?:IPL_)?English(?:-part\d+)?\.pak', p.name, re.I))
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            names = {n.lower(): n for n in z.namelist()}
            for source_name, key in wanted.items():
                actual = names.get(source_name.lower())
                if actual is None:
                    continue
                data = read(z, actual)
                if not data.startswith(b'OggS') or found.get(key, data) != data:
                    raise ValueError('Unusable or ambiguous KCD1 recording: ' + source_name)
                found[key] = data
    missing = set(wanted.values()) - set(found)
    if missing:
        raise ValueError('Missing KCD1 recordings: ' + ', '.join(sorted(k[2] for k in missing)))
    return found


def facial_selection(ported, source_headers, indexed):
    """(recordings with exactly one KCD1 facial track, those not yet in the facial index).

    Covers every ported recording, not only the ones this run adds to English.pak,
    so a package installed before the lowercase lookup gets its missing tracks."""
    headers = {n: source_headers.get(Path(n).stem.lower(), []) for n in ported}
    ambiguous = sorted(n for n, found in headers.items() if len(found) > 1)
    if ambiguous:
        raise ValueError('Ambiguous KCD1 shop lip-sync track: ' + ambiguous[0])
    tracked = {n for n, found in headers.items() if found}
    added = {n: ported[n] for n in sorted(tracked)
             if 'animations/humans/facials/' + n[:-4].lower() + '.caf' not in indexed}
    return tracked, added


def plan(package, source, target):
    """Return (archive -> replacements, travel removals, report) without writing."""
    from shop_roles import keepers
    from campaign_dialogue_runtime import voice_namespace
    from dialogue_dubbing import DEPOT
    package, source, target = Path(package), Path(source), Path(target)
    with zipfile.ZipFile(package / LEVEL) as level:
        people = keepers(read(level, 'objects_mission0.xml'))
    outside = sorted(set(SCOPE) - set(people))
    if outside:
        raise ValueError('KCD1 shop port scope is not a shopkeeper: ' + ', '.join(outside))
    with zipfile.ZipFile(package / TRAVEL) as travel:
        names = set(travel.namelist())
        for required in (ENTRY, PROJECT, HOST):
            if required not in names:
                raise ValueError('Missing package graph (smithing voice stage): ' + required)
        role_files = {n: read(travel, n) for n in names if n.lower().startswith(ROLE_FILES)}
        entry_blob, host_blob, project_blob = read(travel, ENTRY), read(travel, HOST), read(travel, PROJECT)
        crime_blob = read(travel, CRIME_HOST) if CRIME_HOST in names else None
        generated_dialogs = {n: read(travel, n) for n in names
                             if posixpath.dirname(n) == posixpath.dirname(ENTRY) and n.endswith('_trade.xml')}
        role_tables = {n: read(travel, n) for n in names if n.startswith('Libs/Tables/rpg/role__') and n != ROLE_TABLE}
        quest_files = {n: read(travel, n) for n in names if n.startswith('Quests/') and n.endswith('.xml')}
        voices, voice_groups = keeper_voices(names, lambda n: read(travel, n), target, SCOPE)
        voice_rows, characters, _ = voice_tables(names, lambda n: read(travel, n), target)
        soul_tables = {n: ET.fromstring(read(travel, n)) for n in names if n.startswith('Libs/Tables/rpg/soul__')}
        character_table = read(travel, CHARACTER_TABLE) if CHARACTER_TABLE in names else None
    # Every keeper speaks in its KCD1 voice. A keeper the package voices differently (rato_innkeeper1
    # rlaz -> rpro, rat_pesek dosg -> ccla) is switched as a whole: its other lines play in that voice too.
    kcd1_voices = source_voices(source, SCOPE)
    switches = {p: kcd1_voices[p] for p in SCOPE if voices[p] != kcd1_voices[p]}
    voice_changes, voice_report = switch_voices(soul_tables, character_table, voice_rows, characters, switches)
    for person in switches:
        voices[person] = kcd1_voices[person]
        voice_groups[person] = next(g for a, g in voice_rows.values() if a == kcd1_voices[person])
    with zipfile.ZipFile(package / ENGLISH) as english:
        stale = old_layout(names, crime_blob, english.namelist())
    if stale:
        raise ValueError('Pre-release KCD1 shop layout (step version 1) found; it was never shipped and is not '
                         'migrated, because removing it would rewrite the crime wrapper. Rebuild from a package '
                         'without it: ' + ', '.join(stale[:5]) + (f' (+{len(stale) - 5} more)' if len(stale) > 5 else ''))
    check_project(project_blob)
    with zipfile.ZipFile(target / 'Data/Scripts.pak') as scripts, \
            zipfile.ZipFile(target / 'Data/IPL_GameData.pak') as gamedata, zipfile.ZipFile(target / 'Data/Tables.pak') as tables:
        native_module = read(scripts, NATIVE_HAGGLE_MODULE)
        native_project = read(scripts, NATIVE_PROJECT)
        natives = {sex: read(scripts, conversation.NATIVE_HAGGLE[sex]) for sex in conversation.SEXES}
        custom = {o.get('name'): [a.get('name') for a in o if a.tag == 'addRole']
                  for o in ET.fromstring(read(gamedata, 'Libs/Storm/common/roles_operations.xml')).iter('customOperation')}
        generic_shop = read(gamedata, GENERIC_SHOP)
        native_definitions = read(gamedata, 'Libs/concept/definitions.xml')
        metaroles = {r.get('role_name'): r.get('metarole_name')
                     for r in ET.fromstring(read(tables, 'Libs/Tables/rpg/role.xml')).iter('role')}
    for blob in role_tables.values():
        metaroles.update({r.get('role_name'): r.get('metarole_name') for r in ET.fromstring(blob).iter('role')})
    rows = role_rows()
    metaroles.update({r.get('role_name'): r.get('metarole_name') for r in ET.fromstring(rows).iter('role')})
    generic = generic_shop_roles(generic_shop, custom, metaroles)

    models = conversation.load_models(source)
    aliases = {'man': None, 'woman': conversation.topic_aliases(models[('haggle', 'woman')], models[('haggle', 'man')])}
    dialogs, reports, ports, farewell_ports, lines = {}, {}, {}, {}, []
    by_voice = {sex: sorted({voices[p] for p in SCOPE if people[p] == sex}) for sex in conversation.SEXES}
    for sex in conversation.SEXES:
        unknown = set(by_voice[sex]) - set(conversation.VOICES[sex])
        if unknown:
            raise ValueError(f'{sex} keeper voices outside the port: {sorted(unknown)}')
        haggle, haggle_report = conversation.map_haggle(models[('haggle', sex)], natives[sex], sex, aliases[sex])
        differences = conversation.skeleton_differences(natives[sex], haggle, sex, haggle_report['removed_responses'])
        if differences:
            raise ValueError('Ported haggle dialog differs from the KCD2 skeleton: ' + differences[0])
        if re.search(rb'\bSMLOUVANI_(?:MUZ|ZENA)\b', haggle):
            raise ValueError('Native haggle role left in the ported dialog')
        greeting, greeting_report = conversation.emit_greeting(models[('greeting', sex)], sex)
        dialogs[conversation.PORTED_NAME[sex]], dialogs[conversation.GREETING_NAME[sex]] = haggle, greeting
        farewell, farewell_report = conversation.emit_farewell(models[('farewell', sex)], sex)
        dialogs[conversation.FAREWELL_NAME[sex]] = farewell
        ports[sex], farewell_ports[sex] = greeting_report['ports'], farewell_report['ports']
        reports[sex] = dict(haggle={k: v for k, v in haggle_report.items() if k not in ('pairs', 'removed_responses')},
                            greeting={k: v for k, v in greeting_report.items() if k != 'adapter'},
                            farewell=farewell_report, voices=by_voice[sex])
        mapped = {p['string'] for p in haggle_report['pairs']}
        for line in conversation.lines(models[('haggle', sex)]):
            if line['string'] in mapped:
                henry = line['role'] == 'HENRY'
                lines.append(dict(string=line['string'], text=line['text'], rows=line['voices'],
                                  voices=[conversation.HENRY_VOICE] if henry else by_voice[sex]))
        for part in ('greeting', 'farewell'):
            for line in conversation.lines(models[(part, sex)]):
                lines.append(dict(string=line['string'], text=line['text'], rows=line['voices'], voices=by_voice[sex]))
    trade, trade_report = conversation.emit_trade(models[('trade', None)])
    dialogs[conversation.TRADE_NAME] = trade

    folder = {FOLDER + name + '.xml': blob for name, blob in dialogs.items()}
    folder[FOLDER + MODULE + '.xml'] = module(native_module, ports, farewell_ports)
    with zipfile.ZipFile(target / 'Data/Scripts.pak') as scripts:
        closure = utils_closure(scripts, folder[FOLDER + MODULE + '.xml'])
    folder.update(closure)
    desired, audit = hosted({PROJECT: project_blob, HOST: host_blob}, folder, native_project, native_definitions)
    desired[ROLE_TABLE] = rows
    chain = voice_namespace({**quest_files, **desired}, FOLDER + conversation.TRADE_NAME + '.xml')
    scope = 'dialog/' + '/'.join(chain).lower() + '/'
    if scope != AUDIO_SCOPE:
        raise ValueError('KCD1 shop dialogs would resolve to another audio scope: ' + scope)

    # Shop dialogs that stay: not the port's own, not the generated per-keeper ones it removes below.
    removed_generated = {p for p, b in generated_dialogs.items() if (generated(b) or (None,))[0] in SCOPE}
    shop_roles = shop_dialog_roles(quest_files, {p for p in quest_files if p.startswith(FOLDER)} | removed_generated)
    keepers_report, role_changes = [], {}
    for person in SCOPE:
        own = own_rule(role_files, person)
        if own is None:
            raise ValueError('KCD1 shop keeper without its own roles rule: ' + person)
        file_name, root, rule = own
        before = xml(root)
        sex = people[person]
        # A keeper whose own rule already opens its shop (the maintainer's rattay_innkeeper and
        # rattay_miller dialogs) keeps that as its one Trade option instead of "Let's talk trade.".
        kept_trade = own_trade(rule, custom, shop_roles)
        added, removed = port_rule(rule, sex, generic[sex], trade=not kept_trade)
        # Checked as if the generic trader rules select the keeper: they may, and it cannot be told offline.
        roles = keeper_roles(rule, custom, generic[sex])
        trade = [r for r in roles if r == conversation.TRADE_ROLE or TRADE_STYLE.fullmatch(r) or r in shop_roles]
        if trade != (kept_trade or [conversation.TRADE_ROLE]):
            raise ValueError(f'{person} would offer {len(trade)} Trade options: {trade}')
        for metarole, ported in (('SMLOUVANI', conversation.PORTED_ROLE), ('ROZLOUCENI', conversation.FAREWELL_ROLE)):
            bound = [r for r in roles if metaroles.get(r) == metarole]
            if bound != [ported[sex]]:
                raise ValueError(f'{person} binds {len(bound)} {metarole} dialogs: {bound}')
            for name, blob in role_files.items():
                if name == file_name:
                    continue
                for other in ET.fromstring(blob).iter('rule'):
                    if [s.get('name') for s in other.findall('selectors/hasName')] == [person] \
                            and other.find('operations') is not None and haggle_roles(other, metaroles, custom, metarole):
                        raise ValueError(f'Another rule gives {person} a {metarole} role: {name}')
        after = xml(root)
        if after != before:
            role_files[file_name] = role_changes[file_name] = after
        keepers_report.append(dict(
            person=person, sex=sex, voice=voices[person], roles_file=file_name, added=added, removed=removed,
            # retail hasMerchantVoiceOrNoCharacter reads the voice's groups; the other selectors are runtime state
            merchant_voice='Merchants' in voice_groups[person], generic_removed=list(generic[sex]),
            trade=trade[0]))
    desired.update(role_changes)
    desired.update(voice_changes)

    entry = ET.fromstring(entry_blob)
    level_host = entry.find('Skald/Level')
    definitions, nodes = level_host.find('Definitions'), level_host.find('Nodes')
    removed_dialogs = []
    for path, blob in sorted(generated_dialogs.items()):
        shape = generated(blob)
        if shape is None or shape[0] not in SCOPE:
            continue
        name = posixpath.basename(path)[:-4]
        if re.search(r'From="' + re.escape(name) + r'\.', entry_blob.decode('utf-8', 'replace')):
            raise ValueError('Generated trade dialog is wired and requires review: ' + name)
        for definition in list(definitions):
            if definition.get('File') == name + '.xml':
                definitions.remove(definition)
        for node in list(nodes):
            if node.tag == name:
                nodes.remove(node)
        removed_dialogs.append(path)
    if removed_dialogs:
        desired[ENTRY] = xml(entry)

    with zipfile.ZipFile(package / TRAVEL) as travel:
        present_travel = set(travel.namelist())
        current = {p: read(travel, p) for p in desired if p in present_travel}
    travel_changes = {p: b for p, b in desired.items() if current.get(p) != b}
    if CRIME_HOST in desired or CRIME_HOST in travel_changes:
        raise ValueError('The crime wrapper must not be written by the KCD1 shop port: ' + CRIME_HOST)

    found = recordings(source, lines)
    media = {scope + wave + '.ogg': data for (voice, string, wave), data in found.items()}
    ported = dict(media)
    texts = {l['string']: l['text'] for l in lines}
    texts[trade_report['prompt']] = trade_report['text']
    with zipfile.ZipFile(package / ENGLISH) as english:
        present = set(english.namelist())
        for name in [n for n in media if n in present]:
            if read(english, name) != media[name]:
                raise ValueError('English.pak already holds other audio at ' + name)
            del media[name]
        depot = read(english, DEPOT) if media else None
    english_changes = {}
    if media:
        from dialogue_dubbing import dubbing_index
        english_changes = dict(media)
        english_changes[DEPOT] = dubbing_index(target, dict(media), depot)[0]
    rows_root = ET.Element('Table')
    for key, text in sorted(texts.items()):
        row = ET.SubElement(rows_root, 'Row')
        for value in (key, text, text):
            ET.SubElement(row, 'Cell').text = value
    from build_english_audio_test import merge_audio_strings
    with zipfile.ZipFile(package / ENGLISH_XML) as localized:
        current_text = read(localized, 'text_ui_dialog.xml')
    merged = merge_audio_strings(current_text, xml(rows_root))
    text_changes = {'text_ui_dialog.xml': merged} if merged != current_text else {}
    facial_changes, tracked, added = {}, set(), {}
    if ported:
        from dialogue_facials import FacialImporter, INDEX
        with zipfile.ZipFile(package / FACIALS) as facial_pak:
            index = read(facial_pak, INDEX)
        importer = FacialImporter(source, target, index)
        try:
            tracked, added = facial_selection(ported, importer.source_headers, importer.indexed)
            if added:
                importer.add(added)
                facial_changes = importer.resources()
        finally:
            importer.close()
    changes = {TRAVEL: travel_changes, ENGLISH: english_changes, ENGLISH_XML: text_changes, FACIALS: facial_changes}
    report = dict(version=VERSION, scope=list(SCOPE), host=HOST, module=FOLDER + MODULE + '.xml', audio_scope=scope,
                  utils_closure=sorted(closure), utils_libraries=utils_libraries(closure), **audit,
                  keepers=keepers_report, voice_switches=voice_report, dialogs=reports,
                  trade=trade_report, removed_dialogs=removed_dialogs, role_table=ROLE_TABLE,
                  recordings_added=sorted(media), text_rows=len(texts), facial_lines=len(tracked),
                  facial_tracks_added=len(added),
                  # No KCD1 base-pak track (e.g. patch-only); they play without lip-sync here.
                  facial_missing=sorted(set(ported) - tracked),
                  changed={archive: sorted(entries) for archive, entries in changes.items() if entries},
                  runtime_verified=False)
    return changes, removed_dialogs, report


def upgrade(package, source, target, notify=lambda *a: None):
    """Idempotent: a second run changes nothing. English.pak is written first, the travel archive last."""
    if source is None or target is None:
        raise ValueError('KCD1 and KCD2 folders required to port the KCD1 shop conversation')
    package = Path(package)
    changes, removed, report = plan(package, source, target)
    if not any(changes.values()) and not removed:
        return {}, report
    label = 'Port the KCD1 shop conversation'
    notify(label, 0, 1, ', '.join(SCOPE))
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    files = {}
    for archive in (ENGLISH, ENGLISH_XML, FACIALS, TRAVEL):
        gone = set(removed) if archive == TRAVEL else set()
        if changes[archive] or gone:
            rewrite(package, archive, changes[archive], lambda name, gone=gone: name in gone)
            files[archive] = digest(package / archive)
    notify(label, 1, 1, f"{len(report['recordings_added'])} recordings, {len(removed)} generated dialogs removed")
    return files, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True, help='installed or staged package')
    parser.add_argument('--source', type=Path, required=True, help='KCD1 folder')
    parser.add_argument('--game', type=Path, required=True, help='KCD2 folder')
    arguments = parser.parse_args()
    print(json.dumps(plan(arguments.mod, arguments.source, arguments.game)[2], indent=2))
