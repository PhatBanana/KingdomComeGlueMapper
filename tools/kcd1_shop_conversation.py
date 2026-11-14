"""Port KCD1's own shop conversation for the converted traders.

KCD1 traders got `addShopRoles_man/woman`: `SMLOUVANI_(MUZ|ZENA)` for the
haggle reactions in the shop screen, `VYJEDNAVANI_*` for negotiation and
`MERCHANT` for the "Let's talk trade." topic, and every NPC greeted through
`POZDRAV_(MUZ|ZENA)`. The live source closures (Tables.pak text tables; older
generations without English text or recordings are cut content):

- greeting 25570 (man) / 25697 (woman), branch type 2;
- farewell 15518 (man) / 15547 (woman), branch type 3 (`ROZLOUCENI_(MUZ|ZENA)`),
  the keeper's line after the talk screen closes; Henry says nothing;
- trade choice 22069, one type-9 sequence, prompt only;
- haggle 23469 (man) / 23605 (woman), trader and Henry lines.

KCD2's shop haggle dialogs (open_world/shop/bribe_haggle_.../smlouvani_v_obchode_*)
descend from the KCD1 haggle closures: their Decisions keep the KCD1 topic ids
and the same gvars, and their ExitScripts run the sale. The DLL finds them by
the SMLOUVANI metarole. So the haggle port keeps the KCD2 skeleton and changes
only the Response text ids it can map, plus the role name (a new role carrying
metarole SMLOUVANI, so exactly one haggle dialog binds to a keeper).

Mapping rule: a KCD1 sequence maps only inside the KCD2 Decision named after its
KCD1 topic and only to KCD2 sequences with the same entry condition. A KCD2
sequence whose own Response is silent and which opens a nested Decision lends
that Decision's base sequences (no VoiceCategory) as its line slots. Lines pair
in order and by speaker. A condition present in only one game is reported, and
the KCD1 lines are dropped and listed. Sean's rule (1 Nov 2026): KCD1 NPCs
keep their original lines and voices and nothing KCD1 lacked is ported, so
every KCD2 Response without a KCD1 counterpart is removed: no text, no audio.
Sequences, ports, scripts and OpenShop stay, so the sale logic is untouched;
the sequences that fall silent are reported. Step 1 (inventory) and step 2
(haggle mapping) live here; nothing is written to a package yet.
"""
from collections import defaultdict
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read

VERSION = 1
SEXES = ('man', 'woman')
WHITESPACE = b' \t\n\r'
GREETING = {'man': '25570', 'woman': '25697'}
FAREWELL = {'man': '15518', 'woman': '15547'}
HAGGLE = {'man': '23469', 'woman': '23605'}
TRADE = '22069'
# Speaker voices of the converted traders (KCD1 abbreviations, as imported).
VOICES = {'man': ('rpro', 'bcas', 'ccla', 'bdou', 'dsir', 'tzie', 'bbra', 'jcom', 'lhil', 'jhig1', 'kmic', 'sbar', 'ggud'),
          'woman': ('akem', 'aric', 'bvac', 'amil', 'jpres', 'bada', 'vhoga', 'sphe')}
HENRY_VOICE = 'tmck'
NATIVE_HAGGLE = {
    'man': 'Quests/Final/Barbora/open_world/shop/bribe_haggle_negotiation_vyjednavani_smlouvani_podplaceni/smlouvani_v_obchode_muz.xml',
    'woman': 'Quests/Final/Barbora/open_world/shop/bribe_haggle_negotiation_vyjednavani_smlouvani_podplaceni/smlouvani_v_obchode_zena_new.xml'}
NATIVE_ROLE = {'man': 'SMLOUVANI_MUZ', 'woman': 'SMLOUVANI_ZENA'}
PORTED_ROLE = {'man': 'GM_KCD1_SMLOUVANI_MUZ', 'woman': 'GM_KCD1_SMLOUVANI_ZENA'}
PORTED_NAME = {'man': 'gm_kcd1_smlouvani_muz', 'woman': 'gm_kcd1_smlouvani_zena'}
SOURCE_ROLE = {'man': 'SMLOUVANI_(MUZ)', 'woman': 'SMLOUVANI_(ZENA)'}
# Reviewed exceptions to the same-condition rule: (KCD2 Decision, KCD1 condition) -> KCD2 condition.
# 23528: KCD1's "No deal then." / "Forget it then." carried a KCD1-only condition;
# KCD2 kept the lines unconditioned in the same order (seq57/seq58).
CONDITION_OVERRIDES = {
    ('23528', "var('negotiation_result_canceled') == 0"): '',
    ('23528', "gvar('negotiation_merchantReaction_kind') == 4"): ''}
# 23479 low band: KCD1 "< 0.35" (priorities 0-1, before the mid band at 2-3) overlaps the
# mid band; it fired for every dominance below 0.35, which contains KCD2's tightened
# "< -0.35", so "Naturally." / "Sure, why not?" map onto KCD2's low band (Features, 1 Nov 2026).
MAP_LOW_DOMINANCE = True
LOW_DOMINANCE = ('23479', "gvar('negotiation_dominance') < 0.35", "gvar('negotiation_dominance') < -0.35")


def condition(text):
    """Comparable form of a dialogue entry condition in either game."""
    text = html.unescape(text or '').strip()
    return '' if text == '1' else re.sub(r'\s+', ' ', text)


def load_models(source):
    """KCD1 models of the greeting, farewell, trade and haggle closures, keyed by (part, sex)."""
    from campaign_dialogue import load_many
    keys = [(p, s) for p in ('greeting', 'farewell', 'haggle') for s in SEXES] + [('trade', None)]
    starts = [{'greeting': GREETING, 'farewell': FAREWELL, 'haggle': HAGGLE}[p][s] if s else TRADE for p, s in keys]
    return dict(zip(keys, load_many(source, [(None, start) for start in starts])))


def lines(model):
    """Every spoken source line: topic, sequence, condition, role name, string, voices."""
    roles = {r: row['role_name'] for r, row in model['roles'].items()}
    found = []
    for tid, topic in model['topics'].items():
        for sequence in topic['sequences']:
            for line in sequence['lines']:
                response = line['response']
                if response:
                    found.append(dict(topic=tid, sequence=sequence['source']['sequence_id'], order=len(found),
                                      condition=condition(sequence['entry'].get('entry_condition')),
                                      role=roles.get(response['role_id'], response['role_id']),
                                      string=response['string_name'], text=model['strings'].get(response['string_name']),
                                      voices={v['wave_file'].split('_', 1)[0]: v for v in line['voices']}))
    return found


def inventory(models, facial_stems=None):
    """Counts per closure: lines by role, texted lines, recordings and facial records per wanted voice."""
    report = {}
    for (part, sex), model in sorted(models.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        found = lines(model)
        wanted = (VOICES[sex] if sex else ()) + (HENRY_VOICE,)
        by_role = defaultdict(int)
        for line in found:
            by_role[line['role']] += 1
        voices = {}
        for voice in wanted:
            recorded = [l['voices'][voice]['wave_file'] for l in found if voice in l['voices']]
            entry = dict(recorded=len(recorded))
            if facial_stems is not None:
                entry['facial'] = sum(1 for stem in recorded if stem in facial_stems)
            voices[voice] = entry
        report[f'{part}_{sex}' if sex else part] = dict(
            start_topic=model['start_topic'], topics=len(model['topics']),
            sequence_types=sorted({s['source']['type'] for t in model['topics'].values() for s in t['sequences']}),
            lines=len(found), by_role=dict(by_role), texted=sum(1 for l in found if l['text']), voices=voices)
    return report


def slots(sequence, role):
    """Line slots of a KCD2 sequence for one speaker role, in document order.

    A speaker Response without Text in a sequence that opens no Decision is an
    empty slot (None): KCD2 kept the position but never wrote the line.
    """
    own = [r for r in sequence.findall('Elements/Response') if r.get('Role') == role and r.find('Text') is not None]
    if own:
        return own
    silent = all(r.find('Text') is None for r in sequence.findall('Elements/Response'))
    nested = sequence.findall('Decision')
    if silent and not nested and not sequence.get('VoiceCategory') and any(
            r.get('Role') == role for r in sequence.findall('Elements/Response')):
        return [None]
    if not silent or len(nested) != 1:
        return []
    found = []
    for child in nested[0].find('Sequences'):
        if child.get('VoiceCategory'):
            continue
        found.extend(r for r in child.findall('Elements/Response') if r.get('Role') == role and r.find('Text') is not None)
    return found


def topic_aliases(model, reference):
    """{topic of `model`: topic of `reference`} by walking both closures in parallel.

    KCD1's female haggle closure is a copy of the male one under new topic ids
    (with the stolen-goods lines inlined instead of behind a topic), while KCD2's
    female dialog keeps the male ids. Topics pair by start; within a pair,
    sequences of the same condition pair in order and their `next` topics pair
    where both continue. A topic pairing with two different topics is refused.
    """
    aliases, queue = {}, [(model['start_topic'], reference['start_topic'])]
    while queue:
        mine, theirs = queue.pop(0)
        if mine in aliases:
            if aliases[mine] != theirs:
                raise ValueError(f'Topic {mine} pairs with both {aliases[mine]} and {theirs}')
            continue
        aliases[mine] = theirs
        groups = [defaultdict(list), defaultdict(list)]
        for group, closure, topic in zip(groups, (model, reference), (mine, theirs)):
            for sequence in closure['topics'][topic]['sequences']:
                group[condition(sequence['entry'].get('entry_condition'))].append(sequence['source']['next'])
        for key, nexts in groups[0].items():
            for a, b in zip(nexts, groups[1].get(key, [])):
                if a != '0' and b != '0':
                    queue.append((a, b))
    return aliases


def brief(line):
    return dict(kcd1_topic=line['topic'], kcd1_sequence=line['sequence'], kcd1_role=line['role'],
                string=line['string'], text=line['text'])


def map_haggle(model, native, sex, aliases=None):
    """(ported dialog bytes, report) for one sex. `native` is the KCD2 skeleton's bytes.

    `aliases` maps source topics to the KCD1 topic ids the KCD2 Decisions are named after.
    """
    aliases = aliases or {}
    root = ET.fromstring(native)
    decisions = {d.get('Name'): d for d in root.iter('Decision')}
    source_role, native_role = SOURCE_ROLE[sex], NATIVE_ROLE[sex]
    by_topic = defaultdict(lambda: defaultdict(list))
    for line in lines(model):
        by_topic[aliases.get(line['topic'], line['topic'])][line['condition']].append(line)
    overrides = dict(CONDITION_OVERRIDES)
    if MAP_LOW_DOMINANCE:
        overrides[LOW_DOMINANCE[:2]] = LOW_DOMINANCE[2]
    applied = []
    for (decision, source_condition), target_condition in overrides.items():
        groups = by_topic.get(decision, {})
        if source_condition in groups:
            moved = groups.pop(source_condition)
            groups[target_condition] = sorted(groups.get(target_condition, []) + moved, key=lambda l: l['order'])
            applied.append(dict(decision=decision, kcd1=source_condition, kcd2=target_condition,
                                lines=[l['string'] for l in moved]))
    renames, pairs, dropped, mismatched = {}, [], [], []
    for topic, groups in sorted(by_topic.items(), key=lambda item: int(item[0])):
        decision = decisions.get(topic)
        if decision is None:
            dropped.extend(dict(reason='no_decision', **brief(l)) for g in groups.values() for l in g)
            continue
        native_groups = defaultdict(list)
        for sequence in decision.find('Sequences'):
            native_groups[condition(sequence.get('EntryCondition'))].append(sequence)
        only_source = sorted(set(groups) - set(native_groups))
        only_native = sorted(c for c in set(native_groups) - set(groups)
                             if any(slots(s, r) for s in native_groups[c] for r in (native_role, 'HRAC')))
        if only_source or only_native:
            mismatched.append(dict(decision=topic, kcd1=only_source, kcd2=only_native))
        for key in only_source:
            dropped.extend(dict(reason='condition_differs', **brief(l)) for l in groups[key])
        for key in sorted(set(groups) & set(native_groups)):
            for speaker, target in ((source_role, native_role), ('HENRY', 'HRAC')):
                wanted = [l for l in groups[key] if l['role'] == speaker]
                available = [slot for s in native_groups[key] for slot in slots(s, target)]
                for line, slot in zip(wanted, available):
                    if slot is None:
                        dropped.append(dict(reason='empty_kcd2_slot', **brief(line)))
                        continue
                    text = slot.find('Text')
                    renames[text.get('StringName')] = line['string']
                    pairs.append(dict(decision=topic, condition=key, role=target, native=text.get('StringName'),
                                      native_text=text.get('Text'), **brief(line)))
                dropped.extend(dict(reason='no_slot', **brief(l)) for l in wanted[len(available):])
    blob = native
    removed = [t.get('StringName') for r in root.iter('Response') for t in r.findall('Text')
               if t.get('StringName') not in renames]
    for old in removed:
        blob = remove_response(blob, old)
    for old, new in renames.items():
        token = f'StringName="{old}"'.encode()
        if blob.count(token) != 1:
            raise ValueError('KCD2 haggle string is not unique: ' + old)
        blob = blob.replace(token, f'StringName="{new}"'.encode())
    blob = re.sub(rb'\b' + native_role.encode() + rb'\b', PORTED_ROLE[sex].encode(), blob)
    name = root.find('Skald/FaderDialog').get('Name')
    blob = blob.replace(f'<FaderDialog Name="{name}"'.encode(), f'<FaderDialog Name="{PORTED_NAME[sex]}"'.encode(), 1)
    silent = silenced(root, set(removed))
    report = dict(sex=sex, kcd1_start=model['start_topic'], topic_aliases=aliases, native=NATIVE_HAGGLE[sex], name=PORTED_NAME[sex],
                  role=PORTED_ROLE[sex], condition_overrides=applied, mapped=len(pairs), dropped=len(dropped), removed=len(removed),
                  silenced=len(silent), player_choices_silenced=sum(1 for s in silent if s['player_choice']),
                  pairs=pairs, dropped_lines=dropped, condition_mismatches=mismatched, removed_responses=removed,
                  silenced_sequences=silent)
    return blob, report


def remove_response(blob, string):
    """Cut the one Response element carrying Text StringName `string`, with its leading whitespace."""
    token = f'StringName="{string}"'.encode()
    if blob.count(token) != 1:
        raise ValueError('KCD2 haggle string is not unique: ' + string)
    at = blob.index(token)
    start, end = blob.rfind(b'<Response ', 0, at), blob.find(b'</Response>', at)
    if start < 0 or end < 0 or b'<Response ' in blob[start + 1:at] or b'</Response>' in blob[start:at]:
        raise ValueError('Cannot isolate the KCD2 response of ' + string)
    end += len(b'</Response>')
    while start > 0 and blob[start - 1] in WHITESPACE:
        start -= 1
    return blob[:start] + blob[end:]


def silenced(root, removed):
    """KCD2 sequences that spoke and are silent after the removal, and whether the player picks them."""
    found = []
    for decision in root.iter('Decision'):
        for sequence in decision.find('Sequences'):
            texts = [t.get('StringName') for t in sequence.findall('Elements/Response/Text')]
            if texts and all(t in removed for t in texts):
                found.append(dict(decision=decision.get('Name'), sequence=sequence.get('Name'),
                                  end=sequence.get('EndType'), voice_category=sequence.get('VoiceCategory') or '',
                                  player_choice=sequence.find('UiPrompt') is not None or (
                                      decision.get('Autoselect') != 'true' and len(decision.find('Sequences')) > 1)))
    return found


def skeleton_differences(native, ported, sex, removed=()):
    """Every difference between the KCD2 skeleton and the port that the port is not allowed to make.

    Allowed: Response Text ids, the dialog name, the role name wherever it occurs
    (roles, voiceover and voice-category role lists, `dc[...]` in scripts), and
    the removal of the Responses whose KCD2 text ids are listed in `removed`.
    """
    def normalize(value):
        return re.sub(r'\b' + PORTED_ROLE[sex] + r'\b', NATIVE_ROLE[sex], value)
    problems = []

    def walk(a, b, path):
        if a.tag != b.tag:
            problems.append(f'{path}: tag {a.tag} != {b.tag}')
            return
        for key in sorted(set(a.attrib) | set(b.attrib)):
            left, right = a.get(key), b.get(key)
            if left == right:
                continue
            if a.tag == 'Text' and key == 'StringName' and path.endswith('/Response'):
                continue
            if a.tag == 'FaderDialog' and key == 'Name':
                continue
            if left is not None and right is not None and normalize(right) == left:
                continue
            problems.append(f'{path}/{a.tag}@{key}: {left!r} != {right!r}')
        if (a.text or '').strip() != (b.text or '').strip():
            problems.append(f'{path}/{a.tag}: text differs')
        if len(a) != len(b):
            problems.append(f'{path}/{a.tag}: {len(a)} children != {len(b)}')
            return
        for x, y in zip(a, b):
            walk(x, y, path + '/' + a.tag)
    reference = ET.fromstring(native)
    for elements in reference.iter('Elements'):
        for response in list(elements.findall('Response')):
            if any(t.get('StringName') in removed for t in response.findall('Text')):
                elements.remove(response)
    walk(reference, ET.fromstring(ported), '')
    return problems


# KCD1 greeting conditions call engine functions KCD2 dialogs do not have. They
# become ports wired to KCD2's own greeting state node (utils.greetings_utils
# timeandplayerstate), longest pattern first. A state KCD2 does not track is
# FALSE: none of the seven converted keepers is in KCD1's do-not-judge lists or
# carries the expectsDude tag, and KCD2 has no "looks knightly" state.
GREETING_ADAPTER = (
    ('GetActorAngriness()[1] > 0.2 & GetActorAngriness()[1] < 0.4', "Port('nastvanost__neklid')"),
    ('GetActorAngriness()[1] > 0.4 & GetActorAngriness()[1] < 0.7', "Port('nastvanost__neklid')"),
    ('GetActorAngriness()[1] > 0.65', "Port('nastvanost__neklid')"),
    ('GetActorAngriness()[1] > 0.5', "Port('nastvanost__neklid')"),
    ('GetActorAngriness()[1] < 0.25', "Port('nastvanost__klid')"),
    ('HourOfDay() > 6 & HourOfDay() < 10', "Port('je_rano')"),
    ('HourOfDay() > 12 & HourOfDay() < 17', "Port('je_odpoledne')"),
    ('HourOfDay() > 18 & HourOfDay() < 22', "Port('je_vecer')"),
    ("gvar('playerIsBleeding') == 1", "Port('hrac_je_zakrvaceny')"),
    ('greeting_reputation_5', "Port('reputace_dobra')"),
    ('greeting_reputation_4', "Port('reputace_dobra')"),
    ('greeting_reputation_3', "Port('reputace_stredni')"),
    ('greeting_reputation_2', "Port('reputace_nizka')"),
    ('greeting_reputation_1', "Port('reputace_nizka')"),
    ('greeting_looksPoor', "Port('hrac_je_spinavy')"),
    ('greeting_looksFancy', "Port('hrac_ma_alespon_vysoke_charisma')"),
    ('greeting_looksKnightly', 'FALSE'),
    ('greeting_do_not_judge_clothes_men', 'FALSE'),
    ('greeting_do_not_judge_clothes_women', 'FALSE'),
    ('expectsDude', 'FALSE'),
    # Farewell 15518's "why are you keeping me" pool: a KCD1 dialogue variable with no KCD2 counterpart.
    ("var('isUsed') == 0", 'FALSE'))
GREETING_SOURCE_ROLE = {'man': 'POZDRAV_(MUZ)', 'woman': 'POZDRAV_(ZENA)'}
GREETING_ROLE = {'man': 'GM_KCD1_POZDRAV_MUZ', 'woman': 'GM_KCD1_POZDRAV_ZENA'}
GREETING_NAME = {'man': 'gm_kcd1_pozdrav_muz', 'woman': 'gm_kcd1_pozdrav_zena'}
GREETED = 'uz_jsem_pozdravil'
COOLDOWN = 'nastav_cooldown'
# The only script in the KCD1 greeting closures: KCD2's once-a-day cooldown stands in for it.
METAROLE_SCRIPT = re.compile(r"dc\['POZDRAV_\((?:MUZ|ZENA)\)'\]\.soul:RemoveMetaRoleByName\('POZDRAV'\)")


def adapt_condition(text):
    """KCD2 condition for a KCD1 greeting condition ('' when always true); unknown terms are refused."""
    text = condition(text)
    if text == '0':
        return 'FALSE'
    for pattern, port in GREETING_ADAPTER:
        text = text.replace(pattern, port)
    rest = re.sub(r"Port\('[a-z_]+'\)|FALSE|[()!&| ]", '', text)
    if rest:
        raise ValueError('Unadapted KCD1 greeting condition: ' + rest)
    text = re.sub(r'\s+', ' ', text.replace('&', ' AND ').replace('|', ' OR ')).strip()
    return re.sub(r'\(\s+', '(', re.sub(r'\s+\)', ')', text))


def closure_writer(model, source_role, role, kind, used, emitted, lines_out, scripts, leaf_end=None):
    """topic(tid, parent): write a KCD1 closure from topic tid down as nested Autoselect Decisions.

    Every spoken line must be source_role's; it is written for role. Ports read by the
    adapted conditions go to `used`, written lines to `lines_out`, the sequences whose
    script is the POZDRAV metarole removal to `scripts` (any other script is refused).
    `leaf_end` sets the EndType of sequences that end the closure.
    """
    roles = {r: row['role_name'] for r, row in model['roles'].items()}

    def topic(tid, parent):
        emitted.add(tid)
        decision = ET.SubElement(parent, 'Decision', Name='t' + tid, Priority='General', Autoselect='true')
        sequences = ET.SubElement(decision, 'Sequences')
        records = model['topics'][tid]['sequences']
        # Overlapping conditions stay as KCD1 wrote them: specific variants (bleeding,
        # dirty, fancy) sit after the broad reputation branch, so KCD1 cannot have taken
        # the first valid sequence; Autoselect picks among the valid ones.
        for record in records:
            entry_condition = adapt_condition(record['entry'].get('entry_condition'))
            source = record['source']
            if source['script']:
                if not METAROLE_SCRIPT.fullmatch(source['script'].strip()):
                    raise ValueError(f'Unexpected KCD1 {kind} script in sequence ' + source['sequence_id'])
                scripts.append(source['sequence_id'])
            attrs = dict(Name='s' + source['sequence_id'])
            if entry_condition:
                attrs['EntryCondition'] = entry_condition
                used.update(re.findall(r"Port\('([a-z_]+)'\)", entry_condition))
            sequence = ET.SubElement(sequences, 'Sequence', attrs)
            elements = ET.SubElement(sequence, 'Elements')
            spoken = [l['response'] for l in record['lines'] if l['response']]
            for response in spoken:
                if roles.get(response['role_id']) != source_role:
                    raise ValueError(f'Unexpected KCD1 {kind} speaker: ' + str(roles.get(response['role_id'])))
                item = ET.SubElement(elements, 'Response', Role=role)
                ET.SubElement(item, 'Text', StringName=response['string_name'], Text=model['strings'][response['string_name']])
                lines_out.append(dict(topic=tid, sequence=source['sequence_id'], string=response['string_name']))
            if not spoken:
                ET.SubElement(elements, 'Response', Role=role)
            following = source['next']
            if following == '0':
                if leaf_end:
                    sequence.set('EndType', leaf_end)
                continue
            if following in emitted:
                sequence.set('EndType', 'GoTo')
                sequence.set('GoToDecision', 't' + following)
            else:
                sequence.set('EndType', 'Decision')
                topic(following, sequence)
    return topic


def emit_greeting(model, sex):
    """(KCD2 greeting Dialog bytes, report) for one KCD1 greeting closure."""
    source_role, role = GREETING_SOURCE_ROLE[sex], GREETING_ROLE[sex]
    database = ET.Element('Database', Name='brambora')
    dialog = ET.SubElement(ET.SubElement(database, 'Skald'), 'Dialog', Name=GREETING_NAME[sex])
    ports = ET.SubElement(dialog, 'Ports')
    body = ET.Element('Dialogue', Type='greeting', TechnicalStatus='Enabled')
    souls = ET.SubElement(body, 'SelectedSouls')
    ET.SubElement(souls, 'SelectedSoul', Role='HRAC')
    ET.SubElement(souls, 'SelectedSoul', Role=role)
    root_decision = ET.SubElement(body, 'Decision', Name='greeting', Priority='General')
    gate = ET.SubElement(ET.SubElement(root_decision, 'Sequences'), 'Sequence', Name='greet', EndType='Decision',
                         EntryCondition=f"!Port('{GREETED}')")
    ET.SubElement(ET.SubElement(gate, 'Triggers'), 'Port', Name=COOLDOWN)
    ET.SubElement(ET.SubElement(gate, 'Elements'), 'Response', Role='HRAC')
    used, emitted, lines_out, scripts = {GREETED}, set(), [], []
    topic = closure_writer(model, source_role, role, 'greeting', used, emitted, lines_out, scripts)
    start = model['topics'][model['start_topic']]['sequences']
    if len(start) != 1 or any(l['response'] for l in start[0]['lines']) or start[0]['source']['next'] == '0':
        raise ValueError('KCD1 greeting start topic changed')
    if start[0]['source']['script'].strip():
        if not METAROLE_SCRIPT.fullmatch(start[0]['source']['script'].strip()):
            raise ValueError('Unexpected KCD1 greeting start script')
        scripts.append(start[0]['source']['sequence_id'])
    topic(start[0]['source']['next'], gate)
    for name in sorted(used):
        ET.SubElement(ports, 'Port', Name=name, Direction='In', Type='bool')
    ET.SubElement(ports, 'Port', Name=COOLDOWN, Direction='Out', Type='trigger')
    dialog.append(body)
    from upgrade_map import xml
    unreachable = sorted({l['string'] for l in lines_out if not satisfiable(path_condition(body, 's' + l['sequence']))})
    report = dict(sex=sex, kcd1_start=model['start_topic'], name=GREETING_NAME[sex], role=role,
                  topics=len(emitted), lines=len(lines_out), ports=sorted(used - {GREETED}),
                  replaced_scripts=scripts, unreachable_lines=unreachable,
                  adapter={k: v for k, v in GREETING_ADAPTER})
    return xml(database), report


FAREWELL_SOURCE_ROLE = {'man': 'ROZLOUCENI_(MUZ)', 'woman': 'ROZLOUCENI_(ZENA)'}
FAREWELL_ROLE = {'man': 'GM_KCD1_ROZLOUCENI_MUZ', 'woman': 'GM_KCD1_ROZLOUCENI_ZENA'}
FAREWELL_NAME = {'man': 'gm_kcd1_rozlouceni_muz', 'woman': 'gm_kcd1_rozlouceni_zena'}
# After the shop closes, KCD2's ShopModule asks for a goodbye by purchase size through the hard-coded
# metaroles POZDRAV_PO_NAKUPU_ZADNY/BEZNY/VELKY (retail ending_po_ukonceni_shopu). KCD1 had one farewell
# for the end of every conversation, so each size gets the same KCD1 farewell, on its own role.
AFTER_SHOP = ('ZADNY', 'BEZNY', 'VELKY')
AFTER_SHOP_METAROLE = {kind: 'POZDRAV_PO_NAKUPU_' + kind for kind in AFTER_SHOP}
AFTER_SHOP_ROLE = {(sex, kind): f'GM_KCD1_LOUCENI_PO_NAKUPU_{kind}_{suffix}'
                   for sex, suffix in (('man', 'MUZ'), ('woman', 'ZENA')) for kind in AFTER_SHOP}
AFTER_SHOP_NAME = {(sex, kind): f'gm_kcd1_po_nakupu_{kind.lower()}_{suffix}'
                   for sex, suffix in (('man', 'muz'), ('woman', 'zena')) for kind in AFTER_SHOP}


def emit_farewell(model, sex, role=None, name=None, clash='Flavor'):
    """(KCD2 farewell Dialog bytes, report) for one KCD1 farewell closure.

    KCD1's farewell branch picks a pool by reputation band and the keeper says one
    of its lines; Henry is a silent participant. KCD2 plays the same moment as the
    NonPlayer monolog bound to a ROZLOUCENI role (ending_npc_se_louci_s_hracem__common_*),
    so the closure keeps that Dialogue shape and KCD1's own pools and lines. role/name
    give the post-purchase copies (AFTER_SHOP_*), which retail runs at ClashPriority OpenWorld.
    """
    role, name = role or FAREWELL_ROLE[sex], name or FAREWELL_NAME[sex]
    database = ET.Element('Database', Name='brambora')
    dialog = ET.SubElement(ET.SubElement(database, 'Skald'), 'Dialog', Name=name)
    ports = ET.SubElement(dialog, 'Ports')
    body = ET.Element('Dialogue', Type='ingame monolog', TechnicalStatus='Enabled', Initiator='NonPlayer',
                      ForceMood='noScope', ClashPriority=clash)
    used, emitted, lines_out, scripts = set(), set(), [], []
    start = model['topics'][model['start_topic']]['sequences']
    if not start or any(l['response'] for s in start for l in s['lines']) or any(s['source']['next'] == '0' for s in start):
        raise ValueError('KCD1 farewell start topic changed')
    closure_writer(model, FAREWELL_SOURCE_ROLE[sex], role, 'farewell', used, emitted, lines_out, scripts,
                   leaf_end='EndDialogue')(model['start_topic'], body)
    if scripts:
        raise ValueError('Unexpected KCD1 farewell scripts: ' + ', '.join(scripts))
    for name in sorted(used):
        ET.SubElement(ports, 'Port', Name=name, Direction='In', Type='bool')
    dialog.append(body)
    from upgrade_map import xml
    unreachable = sorted({l['string'] for l in lines_out if not satisfiable(path_condition(body, 's' + l['sequence']))})
    report = dict(sex=sex, kcd1_start=model['start_topic'], name=name, role=role,
                  topics=len(emitted), lines=len(lines_out), ports=sorted(used), unreachable_lines=unreachable)
    return xml(database), report


TRADE_ROLE = 'GM_KCD1_OBCHODNIK'
TRADE_NAME = 'gm_kcd1_obchod'


def emit_trade(model):
    """(KCD2 trade FaderDialog bytes, report) for KCD1's trade choice 22069.

    KCD1 offers one unvoiced choice, "Let's talk trade.", whose type-9 sequence
    opens the shop. The KCD2 form is the generated trade dialog's proven shape
    (Trade topic, OpenShop behind it, End dialog) bound to a role instead of a
    soul, with KCD1's prompt string and greetings allowed. There is no seller_in_shop
    gate, so it trades on and off the stall.
    """
    from region_travel_merchant import dialogue
    sequences = [s for t in model['topics'].values() for s in t['sequences']]
    if len(sequences) != 1 or sequences[0]['source']['type'] != '9' or any(l['response'] for l in sequences[0]['lines']):
        raise ValueError('KCD1 trade choice changed')
    prompt = sequences[0]['source']['ui_prompt']
    root = ET.fromstring(dialogue('', role=TRADE_ROLE, name=TRADE_NAME, trade_string=prompt, diagnostics=False))
    dialog = root.find('Skald/FaderDialog')
    dialog.remove(dialog.find('Ports'))
    body = dialog.find('Dialogue')
    # The engine plays the greeting and the ROZLOUCENI farewell only when the talk-screen dialog allows
    # them; KCD1 greeted and said farewell at the end of every conversation.
    body.set('AllowGreeting', 'true')
    body.set('AllowFarewell', 'true')
    for soul in body.iter('SelectedSoul'):
        soul.attrib.pop('Soul', None)
    for sequence in body.iter('Sequence'):
        triggers = sequence.find('Triggers')
        if triggers is not None:
            sequence.remove(triggers)
        for ui in sequence.findall('UiPrompt'):
            if ui.get('StringName') == prompt:
                ui.set('Text', model['strings'][prompt])
    from upgrade_map import xml
    return xml(root), dict(name=TRADE_NAME, role=TRADE_ROLE, kcd1_topic=model['start_topic'],
                           kcd1_sequence=sequences[0]['source']['sequence_id'], prompt=prompt, text=model['strings'][prompt])


def path_condition(body, name):
    """Conjunction of the entry conditions from the greeting root down to sequence `name`."""
    parents = {child: parent for parent in body.iter() for child in parent}
    node = next(s for s in body.iter('Sequence') if s.get('Name') == name)
    parts = []
    while node is not None:
        if node.tag == 'Sequence' and node.get('EntryCondition'):
            parts.append(f"({node.get('EntryCondition')})")
        node = parents.get(node)
    return ' AND '.join(reversed(parts))


def satisfiable(expression):
    """Whether some assignment of the ports makes a greeting condition true (ports are independent)."""
    ports = sorted(set(re.findall(r"Port\('([a-z_]+)'\)", expression)))
    python = expression.replace('FALSE', 'False').replace(' AND ', ' and ').replace(' OR ', ' or ').replace('!', ' not ')
    python = re.sub(r"Port\('([a-z_]+)'\)", r'p["\1"]', python)
    for mask in range(1 << len(ports)):
        if eval(python or 'True', {}, {'p': {port: bool(mask >> i & 1) for i, port in enumerate(ports)}}):
            return True
    return False


def facial_stems(source, target):
    """Stems that carry a KCD1 facial record."""
    from dialogue_facials import FacialImporter
    importer = FacialImporter(source, target)
    try:
        return set(importer.source_headers)
    finally:
        importer.close()


def plan_haggle(source, target, facials=False):
    """Read-only step 1 and 2 report, and the ported dialog bytes for both sexes."""
    models = load_models(source)
    with zipfile.ZipFile(Path(target) / 'Data/Scripts.pak') as scripts:
        natives = {sex: read(scripts, NATIVE_HAGGLE[sex]) for sex in SEXES}
    ported, reports = {}, {}
    aliases = {'man': None, 'woman': topic_aliases(models[('haggle', 'woman')], models[('haggle', 'man')])}
    for sex in SEXES:
        blob, report = map_haggle(models[('haggle', sex)], natives[sex], sex, aliases[sex])
        report['skeleton_differences'] = skeleton_differences(natives[sex], blob, sex, report['removed_responses'])
        ported[sex], reports[sex] = blob, report
    stems = facial_stems(source, target) if facials else None
    return ported, dict(version=VERSION, inventory=inventory(models, stems), haggle=reports, runtime_verified=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='KCD1 folder')
    parser.add_argument('--game', type=Path, required=True, help='KCD2 folder')
    parser.add_argument('--out', type=Path, help='write the report and ported dialogs here')
    parser.add_argument('--facials', action='store_true', help='also count KCD1 facial records (slow)')
    arguments = parser.parse_args()
    ported, report = plan_haggle(arguments.source, arguments.game, arguments.facials)
    if arguments.out:
        arguments.out.mkdir(parents=True, exist_ok=True)
        (arguments.out / 'haggle-map.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        for sex, blob in ported.items():
            (arguments.out / f'{PORTED_NAME[sex]}.xml').write_bytes(blob)
    print(json.dumps({sex: {k: v for k, v in r.items() if k in ('mapped', 'dropped', 'removed', 'silenced', 'player_choices_silenced')}
                      for sex, r in report['haggle'].items()}, indent=2))
