"""KCD1 haggle lines map onto KCD2's haggle skeleton by Decision and condition only."""
from pathlib import Path
import sys
import re
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import kcd1_shop_conversation
from kcd1_shop_conversation import (GREETING_ROLE, PORTED_NAME, PORTED_ROLE, adapt_condition, emit_greeting, emit_trade, inventory,
                                    map_haggle, satisfiable, skeleton_differences, topic_aliases)

ROLES = {'1': {'role_name': 'HENRY'}, '2': {'role_name': 'SMLOUVANI_(MUZ)'}, '3': {'role_name': 'SMLOUVANI_(ZENA)'}}


def sequence(sid, cond, nxt, speaker=None, string=None, voices=('rpro', 'bcas')):
    lines = []
    if string:
        lines.append(dict(source={}, response=dict(role_id=speaker, string_name=string), commands=[], flowcharts=[],
                          voices=[dict(wave_file=f'{v}_{string}', path='1') for v in voices]))
    return dict(source=dict(sequence_id=sid, next=nxt, type='0'), entry=dict(entry_condition=cond), lines=lines)


def model(start, topics, strings=None):
    return dict(start_topic=start, roles=ROLES, strings=strings or {},
                topics={tid: dict(source={}, sequences=seqs) for tid, seqs in topics.items()})


HAGGLE_MAN = model('100', {
    '100': [sequence('1', '1', '110')],
    '110': [sequence('2', "gvar('d') == 0", '120', '1', 't110_henry_a', voices=('tmck',)),
            sequence('3', "gvar('d') == 0", '120', '1', 't110_henry_b', voices=('tmck',)),
            sequence('4', "gvar('d') == 2", '130')],
    '120': [sequence('5', "gvar('dom') < 0.35", '0', '2', 't120_low_a'),
            sequence('6', "gvar('dom') >= 0.35", '0', '2', 't120_high_a'),
            sequence('7', "gvar('dom') >= 0.35", '0', '2', 't120_high_b')],
    '130': [sequence('8', '', '0', '2', 't130_stolen_a')]},
    strings={'t110_henry_a': 'Price?', 't120_high_a': 'We can try.'})

SKELETON = '''﻿<?xml version="1.0" encoding="utf-8"?>
<Database Name="brambora">
\t<Skald>
\t\t<FaderDialog Name="smlouvani_v_obchode_muz" Time="ANYTIME">
\t\t\t<Dialogue AllowFarewell="false">
\t\t\t\t<SelectedSouls><SelectedSoul Role="HRAC" Voice="tomMcKay" /><SelectedSoul Role="SMLOUVANI_MUZ" Voice="juergenStraub" /></SelectedSouls>
\t\t\t\t<Decision Name="100" Autoselect="true"><Sequences><Sequence EndType="Decision" Name="seq1"><Elements><Response Role="HRAC" /></Elements>
\t\t\t\t<Decision Name="110" Autoselect="true"><Sequences>
\t\t\t\t\t<Sequence EntryCondition="gvar('d') == 0" EndType="GoTo" GoToDecision="120" Name="s2"><Elements><Response Role="HRAC"><Text StringName="smlo_henry_a" Text="Cena?" /></Response></Elements></Sequence>
\t\t\t\t\t<Sequence EntryCondition="gvar('d') == 0" EndType="GoTo" GoToDecision="120" Name="s3"><Elements><Response Role="HRAC"><Text StringName="smlo_henry_b" Text="Cena!" /></Response></Elements></Sequence>
\t\t\t\t\t<Sequence EntryCondition="gvar('d') == 2" EndType="Decision" Name="s4" ExitScript="local merchant = dc['SMLOUVANI_MUZ']&#xD;&#xA;Shops.CancelTransaction(merchant.id)"><Elements><Response Role="SMLOUVANI_MUZ" /></Elements>
\t\t\t\t\t\t<Decision Name="130" Autoselect="true" VoiceoverReductionMaxSequences="2" VoiceoverReductionRole="SMLOUVANI_MUZ"><Sequences>
\t\t\t\t\t\t\t<Sequence EndType="EndDialogue" Name="s8"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_stolen_a" Text="Kradene." /></Response></Elements></Sequence>
\t\t\t\t\t\t\t<Sequence EndType="EndDialogue" Name="s9"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_stolen_b" Text="Kradene!" /></Response></Elements></Sequence>
\t\t\t\t\t\t</Sequences></Decision></Sequence>
\t\t\t\t\t<Sequence EntryCondition="gvar('d') == 3" EndType="EndDialogue" Name="s10"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_own_goods" Text="Moje veci?" /></Response></Elements></Sequence>
\t\t\t\t</Sequences></Decision>
\t\t\t\t<Decision Name="120" Autoselect="true"><Sequences>
\t\t\t\t\t<Sequence EntryCondition="gvar('dom') &lt; -0.35" EndType="EndDialogue" Name="s5"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_low_a" Text="Jiste." /></Response></Elements></Sequence>
\t\t\t\t\t<Sequence EntryCondition="gvar('dom') &gt;= 0.35" EndType="Decision" Name="s6"><Elements><Response Role="SMLOUVANI_MUZ" /></Elements>
\t\t\t\t\t\t<Decision Name="dec5" Autoselect="true" VoiceoverReductionMaxSequences="2" VoiceoverReductionRole="SMLOUVANI_MUZ"><Sequences>
\t\t\t\t\t\t\t<Sequence EndType="EndDialogue" Name="s61"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_high_a" Text="Zkusime." /></Response></Elements></Sequence>
\t\t\t\t\t\t\t<Sequence EndType="EndDialogue" Name="german01" VoiceCategory="german" VoiceCategoryRoles="SMLOUVANI_MUZ"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_high_de" Text="Gut." /></Response></Elements></Sequence>
\t\t\t\t\t\t\t<Sequence EndType="EndDialogue" Name="s62"><Elements><Response Role="SMLOUVANI_MUZ"><Text StringName="smlo_high_b" Text="Tak jo." /></Response></Elements></Sequence>
\t\t\t\t\t\t</Sequences></Decision></Sequence>
\t\t\t\t</Sequences></Decision>
\t\t\t\t</Sequence></Sequences></Decision>
\t\t\t</Dialogue>
\t\t</FaderDialog>
\t</Skald>
</Database>'''.encode('utf-8')


class HaggleMappingTests(unittest.TestCase):
    def setUp(self):
        self.ported, self.report = map_haggle(HAGGLE_MAN, SKELETON, 'man')
        self.root = ET.fromstring(self.ported)

    def strings(self):
        return {r.get('Name'): [t.get('StringName') for t in r.findall('Elements/Response/Text')] for r in self.root.iter('Sequence')}

    def test_lines_pair_in_order_within_the_same_decision_and_condition(self):
        strings = self.strings()
        self.assertEqual((strings['s2'], strings['s3']), (['t110_henry_a'], ['t110_henry_b']))
        # Silent sequence opening a nested Decision: its base sequences are the slots; voice categories are not.
        self.assertEqual((strings['s61'], strings['s62'], strings['german01']), (['t120_high_a'], ['t120_high_b'], []))
        # The stolen-goods topic maps through its own Decision; the unmatched second slot loses its KCD2 line.
        self.assertEqual((strings['s8'], strings['s9']), (['t130_stolen_a'], []))
        self.assertEqual(self.report['mapped'], 5)

    def test_a_condition_that_differs_drops_the_kcd1_line_and_silences_the_kcd2_line(self):
        self.assertEqual(self.strings()['s5'], [])
        self.assertEqual([(d['reason'], d['string']) for d in self.report['dropped_lines']], [('condition_differs', 't120_low_a')])
        mismatches = {m['decision']: m for m in self.report['condition_mismatches']}
        self.assertEqual(mismatches['120']['kcd1'], ["gvar('dom') < 0.35"])
        self.assertEqual(mismatches['120']['kcd2'], ["gvar('dom') < -0.35"])
        self.assertIn("gvar('d') == 3", mismatches['110']['kcd2'])
        self.assertEqual(sorted(self.report['removed_responses']), ['smlo_high_de', 'smlo_low_a', 'smlo_own_goods', 'smlo_stolen_b'])
        silent = {(s['sequence'], s['voice_category'], s['player_choice']) for s in self.report['silenced_sequences']}
        self.assertEqual(silent, {('s9', '', False), ('s10', '', False), ('s5', '', False), ('german01', 'german', False)})
        # The silenced sequences keep their elements, scripts and jumps.
        s5 = next(q for q in self.root.iter('Sequence') if q.get('Name') == 's5')
        self.assertEqual((s5.get('EndType'), len(s5.find('Elements'))), ('EndDialogue', 0))

    def test_only_text_ids_dialog_name_role_name_and_removed_responses_change(self):
        removed = self.report['removed_responses']
        self.assertEqual(skeleton_differences(SKELETON, self.ported, 'man', removed), [])
        # Without the removal list the cut responses are differences.
        self.assertTrue(skeleton_differences(SKELETON, self.ported, 'man'))
        self.assertTrue(self.ported.startswith('﻿'.encode('utf-8')))
        self.assertEqual(self.root.find('Skald/FaderDialog').get('Name'), PORTED_NAME['man'])
        self.assertNotIn(b'SMLOUVANI_MUZ', self.ported.replace(PORTED_ROLE['man'].encode(), b''))
        script = [s.get('ExitScript') for s in self.root.iter('Sequence') if s.get('ExitScript')]
        self.assertEqual(script, [f"local merchant = dc['{PORTED_ROLE['man']}']\r\nShops.CancelTransaction(merchant.id)"])
        tampered = self.ported.replace(b'Shops.CancelTransaction', b'Shops.Other')
        self.assertEqual(len(skeleton_differences(SKELETON, tampered, 'man', removed)), 1)
        moved = self.ported.replace(b'GoToDecision="120" Name="s2"', b'GoToDecision="130" Name="s2"')
        self.assertIn("GoToDecision", skeleton_differences(SKELETON, moved, 'man', removed)[0])

    def test_duplicate_kcd2_string_is_refused(self):
        twice = SKELETON.replace(b'StringName="smlo_henry_b"', b'StringName="smlo_henry_a"')
        with self.assertRaisesRegex(ValueError, 'not unique'):
            map_haggle(HAGGLE_MAN, twice, 'man')

    def test_female_copy_aliases_onto_the_male_topics_with_an_inlined_branch(self):
        female = model('200', {
            '200': [sequence('11', '1', '210')],
            '210': [sequence('12', "gvar('d') == 0", '220', '1', 't210_henry_a', voices=('tmck',)),
                    sequence('13', "gvar('d') == 2", '0', '3', 't210_stolen_a', voices=('akem',))],
            '220': [sequence('14', "gvar('dom') >= 0.35", '0', '3', 't220_high_a', voices=('akem',))]})
        aliases = topic_aliases(female, HAGGLE_MAN)
        self.assertEqual(aliases, {'200': '100', '210': '110', '220': '120'})
        skeleton = SKELETON.replace(b'SMLOUVANI_MUZ', b'SMLOUVANI_ZENA')
        ported, report = map_haggle(female, skeleton, 'woman', aliases)
        strings = {r.get('Name'): [t.get('StringName') for t in r.findall('Elements/Response/Text')]
                   for r in ET.fromstring(ported).iter('Sequence')}
        # The inlined stolen-goods line lands in the nested slot of the matching KCD2 sequence.
        self.assertEqual((strings['s8'], strings['s61']), (['t210_stolen_a'], ['t220_high_a']))
        self.assertEqual(skeleton_differences(skeleton, ported, 'woman', report['removed_responses']), [])
        conflicting = model('200', {'200': [sequence('11', '1', '210'), sequence('15', '1', '210')],
                                    '210': [sequence('12', '', '0')]})
        reference = model('100', {'100': [sequence('1', '1', '110'), sequence('2', '1', '120')],
                                  '110': [sequence('3', '', '0')], '120': [sequence('4', '', '0')]})
        with self.assertRaisesRegex(ValueError, 'pairs with both'):
            topic_aliases(conflicting, reference)

    def test_inventory_counts_lines_texts_and_recordings_per_voice(self):
        report = inventory({('haggle', 'man'): HAGGLE_MAN}, facial_stems={'rpro_t120_high_a', 'tmck_t110_henry_a'})
        row = report['haggle_man']
        self.assertEqual((row['lines'], row['texted'], row['by_role']), (6, 2, {'HENRY': 2, 'SMLOUVANI_(MUZ)': 4}))
        self.assertEqual(row['voices'], {'rpro': {'recorded': 4, 'facial': 1}, 'bcas': {'recorded': 4, 'facial': 0},
                                         'tmck': {'recorded': 2, 'facial': 1}})


    def test_no_native_role_token_survives_anywhere_in_the_port(self):
        text = self.ported.decode('utf-8-sig')
        self.assertEqual(re.findall(r'SMLOUVANI_(?:MUZ|ZENA)', text), [])
        lists = [d.get('VoiceoverReductionRole') for d in self.root.iter('Decision') if d.get('VoiceoverReductionRole')]
        lists += [q.get('VoiceCategoryRoles') for q in self.root.iter('Sequence') if q.get('VoiceCategoryRoles')]
        self.assertEqual(set(lists), {PORTED_ROLE['man']})

    def test_reviewed_condition_override_merges_lines_in_kcd1_order(self):
        overrides = {('120', "gvar('dom') < 0.35"): "gvar('dom') < -0.35"}
        with patch.dict(kcd1_shop_conversation.CONDITION_OVERRIDES, overrides, clear=True):
            ported, report = map_haggle(HAGGLE_MAN, SKELETON, 'man')
        strings = {q.get('Name'): [t.get('StringName') for t in q.findall('Elements/Response/Text')]
                   for q in ET.fromstring(ported).iter('Sequence')}
        self.assertEqual(strings['s5'], ['t120_low_a'])
        self.assertEqual(report['condition_overrides'][0]['lines'], ['t120_low_a'])
        self.assertNotIn('t120_low_a', [d['string'] for d in report['dropped_lines']])

    def test_an_empty_kcd2_slot_keeps_its_position_and_drops_that_kcd1_line(self):
        source = model('100', {'100': [sequence('1', '1', '130')],
                               '130': [sequence('8', '', '0', '2', 't130_first'), sequence('9', '', '0', '2', 't130_second')]})
        skeleton = SKELETON.replace(b'<Text StringName="smlo_stolen_a" Text="Kradene." />', b'')
        ported, report = map_haggle(source, skeleton, 'man')
        strings = {q.get('Name'): [t.get('StringName') for t in q.findall('Elements/Response/Text')]
                   for q in ET.fromstring(ported).iter('Sequence')}
        self.assertEqual((strings['s8'], strings['s9']), ([], ['t130_second']))
        self.assertEqual([(d['reason'], d['string']) for d in report['dropped_lines']], [('empty_kcd2_slot', 't130_first')])



GREETING_ROLES = {'4': {'role_name': 'POZDRAV_(MUZ)'}}


def greeting_model(script="dc['POZDRAV_(MUZ)'].soul:RemoveMetaRoleByName('POZDRAV')"):
    def seq(sid, cond, nxt, string=None):
        record = sequence(sid, cond, nxt, '4', string)
        record['source']['script'] = ''
        return record
    start = seq('1', '1', '20')
    start['source']['script'] = script
    return dict(start_topic='10', roles=GREETING_ROLES,
                strings={'g_kind': 'Greetings!', 'g_blood': 'You are bleeding!', 'g_knight': 'Good knight.', 'g_any': 'Yes?'},
                topics={'10': dict(source={}, sequences=[start]),
                        '20': dict(source={}, sequences=[seq('2', 'greeting_reputation_5', '30'),
                                                         seq('3', "greeting_reputation_5 & gvar('playerIsBleeding') == 1", '40'),
                                                         seq('4', 'greeting_reputation_4 & greeting_looksKnightly', '0', 'g_knight'),
                                                         seq('5', '', '30')]),
                        '30': dict(source={}, sequences=[seq('6', '', '0', 'g_kind'), seq('7', '', '0', 'g_any')]),
                        '40': dict(source={}, sequences=[seq('8', '', '0', 'g_blood')])})


class GreetingTests(unittest.TestCase):
    def test_kcd1_functions_become_kcd2_greeting_ports(self):
        self.assertEqual(adapt_condition("(greeting_reputation_5 | greeting_reputation_4) & gvar('playerIsBleeding') == 1"),
                         "(Port('reputace_dobra') OR Port('reputace_dobra')) AND Port('hrac_je_zakrvaceny')")
        self.assertEqual(adapt_condition('GetActorAngriness()[1] > 0.2 & GetActorAngriness()[1] < 0.4'), "Port('nastvanost__neklid')")
        self.assertEqual(adapt_condition('HourOfDay() > 6 & HourOfDay() < 10'), "Port('je_rano')")
        self.assertEqual(adapt_condition('!expectsDude'), '!FALSE')
        self.assertEqual((adapt_condition('1'), adapt_condition('0')), ('', 'FALSE'))
        with self.assertRaisesRegex(ValueError, 'Unadapted'):
            adapt_condition("IsActor('rat_bernard')[1]")
        self.assertTrue(satisfiable("Port('a') AND !Port('b')"))
        self.assertFalse(satisfiable("Port('a') AND FALSE"))

    def test_greeting_is_a_once_a_day_kcd2_greeting_with_kcd1_lines(self):
        blob, report = emit_greeting(greeting_model(), 'man')
        dialog = ET.fromstring(blob).find('Skald/Dialog')
        body = dialog.find('Dialogue')
        self.assertEqual(body.get('Type'), 'greeting')
        gate = body.find('Decision/Sequences/Sequence')
        self.assertEqual(gate.get('EntryCondition'), "!Port('uz_jsem_pozdravil')")
        self.assertEqual([p.get('Name') for p in gate.findall('Triggers/Port')], ['nastav_cooldown'])
        ports = {p.get('Name'): p.get('Direction') for p in dialog.find('Ports')}
        self.assertEqual(ports, {'hrac_je_zakrvaceny': 'In', 'reputace_dobra': 'In', 'uz_jsem_pozdravil': 'In', 'nastav_cooldown': 'Out'})
        speakers = {r.get('Role') for r in body.iter('Response')} - {'HRAC'}
        self.assertEqual(speakers, {GREETING_ROLE['man']})
        texts = [t.get('StringName') for t in body.iter('Text')]
        self.assertEqual(sorted(texts), ['g_any', 'g_blood', 'g_kind', 'g_knight'])
        # Topic 30 is emitted once; the second reference jumps to it.
        jumps = [s.get('GoToDecision') for s in body.iter('Sequence') if s.get('EndType') == 'GoTo']
        self.assertEqual(jumps, ['t30'])
        self.assertEqual(report['replaced_scripts'], ['1'])
        self.assertEqual(report['unreachable_lines'], ['g_knight'])

    def test_unexpected_greeting_script_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected KCD1 greeting start script'):
            emit_greeting(greeting_model("Game.SomethingElse()"), 'man')



class TradeTests(unittest.TestCase):
    def trade_model(self, kind='9', string=None):
        record = sequence('42432', '1', '0', '4', string)
        record['source'].update(type=kind, ui_prompt='t22069_ui')
        return dict(start_topic='22069', roles=GREETING_ROLES, strings={'t22069_ui': "Let's talk trade.", 'x': 'x'},
                    topics={'22069': dict(source={}, sequences=[record])})

    def test_trade_choice_opens_the_shop_for_any_keeper_with_the_role(self):
        blob, report = emit_trade(self.trade_model())
        body = ET.fromstring(blob).find('Skald/FaderDialog/Dialogue')
        self.assertEqual((body.get('AllowGreeting'), body.get('AllowFarewell'), body.get('NonSpeakerRoles')),
                         ('true', 'false', 'GM_KCD1_OBCHODNIK'))
        self.assertEqual([q.get('Soul') for q in body.iter('SelectedSoul')], [None, None])
        types = [q.get('Type') for q in body.iter('Sequence') if q.get('Type')]
        self.assertEqual(types, ['Shop', 'OpenShop'])
        self.assertNotIn('seller_in_shop', blob.decode())
        prompts = {(u.get('StringName'), u.get('Text')) for u in body.iter('UiPrompt')}
        self.assertIn(('t22069_ui', "Let's talk trade."), prompts)
        self.assertEqual(report['kcd1_sequence'], '42432')

    def test_changed_trade_source_is_refused(self):
        for model in (self.trade_model(kind='0'), self.trade_model(string='x')):
            with self.assertRaisesRegex(ValueError, 'trade choice changed'):
                emit_trade(model)


if __name__ == '__main__':
    unittest.main()
