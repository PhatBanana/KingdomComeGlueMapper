"""Register Henry's native level-barrier bark in the standalone project.

KCD2 stops the player at the map edge with designer brushes whose surface type
is `mat_level_barrier`. Retail Libs/MaterialEffects/SurfaceTypes.xml declares
`<Barrier distance="10" slowdown="1" monologMetaroleId="HRAC_NEMUZE_Z_MAPY"/>`
on it: the engine slows and stops the player and asks the dialogue system for
a monolog on that metarole. Henry holds the matching role JINDRICH_NEMUZE_Z_MAPY
through the retail Storm rule `player_henry` (Libs/Storm/roles/dude.xml, "kcd2
barrier barks"), and the dialog that answers it is
open_world/stavy_hrace_unavahlad/narazeni_na_barieru_voda_level/
jindrich_narazil_na_level_barieru.xml in retail Scripts.pak. The converted
world has the barrier ring and Henry has the role, but the standalone project
never instantiated that dialog, so the request had nothing to play (east road
near 3930,1827 on 29 Oct 2026).

The native parents cannot be registered whole: `stavy_hrace_unavahlad` and
`narazeni_na_barieru_voda_level` both take the campaign input `m03_socky`, and
the module wires two deep-water barks through it and the horse stance. This
step follows the smithing warnings and the church prayer instead: the
project-level `open_world` voice namespace (smithing_voice/open_world.xml)
gets a reduced `stavy_hrace_unavahlad` wrapper and a reduced
`narazeni_na_barieru_voda_level` module that hold only the unmodified native
barrier dialog. The audio scope is then retail's own
`dialog/open_world/stavy_hrace_unavahlad/`, where the installed English banks
already carry Henry's recordings, so nothing is copied or relocated. The
deep-water barks are left for a later step.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from audio_mapping import EnglishRecordings
from campaign_dialogue_runtime import voice_namespace
from upgrade_map import read, xml

VERSION = 1
TRAVEL = 'Data/gluemappertravel.pak'
HOST = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
WRAPPER = 'Quests/GlueTravel/smithing_voice/open_world.xml'
STORM = 'Libs/Storm/storm.xml'
FOLDER = 'Quests/GlueTravel/level_barrier_speech/'
PARENT, MODULE, DIALOG = 'stavy_hrace_unavahlad', 'narazeni_na_barieru_voda_level', 'jindrich_narazil_na_level_barieru'
DEFINITION = '../level_barrier_speech/' + PARENT + '.xml'
NATIVE_PARENT = 'quests/final/barbora/open_world/' + PARENT + '.xml'
NATIVE_MODULE = NATIVE_PARENT[:-4] + '/' + MODULE + '.xml'
NATIVE_DIALOG = NATIVE_MODULE[:-4] + '/' + DIALOG + '.xml'
SURFACE = 'mat_level_barrier'
METAROLE = 'HRAC_NEMUZE_Z_MAPY'
ROLE = 'JINDRICH_NEMUZE_Z_MAPY'
PLAYER_RULE = 'player_henry'
SCOPE = 'dialog/open_world/' + PARENT + '/'


def one(matches, what):
    if len(matches) != 1:
        raise ValueError(f'Expected one {what}, found {len(matches)}')
    return matches[0]


def host_of(blob, path):
    skald = ET.fromstring(blob).find('Skald')
    if skald is None or len(skald) != 1:
        raise ValueError('Expected one Skald container: ' + path)
    return skald[0]


def entry(archive, path):
    names = {n.lower(): n for n in archive.namelist()}
    if path.lower() not in names:
        raise ValueError('Missing native data: ' + path)
    return read(archive, names[path.lower()])


def declares(host, host_path, child_path, child_name):
    """The native host must declare the child file and instantiate it once."""
    files = {posixpath.normpath(posixpath.join(posixpath.dirname(host_path), d.get('File'))).lower()
             for d in host.findall('Definitions/Definition')}
    if child_path not in files or len(host.findall('Nodes/' + child_name)) != 1:
        raise ValueError('Native barrier dialogue layout changed: ' + child_path)


def native_contract(scripts, gamedata, tables):
    """Check every retail piece the bark depends on; return the dialog and its lines."""
    parent = host_of(entry(scripts, NATIVE_PARENT), NATIVE_PARENT)
    module = host_of(entry(scripts, NATIVE_MODULE), NATIVE_MODULE)
    blob = entry(scripts, NATIVE_DIALOG)
    dialog = host_of(blob, NATIVE_DIALOG)
    declares(parent, NATIVE_PARENT, NATIVE_MODULE, MODULE)
    declares(module, NATIVE_MODULE, NATIVE_DIALOG, DIALOG)
    if parent.get('Name') != PARENT or parent.get('VoiceNamespace') != 'true':
        raise ValueError('Native player-state voice namespace changed')
    if module.get('Name') != MODULE or module.get('VoiceNamespace') not in (None, 'false'):
        raise ValueError('Native barrier module changed its voice namespace')
    if dialog.tag != 'Dialog' or dialog.get('Name') != DIALOG:
        raise ValueError('Native level barrier dialog changed')
    ports = dialog.find('Ports')
    if (ports is not None and len(ports)) or dialog.find('Definitions') is not None or dialog.find('.//Asset') is not None:
        raise ValueError('Native level barrier dialog depends on inputs the standalone project lacks')
    dialogue = one(dialog.findall('Dialogue'), 'level barrier dialogue')
    if dialogue.get('Type') != 'ingame monolog':
        raise ValueError('Native level barrier dialog is no longer a monolog')
    responses = list(dialog.iter('Response'))
    if {r.get('Role') for r in responses} != {ROLE}:
        raise ValueError('Native level barrier dialog speaks through other roles')
    texts = [t.get('StringName') for r in responses for t in r.findall('Text')]
    if not texts or len(set(texts)) != len(texts) or not all(texts):
        raise ValueError('Native level barrier dialog has no distinct lines')
    surfaces = ET.fromstring(entry(gamedata, 'Libs/MaterialEffects/SurfaceTypes.xml'))
    surface = one([s for s in surfaces.iter('SurfaceType') if s.get('name') == SURFACE], 'level barrier surface type')
    barrier = surface.find('Barrier')
    if barrier is None or barrier.get('monologMetaroleId') != METAROLE:
        raise ValueError('Native level barrier no longer requests the ' + METAROLE + ' monolog')
    rules = ET.fromstring(entry(gamedata, 'Libs/Storm/roles/dude.xml'))
    rule = one([r for r in rules.iter('rule') if r.get('name') == PLAYER_RULE], 'native player Storm rule')
    operations = rule.find('operations')
    if operations is None or not any(o.tag == 'addRole' and o.get('name') == ROLE for o in operations):
        raise ValueError('Native Storm no longer gives Henry the ' + ROLE + ' role')
    metaroles = ET.fromstring(entry(tables, 'Libs/Tables/rpg/metarole.xml'))
    if not any(m.get('metarole_name') == METAROLE for m in metaroles.iter('metarole')):
        raise ValueError('Native metarole table lacks ' + METAROLE)
    return dict(dialog=blob, texts=texts, barrier=dict(barrier.attrib))


def recordings(members, texts):
    """Native recordings of each line under retail's own audio scope, by voice."""
    result = []
    for text in texts:
        suffix = '_' + text.lower() + '.ogg'
        found = sorted(n for n in members
                       if n.startswith(SCOPE) and n.endswith(suffix) and n.count('/') == SCOPE.count('/'))
        if not found:
            raise ValueError('Missing native level barrier recording for ' + text)
        result.append(dict(text=text, recordings=found, voices=sorted({n[len(SCOPE):-len(suffix)] for n in found})))
    return result


def container(tag, name, child, file, voice_namespace=None):
    root = ET.Element('Database', Name='brambora')
    host = ET.SubElement(ET.SubElement(root, 'Skald'), tag, Name=name)
    if voice_namespace is not None:
        host.set('VoiceNamespace', voice_namespace)
    ET.SubElement(ET.SubElement(host, 'Definitions'), 'Definition', File=file)
    ET.SubElement(ET.SubElement(host, 'Nodes'), child, Name=child)
    return xml(root)


def plan(package, target):
    """Return (travel replacements, report) without writing to either folder."""
    package, target = Path(package), Path(target)
    files = (WRAPPER, FOLDER + PARENT + '.xml', FOLDER + MODULE + '.xml', FOLDER + DIALOG + '.xml')
    with zipfile.ZipFile(package / TRAVEL) as travel:
        names = {n.lower(): n for n in travel.namelist()}
        for required in (HOST, WRAPPER, STORM):
            if required.lower() not in names:
                raise ValueError('Project voice namespace registration missing (smithing voice stage): ' + required)
        project_blob = read(travel, names[HOST.lower()])
        storm = ET.fromstring(read(travel, names[STORM.lower()]))
        current = {p: read(travel, names[p.lower()]) for p in files if p.lower() in names}
    if not any((s.get('path') or '').replace('\\', '/').lower() == 'roles/dude.xml' for s in storm.iter('source')):
        raise ValueError('Package Storm no longer includes the native player roles')
    project = host_of(project_blob, HOST)
    if project.tag != 'Project':
        raise ValueError('Project graph host changed')
    one(project.findall("Definitions/Definition[@File='smithing_voice/open_world.xml']"), 'project voice namespace definition')
    one(project.findall("Nodes/open_world[@Name='open_world']"), 'project voice namespace instance')
    wrapper_root = ET.fromstring(current[WRAPPER])
    host = one(list(wrapper_root.find('Skald')), 'project voice namespace wrapper')
    if host.tag != 'Gameplay' or host.get('Name') != 'open_world' or host.get('VoiceNamespace') != 'true':
        raise ValueError('Project voice namespace wrapper changed')
    with ExitStack() as stack:
        scripts = stack.enter_context(zipfile.ZipFile(target / 'Data/Scripts.pak'))
        gamedata = stack.enter_context(zipfile.ZipFile(target / 'Data/IPL_GameData.pak'))
        tables = stack.enter_context(zipfile.ZipFile(target / 'Data/Tables.pak'))
        native = native_contract(scripts, gamedata, tables)
    with EnglishRecordings(target) as bank:
        lines = recordings(bank.members, native['texts'])
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    if definitions is None or nodes is None:
        raise ValueError('Project voice namespace wrapper has no definitions or nodes')
    if not definitions.findall(f"Definition[@File='{DEFINITION}']"):
        ET.SubElement(definitions, 'Definition', File=DEFINITION)
    instances = nodes.findall(PARENT)
    if len(instances) > 1 or any(i.get('Name') != PARENT or len(i) for i in instances):
        raise ValueError('Existing player-state registration requires review')
    if not instances:
        ET.SubElement(nodes, PARENT, Name=PARENT)
    desired = {WRAPPER: xml(wrapper_root),
               FOLDER + PARENT + '.xml': container('Gameplay', PARENT, MODULE, MODULE + '.xml', 'true'),
               FOLDER + MODULE + '.xml': container('Module', MODULE, DIALOG, DIALOG + '.xml'),
               FOLDER + DIALOG + '.xml': native['dialog']}
    chain = voice_namespace({HOST: project_blob, **desired}, FOLDER + DIALOG + '.xml')
    if 'dialog/' + '/'.join(chain) + '/' != SCOPE:
        raise ValueError('Level barrier bark would resolve to another audio scope: ' + '/'.join(chain))
    changes = {p: b for p, b in desired.items() if current.get(p) != b}
    report = dict(version=VERSION, status='registered' if changes else 'present', host=HOST, wrapper=WRAPPER,
                  files=sorted(desired), native_dialog=NATIVE_DIALOG,
                  dialog_sha256=hashlib.sha256(native['dialog']).hexdigest(), surface=SURFACE,
                  barrier=native['barrier'], metarole=METAROLE, role=ROLE, player_rule=PLAYER_RULE,
                  voice_scope=SCOPE, lines=lines, voices=sorted({v for l in lines for v in l['voices']}),
                  changed=sorted(changes), runtime_verified=False)
    return changes, report


def upgrade(package, target, notify=lambda *a: None):
    """Idempotent: adds the registration once; a second run changes nothing."""
    if target is None:
        raise ValueError('Game folder required to register the level barrier bark')
    package = Path(package)
    changes, report = plan(package, target)
    if not changes:
        return {}, report
    label = 'Register the level barrier bark'
    notify(label, 0, 1, 'Native turn-back monolog under the project voice namespace')
    from setup_package_upgrade import rewrite
    rewrite(package, TRAVEL, changes)
    notify(label, 1, 1, ', '.join(sorted(changes)))
    from setup_campaign import digest
    return {TRAVEL: digest(package / TRAVEL)}, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True, help='installed or staged package')
    parser.add_argument('--game', type=Path, required=True, help='KCD2 folder')
    arguments = parser.parse_args()
    print(json.dumps(plan(arguments.mod, arguments.game)[1], indent=2))
