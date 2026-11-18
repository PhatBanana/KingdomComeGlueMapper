import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from storm_lab.audit import run as audit
from storm_lab.engine import Engine
from storm_lab.mounts import Mounts
from storm_lab.program import Program
from storm_lab.runner import run_scenario
from storm_lab.selectors import Context, node
from storm_lab.tables import load
from storm_lab.__main__ import main


def storm(*rules, selectors='', operations=''):
    body = ''.join(rules)
    return ('<?xml version="1.0"?>\n<!DOCTYPE storm SYSTEM "..\\storm.dtd">\n<storm>'
            + ('<customSelectors>%s</customSelectors>' % selectors if selectors else '')
            + ('<customOperations>%s</customOperations>' % operations if operations else '')
            + ('<rules>%s</rules>' % body if body else '') + '</storm>')


def rule(name, selectors, *ops):
    return '<rule name="%s"><selectors>%s</selectors><operations>%s</operations></rule>' % (name, selectors, ''.join(ops))


def add(role):
    return '<addRole name="%s"/>' % role


def table(element, rows):
    return '<database name="barbora"><%ss version="1">%s</%ss></database>' % (
        element, ''.join('<%s %s/>' % (element, ' '.join('%s="%s"' % kv for kv in r.items())) for r in rows), element)


BASE = '''
<customSelector name="isMan"><hasSoulArchetype name="NPC"/></customSelector>
<customSelector name="isWoman"><hasSoulArchetype name="NPC_Female"/></customSelector>
<customSelector name="isHuman" mode="or"><isMan/><isWoman/></customSelector>
<customSelector name="hasNoCharacter"><not><hasACharacter/></not></customSelector>
<customSelector name="hasMerchantVoice" mode="or"><hasVoice name="merchantVoice"/><hasVoice ID="7"/></customSelector>
<customSelector name="hasMerchantVoiceOrNoCharacter" mode="or"><hasMerchantVoice/><hasNoCharacter/></customSelector>
<customSelector name="isTest"><or><hasName name="test_*"/></or></customSelector>
'''
OPS = '''
<customOperation name="addShopRoles_essential_man"><addRole name="SMLOUVANI_MUZ"/><addRole name="VYJEDNAVANI_MUZ"/><addRole name="OBCHODNIK_Z_CHATU"/></customOperation>
<customOperation name="addShopRoles_ending_man"><addRole name="OBCHODNIK_SE_LOUCI"/></customOperation>
<customOperation name="addShopRoles_essential_woman"><addRole name="SMLOUVANI_ZENA"/><addRole name="VYJEDNAVANI_ZENA"/><addRole name="OBCHODNICE_Z_CHATU"/></customOperation>
<customOperation name="addShopRoles_ending_woman"><addRole name="OBCHODNICE_SE_LOUCI"/></customOperation>
<customOperation name="nested"><addShopRoles_ending_man/><addRole name="EXTRA"/></customOperation>
'''
ROLE_NAMES = ['NPC', 'GREETING', 'SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ', 'OBCHODNIK_Z_CHATU', 'OBCHODNIK_SE_LOUCI',
              'SMLOUVANI_ZENA', 'VYJEDNAVANI_ZENA', 'OBCHODNICE_Z_CHATU', 'OBCHODNICE_SE_LOUCI', 'EXTRA', 'MOD_ROLE',
              'MERCHANT_BARK', 'TEMP', 'AFTER']


def native_blobs(roles_xml, extra_sources=()):
    sources = ['roles/world/a.xml'] + list(extra_sources)
    blobs = {
        'Libs/Storm/storm.xml': '<storm><common><source path="common\\base.xml"/><source path="common\\roles_operations.xml"/>'
                                '</common><tasks><task name="roles" class="roles">'
                                + ''.join('<source path="%s"/>' % s.replace('/', '\\') for s in sources)
                                + '</task></tasks></storm>',
        'Libs/Storm/common/base.xml': storm(selectors=BASE),
        'Libs/Storm/common/roles_operations.xml': storm(operations=OPS),
        'Libs/Storm/roles/world/a.xml': roles_xml,
        'Libs/Tables/rpg/soul_archetype.xml': table('soul_archetype', [
            dict(soul_archetype_id='0', soul_archetype_name='NPC', gender_id='1'),
            dict(soul_archetype_id='1', soul_archetype_name='NPC_Female', gender_id='2')]),
        'Libs/Tables/rpg/gender.xml': table('gender', [dict(gender_id='1', gender_name='male'),
                                                       dict(gender_id='2', gender_name='female')]),
        'Libs/Tables/rpg/social_class.xml': table('social_class', [dict(social_class_id='1', social_class_name='villager'),
                                                                   dict(social_class_id='2', social_class_name='blacksmith')]),
        'Libs/Tables/rpg/role.xml': table('role', [dict(role_name=r, metarole_name=(
            'VYJEDNAVANI' if r.startswith('VYJ') else 'SMLOUVANI' if r.startswith('SMLOUVANI') else 'NPC')) for r in ROLE_NAMES]),
        'Libs/Tables/rpg/FactionTree.xml': '<database><FactionTree version="1"><Faction Name="region"><Children>'
                                           '<Faction Name="region_town" Labels="settlement"/><Faction Name="region_bad" '
                                           'Labels="publicEnemy"/></Children></Faction></FactionTree></database>',
        'Libs/Tables/skald/skald_character.xml': table('skald_character', [
            dict(skald_character_name='char_merchant', voice_id='7'), dict(skald_character_name='char_plain', voice_id='8')]),
        'Libs/Tables/skald/voice.xml': table('voice', [
            dict(voice_id='7', voice_technical_name='merchantVoice', voice_groups='Czechs;Merchants'),
            dict(voice_id='8', voice_technical_name='plainVoice', voice_groups='Czechs')]),
        'Libs/Tables/rpg/soul__native.xml': table('soul', [dict(soul_name='native_a', soul_archetype_id='0',
                                                                skald_character_name='char_merchant', voice_group_name='Merchants')]),
    }
    return blobs


def soul(name, **attrs):
    row = dict(soul_name=name, soul_archetype_id='0', social_class_id='1', factionName='region_town')
    row.update(attrs)
    return row


def mounts(roles_xml, souls, mod_roles=None, mission=None, extra=None):
    native = native_blobs(roles_xml)
    mod = {'Libs/Tables/rpg/soul__test.xml': table('soul', souls)}
    if mod_roles is not None:
        mod['Libs/Storm/roles/gm_test.xml'] = mod_roles
        mod['Libs/Storm/storm.xml'] = native['Libs/Storm/storm.xml'].replace(
            '</task>', '<source path="roles\\gm_test.xml"/></task>')
    if mission is not None:
        mod['Levels/test/objects_mission0.xml'] = mission
    mod.update(extra or {})
    return Mounts.blobs(mod, native)


def evaluate(selectors_xml, soul_row, roles_xml=None):
    m = mounts(roles_xml or storm(rule('r', '<isMan/>', add('NPC'))), [soul_row])
    program, tables = Program(m), load(m)
    ctx = Context(tables, program.custom_selectors)
    s = [x for x in tables.souls if x.name == soul_row['soul_name']][0]
    ctx.begin_soul(s, {})
    return node(E.fromstring('<selectors>%s</selectors>' % selectors_xml), s, ctx)


def run(roles_xml, souls, **kw):
    m = mounts(roles_xml, souls, **kw)
    program, tables = Program(m), load(m)
    engine = Engine(program, tables)
    return {s.name: engine.run(s) for s in tables.souls if s.converted}


def mission(*keepers):
    shop = '<Entity Name="shop" EntityClass="Shop" EntityGuid="S1"/>'
    npcs = ''.join('<Entity Name="%s" EntityClass="%s" EntityGuid="N%d"><EntityLinks><Link Name="shopKeeper" '
                   'TargetGuid="S1"/></EntityLinks></Entity>' % (n, c, i) for i, (n, c) in enumerate(keepers))
    return '<Mission><Objects>%s%s</Objects></Mission>' % (shop, npcs)


class SelectorAlgebra(unittest.TestCase):
    def test_custom_selector_modes_and_not(self):
        man = soul('m')
        self.assertEqual(evaluate('<isHuman/>', man).status(), 'APPLIES')       # mode="or"
        self.assertEqual(evaluate('<isWoman/>', man).status(), 'NO')
        self.assertEqual(evaluate('<not><isWoman/></not>', man).status(), 'APPLIES')
        self.assertEqual(evaluate('<isMan/><isWoman/>', man).status(), 'NO')    # selectors = AND
        self.assertEqual(evaluate('<or><isWoman/><isMan/></or>', man).status(), 'APPLIES')

    def test_hasname_glob_is_anchored_and_case_insensitive_with_flag(self):
        s = soul('Rat_Pesek')
        self.assertEqual(evaluate('<hasName name="rat_*"/>', s).status(), 'APPLIES')
        self.assertIn('assume:hasName-case', evaluate('<hasName name="rat_*"/>', s).deps)
        self.assertEqual(evaluate('<hasName name="Rat_Pesek"/>', s).deps, frozenset())
        self.assertEqual(evaluate('<hasName name="pesek"/>', s).status(), 'NO')
        self.assertEqual(evaluate('<hasName Name="*_pesek"/>', s).status(), 'APPLIES')

    def test_unknown_primitive_is_unsupported_unless_a_sibling_decides(self):
        s = soul('a')
        self.assertEqual(evaluate('<isMan/><hasMysteryThing/>', s).status(), 'UNSUPPORTED')
        self.assertEqual(evaluate('<hasMysteryThing/><isWoman/>', s).status(), 'NO')
        self.assertEqual(evaluate('<or><hasMysteryThing/><isMan/></or>', s).status(), 'APPLIES')
        self.assertEqual(evaluate('<hasAttribute stat="str" minValue="5"/>', s).status(), 'UNSUPPORTED')

    def test_random_and_game_mode_fork(self):
        s = soul('a')
        self.assertEqual(evaluate('<hasRandomValue min="0" max="50"/>', s).status(), 'FORK')
        self.assertEqual(evaluate('<isWoman/><isGameMode mode="hardcore"/>', s).status(), 'NO')

    def test_voice_through_skald_character(self):
        merchant = soul('m', skald_character_name='char_merchant')
        plain = soul('p', skald_character_name='char_plain', voice_group_name='Merchants')
        self.assertEqual(evaluate('<hasVoice name="merchantVoice"/>', merchant).status(), 'APPLIES')
        self.assertEqual(evaluate('<hasVoice ID="7"/>', merchant).status(), 'APPLIES')
        # voice_group_name is not the voice: the character's voice decides.
        self.assertEqual(evaluate('<hasMerchantVoice/>', plain).status(), 'NO')
        self.assertEqual(evaluate('<hasMerchantVoice/>', plain).deps, frozenset())

    def test_no_character_has_no_voice_but_passes_or_no_character(self):
        nochar = soul('n', voice_group_name='Merchants')
        v = evaluate('<hasMerchantVoice/>', nochar)
        self.assertEqual(v.status(), 'NO')
        self.assertIn('assume:hasVoice-no-character', v.deps)   # a Merchants voice could match
        self.assertEqual(evaluate('<hasMerchantVoiceOrNoCharacter/>', nochar).status(), 'APPLIES')
        self.assertEqual(evaluate('<hasMerchantVoiceOrNoCharacter/>', nochar).deps, frozenset())
        czech_only = soul('c', voice_group_name='Guards')    # no voice in that group is a merchant voice
        self.assertEqual(evaluate('<hasMerchantVoice/>', czech_only).deps, frozenset())

    def test_missing_character_is_unsupported(self):
        self.assertEqual(evaluate('<hasVoice name="x"/>', soul('a', skald_character_name='nope')).status(), 'UNSUPPORTED')

    def test_faction_ancestors_and_labels(self):
        s = soul('a', factionName='region_bad')
        v = evaluate('<hasFaction name="region"/>', s)
        self.assertEqual(v.status(), 'APPLIES'); self.assertIn('assume:hasFaction-ancestor', v.deps)
        self.assertEqual(evaluate('<hasFaction name="region_bad"/>', s).deps, frozenset())
        self.assertEqual(evaluate('<isPublicEnemy/>', s).status(), 'APPLIES')
        self.assertEqual(evaluate('<hasFactionLabel name="settlement"/>', s).status(), 'NO')

    def test_gender_and_combat_level(self):
        self.assertEqual(evaluate('<hasGender name="Female"/>', soul('w', soul_archetype_id='1')).status(), 'APPLIES')
        self.assertEqual(evaluate('<hasCombatLevel minValue="0.5"/>', soul('a')).status(), 'UNSUPPORTED')
        self.assertEqual(evaluate('<hasCombatLevel minValue="0.5"/>', soul('a', combat_level='0.6')).status(), 'APPLIES')

    def test_duplicate_custom_selector_disagreement_is_ambiguous(self):
        roles = storm(rule('r', '<isSoldier/>', add('NPC')),
                      selectors='<customSelector name="isSoldier"><hasSocialClass name="villager"/></customSelector>'
                                '<customSelector name="isSoldier"><hasSocialClass name="blacksmith"/></customSelector>')
        r = run(roles, [soul('a')])['a']
        self.assertEqual(r.roles['NPC'].definite, False)
        self.assertIn('ambiguous:duplicate customSelector isSoldier', r.roles['NPC'].deps)


class Operations(unittest.TestCase):
    def test_remove_after_add_and_macro_expansion(self):
        native = storm(rule('first', '<isMan/>', add('TEMP'), '<nested/>'))
        mod = storm(rule('later', '<hasName name="a"/>', '<removeRole name="TEMP"/>'))
        r = run(native, [soul('a'), soul('b')], mod_roles=mod)
        self.assertNotIn('TEMP', r['a'].roles)
        self.assertIn('TEMP', r['b'].roles)
        self.assertEqual({'OBCHODNIK_SE_LOUCI', 'EXTRA'} <= set(r['a'].roles), True)
        self.assertEqual(r['a'].roles['EXTRA'].sources[0]['rule'], 'first')

    def test_conditional_add_and_remove(self):
        native = storm(rule('a', '<isMan/>', add('TEMP')),
                       rule('b', '<hasRandomValue min="0" max="50"/>', '<removeRole name="TEMP"/>'))
        r = run(native, [soul('a')])['a']
        self.assertFalse(r.roles['TEMP'].definite)
        self.assertIn('fork:random', r.roles['TEMP'].deps)

    def test_hasrole_reads_earlier_rules_and_flags_late_writers(self):
        native = storm(rule('reader', '<hasRole name="MOD_ROLE"/>', '<addMetarole name="LATE"/>'))
        mod = storm(rule('writer', '<hasName name="a"/>', add('MOD_ROLE')))
        r = run(native, [soul('a')], mod_roles=mod)['a']
        self.assertNotIn('LATE', r.metaroles)
        self.assertEqual(r.alternatives[0]['with_final_roles'], 'APPLIES')


class Contracts(unittest.TestCase):
    def audit(self, mod_roles, souls, keepers):
        return audit(None, None, mounts=mounts(storm(rule('base', '<isHuman/>', add('NPC'))), souls,
                                               mod_roles=mod_roles, mission=mission(*keepers)))

    def test_trade_contract_shapes(self):
        good = storm(rule('k', '<hasName name="keeper"/>', add('SMLOUVANI_MUZ'), add('VYJEDNAVANI_MUZ'),
                          '<addShopRoles_ending_man/>'))
        report = self.audit(good, [soul('keeper')], [('keeper', 'NPC')])
        self.assertEqual(report['contracts'][0]['status'], 'PASS')
        self.assertTrue(report['contracts'][0]['negotiation_metarole']['role_table'])
        missing = storm(rule('k', '<hasName name="keeper"/>', add('SMLOUVANI_MUZ'), '<addShopRoles_ending_man/>'))
        row = self.audit(missing, [soul('keeper')], [('keeper', 'NPC')])['contracts'][0]
        self.assertEqual((row['status'], row['missing']), ('FAIL', ['VYJEDNAVANI_MUZ']))
        woman = self.audit(good, [soul('keeper', soul_archetype_id='1')], [('keeper', 'NPC_Female')])['contracts'][0]
        self.assertEqual(woman['status'], 'FAIL')     # man's roles on a woman keeper

    def test_dialog_trade_role_duplicates_only_a_generated_trade_dialog(self):
        native_path = storm(rule('k', '<hasName name="keeper"/>', '<addShopRoles_essential_man/>',
                                 '<addShopRoles_ending_man/>'))
        level = ('<Database><Skald><Level Name="entry"><Definitions><Definition File="dialogs/gm_trade.xml"/>'
                 '</Definitions></Level></Skald></Database>')
        fader = ('<Database><Skald><FaderDialog Name="gm_trade"><Dialogue><SelectedSouls>'
                 '<SelectedSoul Role="HENRY" Voice="v"/><SelectedSoul Role="keeper_role" Soul="keeper"/></SelectedSouls>'
                 '<Sequence Name="trade" Type="Shop"><Decision><Sequences><Sequence Name="open_shop" Type="OpenShop">'
                 '<Elements><Response Role="keeper_role"/></Elements></Sequence></Sequences></Decision></Sequence>'
                 '</Dialogue></FaderDialog></Skald></Database>')

        def contract(extra):
            return audit(None, None, mounts=mounts(storm(rule('base', '<isHuman/>', add('NPC'))), [soul('keeper')],
                                                   mod_roles=native_path, mission=mission(('keeper', 'NPC')),
                                                   extra=extra))['contracts'][0]
        # Native dialog roles alone are the keeper's trade path.
        row = contract({})
        self.assertEqual((row['status'], row['duplicate_trade'], row['native_trade_roles']),
                         ('PASS', [], ['OBCHODNIK_Z_CHATU']))
        # A registered generated trade dialog for the same keeper makes them a second Trade option.
        row = contract({'Quests/Test/entry.xml': level, 'Quests/Test/dialogs/gm_trade.xml': fader})
        self.assertEqual((row['status'], row['duplicate_trade'], row['generated_trade_dialogs']),
                         ('FAIL', ['OBCHODNIK_Z_CHATU'], ['gm_trade']))
        # An unregistered dialog file, or one for another soul, does not count.
        row = contract({'Quests/Test/dialogs/gm_trade.xml': fader})
        self.assertEqual(row['status'], 'PASS')
        row = contract({'Quests/Test/entry.xml': level,
                        'Quests/Test/dialogs/gm_trade.xml': fader.replace('Soul="keeper"', 'Soul="other"')})
        self.assertEqual(row['status'], 'PASS')

    def test_ported_kcd1_haggle_meets_the_contract_without_ending_roles(self):
        ported_roles = {'Libs/Tables/rpg/role__gm_kcd1_shop.xml': table('role', [
            dict(role_name='GM_KCD1_SMLOUVANI_MUZ', metarole_name='SMLOUVANI'),
            dict(role_name='GM_KCD1_OBCHODNIK', metarole_name='NPC')])}

        def contract(*ops, extra=ported_roles):
            mod = storm(rule('k', '<hasName name="keeper"/>', *ops))
            return audit(None, None, mounts=mounts(storm(rule('base', '<isHuman/>', add('NPC'))), [soul('keeper')],
                                                   mod_roles=mod, mission=mission(('keeper', 'NPC')), extra=extra))['contracts'][0]
        row = contract(add('GM_KCD1_SMLOUVANI_MUZ'), add('VYJEDNAVANI_MUZ'), add('GM_KCD1_OBCHODNIK'))
        self.assertEqual((row['status'], row['missing'], row['haggle_roles']), ('PASS', [], ['GM_KCD1_SMLOUVANI_MUZ']))
        self.assertEqual((row['ported_kcd1_haggle'], row['trade_path']), (True, 'GM_KCD1_OBCHODNIK'))
        self.assertNotIn('OBCHODNIK_SE_LOUCI', row['required'])
        # A second haggle role (the native one beside the port) binds two haggle dialogs.
        row = contract(add('GM_KCD1_SMLOUVANI_MUZ'), add('SMLOUVANI_MUZ'), add('VYJEDNAVANI_MUZ'), add('GM_KCD1_OBCHODNIK'))
        self.assertEqual((row['status'], row['haggle_roles']), ('FAIL', ['GM_KCD1_SMLOUVANI_MUZ', 'SMLOUVANI_MUZ']))
        # Without a role-table row mapping it to SMLOUVANI the ported role meets nothing.
        row = contract(add('GM_KCD1_SMLOUVANI_MUZ'), add('VYJEDNAVANI_MUZ'), extra={})
        self.assertEqual((row['status'], row['missing'][0]), ('FAIL', 'SMLOUVANI_MUZ'))
        self.assertIsNone(row['trade_path'])
        # Negotiation is still required.
        row = contract(add('GM_KCD1_SMLOUVANI_MUZ'), add('GM_KCD1_OBCHODNIK'))
        self.assertEqual((row['status'], row['missing']), ('FAIL', ['VYJEDNAVANI_MUZ']))

    def test_keeper_without_soul_fails(self):
        report = self.audit(storm(), [soul('other')], [('keeper', 'NPC')])
        self.assertEqual(report['contracts'][0]['status'], 'FAIL')
        self.assertEqual(report['verdict']['status'], 'FAIL')

    def test_merchant_roles_on_non_keeper_and_voice_group_shape(self):
        mod = storm(rule('x', '<hasName name="villager"/>', add('SMLOUVANI_MUZ')),
                    rule('y', '<hasName name="nobody_anywhere"/>', add('NPC')))
        report = self.audit(mod, [soul('villager', voice_group_name='Merchants')], [])
        kinds = {f['kind'] for f in report['findings']}
        self.assertIn('merchant-role-on-non-keeper', kinds)
        self.assertIn('voice-group-without-character', kinds)
        self.assertIn('mod-rule-selects-no-soul', kinds)
        shape = [f for f in report['findings'] if f['kind'] == 'voice-group-without-character'][0]
        self.assertIn('0 of 1 native souls', shape['detail'])

    def test_unknown_role_from_mod_is_error_and_native_capture_is_review(self):
        native = storm(rule('cap', '<hasName name="rat_*"/>', add('GREETING')))
        mod = storm(rule('x', '<hasName name="rat_a"/>', add('NOT_IN_TABLE')))
        report = audit(None, None, mounts=mounts(native, [soul('rat_a')], mod_roles=mod))
        by_kind = {f['kind']: f['severity'] for f in report['findings']}
        self.assertEqual(by_kind['unknown-role'], 'error')
        self.assertEqual(by_kind['native-name-capture'], 'review')

    def test_missing_sources(self):
        m = mounts(storm(), [soul('a')], mod_roles=storm())
        m.mod.members.pop('libs/storm/roles/gm_test.xml')
        report = audit(None, None, mounts=m)
        self.assertIn('missing-mod-storm-source', {f['kind'] for f in report['findings']})


class Cli(unittest.TestCase):
    def test_scenario_runner_and_reports(self):
        native = native_blobs(storm(rule('greet', '<isValid/>', add('GREETING')),
                                    rule('fork', '<hasRandomValue min="0" max="1"/>', add('MERCHANT_BARK')),
                                    selectors='<customSelector name="isValid"><isHuman/><not><isTest/></not></customSelector>'))
        spec = dict(name='synthetic', blobs=dict(native=native, mod={'Libs/Tables/rpg/soul__t.xml': table('soul', [soul('a'), soul('test_b')])}),
                    assertions=[dict(soul='a', has_role='GREETING'), dict(soul='test_b', lacks_role='GREETING')])
        self.assertEqual(run_scenario(spec)['status'], 'PASS')
        spec['assertions'] = [dict(soul='a', has_role='MERCHANT_BARK')]
        self.assertEqual(run_scenario(spec)['status'], 'UNSUPPORTED')
        spec['assertions'] = [dict(soul='a', lacks_role='GREETING')]
        self.assertEqual(run_scenario(spec)['status'], 'FAIL')
        with tempfile.TemporaryDirectory() as tmp:
            spec['assertions'] = [dict(soul='a', has_role='GREETING')]
            path = Path(tmp) / 's.json'; path.write_text(json.dumps(spec), encoding='utf-8')
            self.assertEqual(main(['run', str(path), '--output', str(Path(tmp) / 'out')]), 0)
            for name in ('results.json', 'junit.xml', 'report.html'):
                self.assertTrue((Path(tmp) / 'out' / name).is_file())

    def test_audit_writes_reports(self):
        from storm_lab.report import write_audit
        report = audit(None, None, mounts=mounts(storm(rule('base', '<isHuman/>', add('NPC'))), [soul('a')]))
        with tempfile.TemporaryDirectory() as tmp:
            write_audit(report, Path(tmp))
            data = json.loads((Path(tmp) / 'roles_by_soul.json').read_text(encoding='utf-8'))
            self.assertEqual(data['souls']['a']['roles']['NPC']['status'], 'DEFINITE')
            self.assertFalse(data['native_runtime_verified'])
            E.parse(Path(tmp) / 'junit.xml')
            self.assertIn('Storm Role Audit', (Path(tmp) / 'audit.html').read_text(encoding='utf-8'))

    def test_could_not_run_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(['audit', tmp, '--target', tmp, '--output', str(Path(tmp) / 'o')]), 2)


if __name__ == '__main__':
    unittest.main()
