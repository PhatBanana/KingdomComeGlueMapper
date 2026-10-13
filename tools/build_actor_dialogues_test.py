"""Stage ordinary source conversations for registered actors and a native quest container."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_actor_dialogues import register_roles, remap_roles
from campaign_dependency_adapters import SourceTables
from campaign_sources import RetailSourceReader
from campaign_dialogue import load, emit, voices
from campaign_dialogue_selection import SelectionCompiler, load_contract
from campaign_dialogue_runtime import attach_dialogue, bind_recordings
from dialogue_dubbing import DEPOT, dubbing_index, bind_soul_voice
from build_english_audio_test import merge_audio_strings
from build_horse_trader_test import rewrite, digest
from world_item_definitions import native_items, native_item_registry
from upgrade_map import read, xml


def actor_voice_bindings(bindings, mapping, reports):
    """Resolve runtime speakers from source role membership and recorded voices.

    SelectedSouls alone does not register an imported soul's Skald character.
    Reject conflicting recordings instead of assigning whichever branch ran last.
    """
    voices = {}
    for report in reports:
        for role, voice in report['binding']['roles'].items():
            if role in voices and voices[role] != voice:
                raise ValueError('Conflicting recorded voice for role: ' + role)
            voices[role] = voice
    result = {}
    for soul, roles in bindings.items():
        speakers = [(mapping[r['role_name']], voices[mapping[r['role_name']]])
                    for r in roles if mapping[r['role_name']] in voices]
        if not speakers:
            continue
        if len({v['voice_id'] for _, v in speakers}) != 1:
            raise ValueError('Conflicting recorded voices for soul: ' + soul)
        result[soul] = dict(role=speakers[0][0], voice=speakers[0][1])
    return result


def actor_ui_name(resources, soul_name):
    """Reuse the imported identity's name instead of clearing it for dubbing."""
    names = set()
    for path, blob in resources.items():
        if not path.startswith('Libs/Storm/names/') or not path.endswith('.xml'):
            continue
        for rule in ET.fromstring(blob).findall('./rules/rule'):
            selectors = rule.findall('./selectors/*')
            if len(selectors) != 1 or selectors[0].tag != 'hasName' or selectors[0].get('name') != soul_name:
                continue
            names.update(n.get('name') for n in rule.findall('./operations/setUiName') if n.get('name'))
    if len(names) != 1:
        raise ValueError('Missing or ambiguous imported speaker display name: ' + soul_name)
    return names.pop()


def build(a):
    if a.output.exists():
        raise FileExistsError('Choose a fresh dialogue stage')
    travel = a.mod / 'Data/gluemappertravel.pak'
    audio = a.mod / 'Localization/English.pak'
    locale = a.mod / 'Localization/English_xml.pak'
    with zipfile.ZipFile(travel) as z:
        resources = {n:read(z, n) for n in z.namelist() if n.startswith(('Libs/', 'Quests/'))}
    files = {n.removeprefix('Quests/'):b for n,b in resources.items() if n.startswith('Quests/')}
    souls = {}
    for n,b in resources.items():
        if n.lower().startswith('libs/tables/rpg/soul') and n.endswith('.xml'):
            for s in ET.fromstring(b).iter('soul'):
                souls[s.get('soul_id')] = s.get('soul_name')
    item_tables = []
    for pak in sorted((a.mod / 'Data').glob('*.pak')):
        with zipfile.ZipFile(pak) as z:
            item_tables.extend(read(z,n) for n in z.namelist()
                if n.lower().startswith('libs/tables/item/item__') and n.endswith('.xml'))
    items = native_item_registry(native_items(a.target, item_tables))
    models = {topic:load(a.source, start_topic=topic) for topic in a.start_topic}
    needed = {p['role_id'] for m in models.values() for p in m['participants'] if p['topic_id'] in m['topics']}
    with RetailSourceReader(a.source) as reader:
        tables = SourceTables(a.source, reader)
        roles = {r['role_id']:r for r in tables.get('rpg/role')['rows']}
        meta = {r['metarole_id']:r['metarole_name'] for r in tables.get('rpg/metarole')['rows']}
        needed = {r for r in needed if meta[roles[r]['metarole_id']] == 'NPC'}
        bindings = {}
        for r in tables.get('rpg/soul2role')['rows']:
            if r['role_id'] in needed and r['soul_id'] in souls:
                bindings.setdefault(r['soul_id'], []).append(dict(roles[r['role_id']], metarole_name='NPC'))
    bound = {r['role_id'] for rs in bindings.values() for r in rs}
    if needed - bound:
        raise ValueError('Conversation actors need importing for roles: ' + ', '.join(sorted(needed - bound)))
    with zipfile.ZipFile(a.target / 'Data/Tables.pak') as z:
        native_roles = [r.attrib for r in ET.fromstring(read(z, 'Libs/Tables/rpg/role.xml')).iter('role')]
        native_voices = read(z, 'Libs/Tables/skald/voice.xml')
    resources, mapping = register_roles(resources, bindings, souls, native_roles, a.namespace)
    contract = load_contract(a.source, a.target, dict(p.split('=',1) for p in a.skill_upgrade))
    contract['preserve_reputation_caps'] = True
    selection = SelectionCompiler(**contract)
    quests = [json.loads(p.read_text(encoding='utf-8')) for p in a.quest_ir]
    with zipfile.ZipFile(audio) as z:
        depot = read(z, DEPOT)
    with zipfile.ZipFile(locale) as z:
        strings_blob = read(z, 'text_ui_dialog.xml')
    recordings, reports = {}, []
    for topic, model in models.items():
        model = remap_roles(model, mapping)
        name = a.namespace + '_' + topic
        blob, report = emit(model, name, quests, selection_compiler=selection, registered_items=items,
                            participant_assets=dict(p.split('=',1) for p in a.participant_asset))
        media, voice_report = voices(a.source, model, name)
        blob, bound_media, binding_report = bind_recordings(blob, model, media, native_voices)
        files = attach_dialogue(files, a.container_name, blob, report, a.activation, a.container)
        recordings.update(bound_media)
        strings = ET.Element('Table')
        for key, value in sorted(model['strings'].items()):
            row = ET.SubElement(strings, 'Row')
            for text in (key, value, value): ET.SubElement(row, 'Cell').text = text
        strings_blob = merge_audio_strings(strings_blob, xml(strings))
        reports.append(dict(topic=topic, conversion=report, voices=voice_report, binding=binding_report))
    voice_receipts = []
    modid = ET.parse(a.mod / 'mod.manifest').findtext('info/modid')
    for soul, speaker in actor_voice_bindings(bindings, mapping, reports).items():
        matches = [r for n,b in resources.items() if n.startswith('Libs/Tables/rpg/soul__')
                   for r in ET.fromstring(b).iter('soul') if r.get('soul_id') == soul]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous imported speaker soul: ' + soul)
        character = matches[0].get('skald_character_name')
        current = [r for n,b in resources.items() if n.startswith('Libs/Tables/skald/skald_character__')
                   for r in ET.fromstring(b).iter('skald_character')
                   if r.get('skald_character_name') == character]
        if len(current) > 1:
            raise ValueError('Ambiguous imported speaker character: ' + str(character))
        # Retain the actor's established master role and display name when adding
        # ordinary conversations to an actor already used by an opening scene.
        role = current[0].get('master_role_name', speaker['role']) if current else speaker['role']
        ui = (current[0].get('ui_name_string_name') if current else None) or actor_ui_name(resources, souls[soul])
        resources, receipt = bind_soul_voice(resources, a.target, modid, souls[soul],
            speaker['voice']['voice_technical_name'], role, ui)
        voice_receipts.append(receipt)
    depot, dubbing = dubbing_index(a.target, recordings, depot)
    resources.update(selection.resources())
    resources.update({'Quests/' + n:b for n,b in files.items()})
    package = a.output / 'package'
    rewrite(travel, package / 'Data/gluemappertravel.pak', resources)
    rewrite(audio, package / 'Localization/English.pak', dict(recordings, **{DEPOT:depot}))
    rewrite(locale, package / 'Localization/English_xml.pak', {'text_ui_dialog.xml':strings_blob})
    report = dict(conversations=reports, roles=mapping, dubbing=dubbing, actor_voices=voice_receipts,
        baseline={str(p):digest(p) for p in (travel,audio,locale)},
        installed=False, runtime_verified=False,
        files={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*.pak')})
    (a.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return dict(conversations=len(models), recordings=len(recordings), installed=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('source', 'target', 'mod', 'output'):
        p.add_argument('--' + n, type=Path, required=True)
    p.add_argument('--quest-ir', action='append', type=Path, required=True)
    p.add_argument('--start-topic', action='append', required=True)
    p.add_argument('--namespace', required=True)
    p.add_argument('--container', required=True, help='Definition path relative to Quests/')
    p.add_argument('--container-name', required=True)
    p.add_argument('--activation', required=True)
    p.add_argument('--skill-upgrade', action='append', default=[])
    p.add_argument('--participant-asset', action='append', default=[], help='Source inventory selector=registered container soul asset')
    print(json.dumps(build(p.parse_args()), indent=2))
