"""Give imported KCD1 voices a native fallback voice for shared native lines.

`dialogue_dubbing.import_source_voices` registers each KCD1 voice that a
converted speaker needs as a synthetic KCD2 voice (`voice_id` 100000 + the
KCD1 id, `gm_source_<abbreviation>`) so the speaker's own converted recordings
play under its original actor. Native open-world speech (shop, greetings,
farewells, reactions) is recorded per native voice and looked up as
`<abbreviation>_<text id>.ogg`; a synthetic voice has no such files. Retail
covers exactly this with `fallback_voice_id`: all 91 recorded retail voices
name another voice to use when their own recording is missing
(Libs/Tables/skald/voice.xml; WHGame.dll reads the column and exposes the
`wh_dlg_EnableFallbackVoice` cvar). The imported rows carried none, so a
converted trader on a KCD1-only voice traded in silence (ska_merchant1, 29 Oct
2026) while one bound to a native voice (ska_merchant2) spoke.

The fallback follows retail's own pattern instead of a hand-picked actor: a
native voice of the same sex at `fallback_voice_level` 2 (the voices that
retail's level 0 and 1 voices fall back to, and which themselves fall back
only to the two placeholder roots), cast for Czech merchants (`voice_groups`
holds Czechs and Merchants), with recordings in the native shop, greeting and
farewell folders, ranked by how many retail voices already fall back to it and
then by shop recordings. Sex comes from the Skald characters bound to a voice
(`gender` 0 = male, 1 = female, as the generic commoner templates show). Only
the voices of the souls in SCOPE are changed; every converted shopkeeper is
reported with its voice, native coverage and the fallback it has or would get.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from audio_mapping import EnglishRecordings
from shop_roles import keepers
from upgrade_map import read, xml

VERSION = 1
TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'Data/Levels/kcd1_travel/level.pak'
NATIVE_VOICES = 'Libs/Tables/skald/voice.xml'
NATIVE_CHARACTERS = 'Libs/Tables/skald/skald_character.xml'
# Souls whose imported voice receives the fallback now; the rest are reported.
# ska_merchant4 joined when native_shop_dialogue gave her the native shop greeting
# (the collier, on rpro's fallback, was heard speaking on 31 Oct 2026).
SCOPE = ('ska_merchant1', 'ska_merchant4')
COMPLETE_LEVEL = '2'
REQUIRED_GROUPS = frozenset(('Czechs', 'Merchants'))
FOLDERS = {'shop': 'shop', 'greetings': 'pozdravy_na_zacatku_dialogu', 'farewells': 'rozlouceni_na_konci_dialogu'}
NATIVE_SCOPE = 'dialog/open_world/'
SEX = {'0': 'man', '1': 'woman'}


def coverage(members):
    """Recordings per voice abbreviation under the native shop, greeting and farewell folders.

    Shop and farewell lines sit directly in their folder; the greetings live one
    level down in nested voice-namespace modules, so count at any depth.
    """
    counts = defaultdict(lambda: dict.fromkeys(FOLDERS, 0))
    prefixes = {NATIVE_SCOPE + folder + '/': key for key, folder in FOLDERS.items()}
    for name in members:
        for prefix, key in prefixes.items():
            if name.startswith(prefix):
                counts[name.rsplit('/', 1)[-1].split('_', 1)[0]][key] += 1
    return counts


def sexes(characters):
    """Sex of each voice from the characters bound to it; a mixed voice gets None."""
    seen = defaultdict(set)
    for row in characters.iter('skald_character'):
        if row.get('voice_id') and row.get('gender') in SEX:
            seen[row.get('voice_id')].add(SEX[row.get('gender')])
    return {voice: next(iter(found)) if len(found) == 1 else None for voice, found in seen.items()}


def candidates(voices, voice_sexes, counts):
    """Native voices that can stand in for an imported one, best first, per sex."""
    rows = list(voices.iter('voice'))
    referenced = Counter(v.get('fallback_voice_id') for v in rows if v.get('fallback_voice_id'))
    result = defaultdict(list)
    for voice in rows:
        groups = set(filter(None, (voice.get('voice_groups') or '').split(';')))
        sex = voice_sexes.get(voice.get('voice_id'))
        recorded = counts.get(voice.get('abbreviation'))
        if voice.get('fallback_voice_level') != COMPLETE_LEVEL or not REQUIRED_GROUPS <= groups or sex is None:
            continue
        if not recorded or not all(recorded.values()):
            continue
        result[sex].append(dict(voice=voice.get('abbreviation'), voice_id=int(voice.get('voice_id')),
                                technical_name=voice.get('voice_technical_name'),
                                referenced_by=referenced[voice.get('voice_id')], recordings=dict(recorded),
                                groups=sorted(groups)))
    for sex in result:
        result[sex].sort(key=lambda c: (-c['referenced_by'], -c['recordings']['shop'], c['voice']))
    return dict(result)


def bindings(travel):
    """Converted souls, their Skald characters and the imported voice rows of a package."""
    souls, characters, patches, imported = {}, defaultdict(set), {}, {}
    for name in travel.namelist():
        if name.startswith('Libs/Tables/rpg/soul__'):
            for soul in ET.fromstring(read(travel, name)).iter('soul'):
                souls[soul.get('soul_name')] = soul.get('skald_character_name')
        elif name.startswith('Libs/Tables/skald/skald_character__'):
            for row in ET.fromstring(read(travel, name)).iter('skald_character'):
                characters[row.get('skald_character_name')].add((row.get('voice_id'), row.get('gender')))
        elif name.startswith('Libs/Tables/skald/voice__'):
            root = ET.fromstring(read(travel, name))
            patches[name] = root
            for voice in root.iter('voice'):
                if voice.get('voice_id') in imported:
                    raise ValueError('Duplicate imported voice identity: ' + str(voice.get('voice_id')))
                imported[voice.get('voice_id')] = (name, voice)
    return souls, characters, patches, imported


def summary(row, counts):
    return dict(voice=row.get('abbreviation'), voice_id=int(row.get('voice_id')),
                recordings=dict(counts.get(row.get('abbreviation'), dict.fromkeys(FOLDERS, 0))))


def plan(package, target):
    """Return (travel replacements, report) without writing to either folder."""
    package, target = Path(package), Path(target)
    with zipfile.ZipFile(package / LEVEL) as level:
        people = keepers(read(level, 'objects_mission0.xml'))
    with zipfile.ZipFile(package / TRAVEL) as travel:
        souls, characters, patches, imported = bindings(travel)
    with zipfile.ZipFile(target / 'Data/Tables.pak') as tables:
        voices = ET.fromstring(read(tables, NATIVE_VOICES))
        native_characters = ET.fromstring(read(tables, NATIVE_CHARACTERS))
    native = {v.get('voice_id'): v for v in voices.iter('voice')}
    for row in native_characters.iter('skald_character'):
        characters[row.get('skald_character_name')].add((row.get('voice_id'), row.get('gender')))
    with EnglishRecordings(target) as bank:
        counts = coverage(bank.members)
    options = candidates(voices, sexes(native_characters), counts)

    def resolve(person):
        """(character, voice id, sexes) of a converted person, or the reason it has none."""
        character = souls.get(person)
        if character is None:
            return None, 'no_soul'
        rows = characters.get(character, set())
        ids = {voice for voice, _ in rows}
        if len(ids) != 1:
            return None, 'no_character' if not rows else 'ambiguous_character_voice'
        found = {SEX.get(gender) for _, gender in rows} - {None}
        if person in people:
            found.add(people[person])
        return dict(character=character, voice_id=next(iter(ids)), sexes=found), None

    users = defaultdict(set)
    for person in souls:
        info, reason = resolve(person)
        if not reason and info['voice_id'] in imported:
            users[info['voice_id']].add(person)
    selected, scope = {}, []
    for person in SCOPE:
        info, reason = resolve(person)
        if reason:
            scope.append(dict(person=person, outcome=reason))
        elif info['voice_id'] in imported:
            selected[info['voice_id']] = person
            scope.append(dict(person=person, outcome='imported_voice', voice=imported[info['voice_id']][1].get('abbreviation')))
        else:
            scope.append(dict(person=person, outcome='native_voice'))
    status, touched, voice_reports = {}, set(), []
    for voice_id, (path, row) in sorted(imported.items(), key=lambda item: int(item[0])):
        found = set()
        for person in users[voice_id]:
            found |= resolve(person)[0]['sexes']
        sex = next(iter(found)) if len(found) == 1 else None
        choice = (options.get(sex) or [None])[0] if sex else None
        existing = row.get('fallback_voice_id')
        if voice_id not in selected:
            state = 'candidate' if choice else ('sex_unresolved' if sex is None else 'no_candidate')
        elif choice is None:
            raise ValueError('No native fallback voice for imported voice ' + str(row.get('abbreviation')))
        elif existing is None:
            row.set('fallback_voice_id', str(choice['voice_id']))
            touched.add(path)
            state = 'applied'
        elif existing == str(choice['voice_id']):
            state = 'present'
        else:
            state = 'kept'
        status[voice_id] = state
        voice_reports.append(dict(voice=row.get('abbreviation'), voice_id=int(voice_id), sex=sex,
                                  used_by=sorted(users[voice_id]), in_scope=voice_id in selected,
                                  fallback=None if choice is None else dict(voice=choice['voice'], voice_id=choice['voice_id'],
                                                                             recordings=choice['recordings']),
                                  existing_fallback=None if existing is None else int(existing), status=state))
    keeper_reports = []
    for person, sex in sorted(people.items()):
        info, reason = resolve(person)
        if reason:
            keeper_reports.append(dict(person=person, sex=sex, status=reason))
            continue
        voice_id = info['voice_id']
        if voice_id in imported:
            row, kind, state = imported[voice_id][1], 'imported', status[voice_id]
        elif voice_id in native:
            row, kind, state = native[voice_id], 'native', 'native_voice'
        else:
            keeper_reports.append(dict(person=person, sex=sex, character=info['character'], voice_id=int(voice_id), status='unknown_voice'))
            continue
        fallback = native.get(row.get('fallback_voice_id'))
        if fallback is None and row.get('fallback_voice_id') in imported:
            fallback = imported[row.get('fallback_voice_id')][1]
        keeper_reports.append(dict(person=person, sex=sex, character=info['character'], kind=kind, **summary(row, counts),
                                   fallback=None if fallback is None else summary(fallback, counts), status=state))
    changes = {path: xml(patches[path]) for path in sorted(touched)}
    report = dict(version=VERSION, scope=scope,
                  rule=dict(fallback_voice_level=COMPLETE_LEVEL, voice_groups=sorted(REQUIRED_GROUPS), folders=dict(FOLDERS),
                            ranking=['retail voices falling back to it', 'shop recordings', 'abbreviation']),
                  candidates={sex: rows[:3] for sex, rows in sorted(options.items())},
                  voices=voice_reports, keepers=keeper_reports, changed=sorted(changes), runtime_verified=False)
    return changes, report


def upgrade(package, target, notify=lambda *a: None):
    """Idempotent: writes a fallback once; a second run changes nothing."""
    if target is None:
        raise ValueError('Game folder required to choose native fallback voices')
    package = Path(package)
    changes, report = plan(package, target)
    if not changes:
        return {}, report
    label = 'Give imported voices a native fallback'
    applied = [v for v in report['voices'] if v['status'] == 'applied']
    notify(label, 0, 1, ', '.join(f"{v['voice']} -> {v['fallback']['voice']}" for v in applied))
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
