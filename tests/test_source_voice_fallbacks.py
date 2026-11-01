"""Imported KCD1 voices get retail's own kind of fallback voice; converted shopkeepers are reported."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import source_voice_fallbacks
from source_voice_fallbacks import LEVEL, TRAVEL, coverage, plan, upgrade
from setup_campaign import digest

IMPORTED = 'Libs/Tables/skald/voice__gm_source.xml'
MISSION = b'''<Objects>
<Entity Name="shop_1" EntityClass="Shop" EntityGuid="000000a1-0000-0000"/>
<Entity Name="shop_2" EntityClass="Shop" EntityGuid="000000a2-0000-0000"/>
<Entity Name="shop_3" EntityClass="Shop" EntityGuid="000000a3-0000-0000"/>
<Entity Name="shop_4" EntityClass="Shop" EntityGuid="000000a4-0000-0000"/>
<Entity Name="ska_merchant1" EntityClass="NPC" EntityGuid="000000b1-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
<Entity Name="ska_merchant2" EntityClass="NPC" EntityGuid="000000b2-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a2-0000-0000"/></EntityLinks></Entity>
<Entity Name="ska_merchant3" EntityClass="NPC" EntityGuid="000000b3-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a3-0000-0000"/></EntityLinks></Entity>
<Entity Name="ska_merchant4" EntityClass="NPC_Female" EntityGuid="000000b4-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a4-0000-0000"/></EntityLinks></Entity>
<Entity Name="rat_pesek" EntityClass="NPC" EntityGuid="000000b5-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
<Entity Name="ska_collierVarlet" EntityClass="NPC" EntityGuid="000000b6-0000-0000"><EntityLinks><Link Name="home" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
</Objects>'''
SOULS = (b'<database name="barbora"><souls version="1">'
         b'<soul soul_name="ska_merchant1" skald_character_name="gm_voice_ska_merchant1"/>'
         b'<soul soul_name="ska_merchant2" skald_character_name="gm_voice_ska_merchant2"/>'
         b'<soul soul_name="ska_merchant3" skald_character_name="gm_voice_ska_merchant3"/>'
         b'<soul soul_name="ska_merchant4" skald_character_name="gm_voice_ska_merchant4"/>'
         b'<soul soul_name="ska_collierVarlet" skald_character_name="gm_voice_ska_collierVarlet"/>'
         b'<soul soul_name="rat_pesek" skald_character_name="char_GENERIC_MAN_COMMONER_07"/>'
         b'</souls></database>')
CHARACTERS = (b'<database name="barbora"><skald_characters version="1">'
              b'<skald_character skald_character_name="gm_voice_ska_merchant1" voice_id="100105" gender="0"/>'
              b'<skald_character skald_character_name="gm_voice_ska_merchant2" voice_id="78" gender="0"/>'
              b'<skald_character skald_character_name="gm_voice_ska_merchant3" voice_id="100105" gender="0"/>'
              b'<skald_character skald_character_name="gm_voice_ska_merchant4" voice_id="100070" gender="1"/>'
              b'<skald_character skald_character_name="gm_voice_ska_collierVarlet" voice_id="100105" gender="0"/>'
              b'</skald_characters></database>')
# A second person stage repeats a character with the same voice, as the real package does.
CHARACTERS_AGAIN = (b'<database name="barbora"><skald_characters version="1">'
                    b'<skald_character skald_character_name="gm_voice_ska_merchant3" voice_id="100105" gender="0"/>'
                    b'</skald_characters></database>')
IMPORTED_VOICES = (b'<database name="barbora"><voices version="1">'
                   b'<voice abbreviation="bvac" voice_id="100071" voice_name="bvac" voice_technical_name="gm_source_bvac" is_fake="false" fallback_voice_level="0"/>'
                   b'<voice abbreviation="rpro" voice_id="100105" voice_name="rpro" voice_technical_name="gm_source_rpro" is_fake="false" fallback_voice_level="0"/>'
                   b'<voice abbreviation="akem" voice_id="100070" voice_name="akem" voice_technical_name="gm_source_akem" is_fake="false" fallback_voice_level="0"/>'
                   b'</voices></database>')
# (abbreviation, id, level, fallback, groups): retail-shaped rows chosen so the rule, not retail's answer, decides.
NATIVE_ROWS = (('fejk', '1', '3', None, None), ('fejka', '2', '3', None, None),
               ('jbea', '144', '2', '1', 'Guards;Czechs;No Christian Blasphemy;Merchants'),
               ('gand', '83', '2', '1', 'Guards;Bandits;Czechs;No Christian Blasphemy;Merchants'),
               ('mwel', '163', '2', '1', 'Germans;Jews;Merchants'),
               ('dzap', '150', '2', '1', 'Czechs;Merchants'),
               ('nogr', '190', '2', '1', 'Czechs;Merchants'),
               ('aric', '68', '2', '2', 'Czechs;Merchants'),
               ('sphe', '107', '2', '2', 'Czechs;UltralightMerchants'),
               ('dcol', '140', '1', '83', 'Guards;Czechs'),
               ('bcas', '78', '0', '144', 'Guards;Czechs'),
               ('jmil', '158', '0', '144', 'Guards;Czechs;Merchants'),
               ('jcom', '239', '0', '83', 'Bandits;Czechs;Merchants'),
               ('ccla', '86', '0', '83', 'Bandits;Czechs;Merchants'),
               ('ggud', '85', '0', '83', 'Czechs;No Christian Blasphemy'))
# (character, voice, gender): dzap is bound to a man and a woman and so has no sex.
NATIVE_CHARACTER_ROWS = (('char_jbea_a', '144', '0'), ('char_jbea_b', '144', '0'), ('char_gand', '83', '0'),
                         ('char_GENERIC_MAN_COMMONER_07', '83', '0'), ('char_mwel', '163', '0'),
                         ('char_dzap_m', '150', '0'), ('char_dzap_f', '150', '1'), ('char_nogr', '190', '0'),
                         ('char_aric', '68', '1'), ('char_sphe', '107', '1'), ('char_dcol', '140', '0'),
                         ('char_bcas', '78', '0'), ('char_jmil', '158', '0'), ('char_jcom', '239', '0'),
                         ('char_ccla', '86', '0'), ('char_ggud', '85', '0'))
# (abbreviation, shop, greeting, farewell) native recordings; nogr has no farewell.
BANK_ROWS = (('jbea', 5, 2, 1), ('gand', 4, 1, 1), ('mwel', 6, 1, 1), ('dzap', 3, 1, 1), ('nogr', 3, 1, 0),
             ('aric', 3, 1, 1), ('sphe', 2, 1, 1), ('bcas', 2, 1, 1))


def native_voices(rows=NATIVE_ROWS):
    root = ET.Element('database', name='barbora')
    voices = ET.SubElement(root, 'voices', version='1')
    for abbreviation, voice_id, level, fallback, groups in rows:
        attrs = dict(abbreviation=abbreviation, voice_id=voice_id, voice_name=abbreviation,
                     voice_technical_name=abbreviation + 'Voice', is_fake='false', fallback_voice_level=level)
        if fallback: attrs['fallback_voice_id'] = fallback
        if groups: attrs['voice_groups'] = groups
        ET.SubElement(voices, 'voice', attrs)
    return ET.tostring(root)


def native_characters():
    root = ET.Element('database', name='barbora')
    rows = ET.SubElement(root, 'skald_characters', version='1')
    for name, voice_id, gender in NATIVE_CHARACTER_ROWS:
        ET.SubElement(rows, 'skald_character', skald_character_name=name, voice_id=voice_id, gender=gender)
    return ET.tostring(root)


def bank():
    entries = {}
    for abbreviation, shop, greetings, farewells in BANK_ROWS:
        for i in range(shop):
            entries[f'dialog/open_world/shop/{abbreviation}_shop_line_{i}.ogg'] = b'OggS'
        for i in range(greetings):
            entries[f'dialog/open_world/pozdravy_na_zacatku_dialogu/greeting_common_muz/{abbreviation}_greet_{i}.ogg'] = b'OggS'
        for i in range(farewells):
            entries[f'dialog/open_world/rozlouceni_na_konci_dialogu/{abbreviation}_bye_{i}.ogg'] = b'OggS'
    entries['dialog/open_world/combat/jbea_fight.ogg'] = b'OggS'
    entries['dialog/kcd1_travel/open_world/shop/jbea_relocated.ogg'] = b'OggS'
    return entries


def pak(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, blob in entries.items():
            z.writestr(name, blob)


class SourceVoiceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.package, self.game = root / 'mod', root / 'game'
        self.travel = {'Libs/Tables/rpg/soul__gm.xml': SOULS, 'Libs/Tables/skald/skald_character__gm.xml': CHARACTERS,
                       'Libs/Tables/skald/skald_character__gm_source_shop_33.xml': CHARACTERS_AGAIN,
                       IMPORTED: IMPORTED_VOICES, 'Libs/keep.xml': b'<keep/>'}
        self.tables = {'Libs/Tables/skald/voice.xml': native_voices(), 'Libs/Tables/skald/skald_character.xml': native_characters()}

    def write(self):
        pak(self.package / TRAVEL, self.travel)
        pak(self.package / LEVEL, {'objects_mission0.xml': MISSION})
        pak(self.game / 'Data/Tables.pak', self.tables)
        pak(self.game / 'Localization/English.pak', bank())
        return (self.package / TRAVEL).read_bytes()

    def imported(self):
        with zipfile.ZipFile(self.package / TRAVEL) as z:
            return {v.get('abbreviation'): dict(v.attrib) for v in ET.fromstring(z.read(IMPORTED)).iter('voice')}, z.read('Libs/keep.xml')

    def test_coverage_counts_native_folders_at_any_depth(self):
        counts = coverage(bank())
        self.assertEqual(counts['jbea'], {'shop': 5, 'greetings': 2, 'farewells': 1})
        self.assertEqual(counts['nogr'], {'shop': 3, 'greetings': 1, 'farewells': 0})
        self.assertNotIn('relocated', ' '.join(counts))

    def test_default_scope_covers_merchant1_and_merchant4(self):
        self.write()
        files, report = upgrade(self.package, self.game)
        self.assertEqual({v['voice']: v['status'] for v in report['voices']}, {'bvac': 'sex_unresolved', 'rpro': 'applied', 'akem': 'applied'})
        rows, _ = self.imported()
        self.assertEqual((rows['rpro']['fallback_voice_id'], rows['akem']['fallback_voice_id']), ('83', '68'))

    @patch.object(source_voice_fallbacks, 'SCOPE', ('ska_merchant1',))
    def test_scoped_imported_voice_gets_the_retail_pattern_fallback(self):
        self.write()
        progress = []
        files, report = upgrade(self.package, self.game, notify=lambda *a: progress.append(a))
        self.assertEqual(files, {TRAVEL: digest(self.package / TRAVEL)})
        self.assertEqual(progress[0][3], 'rpro -> gand')
        self.assertEqual(report['changed'], [IMPORTED])
        self.assertEqual(report['scope'], [{'person': 'ska_merchant1', 'outcome': 'imported_voice', 'voice': 'rpro'}])
        # Most referenced same-sex complete Czech merchant voice first; mwel (German), dzap (mixed
        # sex), nogr (no farewells) and sphe (not Merchants) never qualify.
        self.assertEqual([c['voice'] for c in report['candidates']['man']], ['gand', 'jbea'])
        self.assertEqual([c['voice'] for c in report['candidates']['woman']], ['aric'])
        self.assertEqual(report['candidates']['man'][0]['referenced_by'], 4)
        voices = {v['voice']: v for v in report['voices']}
        self.assertEqual(voices['rpro']['status'], 'applied')
        self.assertEqual(voices['rpro']['fallback'], {'voice': 'gand', 'voice_id': 83, 'recordings': {'shop': 4, 'greetings': 1, 'farewells': 1}})
        self.assertEqual(voices['rpro']['used_by'], ['ska_collierVarlet', 'ska_merchant1', 'ska_merchant3'])
        self.assertTrue(voices['rpro']['in_scope'])
        self.assertEqual((voices['akem']['status'], voices['akem']['fallback']['voice'], voices['akem']['in_scope']), ('candidate', 'aric', False))
        self.assertEqual((voices['bvac']['status'], voices['bvac']['fallback'], voices['bvac']['used_by']), ('sex_unresolved', None, []))
        keepers = {k['person']: k for k in report['keepers']}
        self.assertEqual(sorted(keepers), ['rat_pesek', 'ska_merchant1', 'ska_merchant2', 'ska_merchant3', 'ska_merchant4'])
        self.assertEqual((keepers['ska_merchant1']['kind'], keepers['ska_merchant1']['status'], keepers['ska_merchant1']['voice']), ('imported', 'applied', 'rpro'))
        self.assertEqual(keepers['ska_merchant1']['recordings'], {'shop': 0, 'greetings': 0, 'farewells': 0})
        self.assertEqual(keepers['ska_merchant1']['fallback']['voice'], 'gand')
        self.assertEqual(keepers['ska_merchant3']['status'], 'applied')
        self.assertEqual((keepers['ska_merchant2']['kind'], keepers['ska_merchant2']['status'], keepers['ska_merchant2']['voice']), ('native', 'native_voice', 'bcas'))
        self.assertEqual(keepers['ska_merchant2']['recordings'], {'shop': 2, 'greetings': 1, 'farewells': 1})
        self.assertEqual(keepers['ska_merchant2']['fallback']['voice'], 'jbea')
        self.assertEqual((keepers['ska_merchant4']['status'], keepers['ska_merchant4']['sex']), ('candidate', 'woman'))
        self.assertEqual((keepers['rat_pesek']['kind'], keepers['rat_pesek']['voice']), ('native', 'gand'))
        self.assertFalse(report['runtime_verified'])
        rows, keep = self.imported()
        self.assertEqual(rows['rpro']['fallback_voice_id'], '83')
        self.assertEqual(rows['rpro']['fallback_voice_level'], '0')
        self.assertNotIn('fallback_voice_id', rows['akem'])
        self.assertNotIn('fallback_voice_id', rows['bvac'])
        self.assertEqual(keep, b'<keep/>')
        before = (self.package / TRAVEL).read_bytes()
        files, report = upgrade(self.package, self.game)
        self.assertEqual((files, report['changed']), ({}, []))
        self.assertEqual({v['voice']: v['status'] for v in report['voices']}, {'bvac': 'sex_unresolved', 'rpro': 'present', 'akem': 'candidate'})
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)

    @patch.object(source_voice_fallbacks, 'SCOPE', ('ska_merchant1',))
    def test_existing_different_fallback_is_kept_and_reported(self):
        self.travel[IMPORTED] = IMPORTED_VOICES.replace(b'voice_technical_name="gm_source_rpro"', b'voice_technical_name="gm_source_rpro" fallback_voice_id="144"')
        before = self.write()
        files, report = upgrade(self.package, self.game)
        self.assertEqual(files, {})
        voices = {v['voice']: v for v in report['voices']}
        self.assertEqual((voices['rpro']['status'], voices['rpro']['existing_fallback'], voices['rpro']['fallback']['voice']), ('kept', 144, 'gand'))
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)

    def test_scoped_voice_without_a_candidate_fails_before_writing(self):
        self.tables['Libs/Tables/skald/voice.xml'] = native_voices(tuple(r for r in NATIVE_ROWS if r[0] != 'aric'))
        before = self.write()
        with patch.object(source_voice_fallbacks, 'SCOPE', ('ska_merchant4',)):
            with self.assertRaisesRegex(ValueError, 'No native fallback voice for imported voice akem'):
                upgrade(self.package, self.game)
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)

    def test_scope_without_a_converted_soul_is_reported_not_fatal(self):
        self.write()
        with patch.object(source_voice_fallbacks, 'SCOPE', ('ghost', 'ska_merchant2')):
            files, report = upgrade(self.package, self.game)
        self.assertEqual(files, {})
        self.assertEqual(report['scope'], [{'person': 'ghost', 'outcome': 'no_soul'}, {'person': 'ska_merchant2', 'outcome': 'native_voice'}])
        self.assertEqual({v['voice']: v['status'] for v in report['voices']}, {'bvac': 'sex_unresolved', 'rpro': 'candidate', 'akem': 'candidate'})

    def test_duplicate_imported_identity_is_rejected(self):
        self.travel['Libs/Tables/skald/voice__other.xml'] = IMPORTED_VOICES
        self.write()
        with self.assertRaisesRegex(ValueError, 'Duplicate imported voice identity'):
            plan(self.package, self.game)

    def test_game_folder_is_required(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'Game folder required'):
            upgrade(self.package, None)


if __name__ == '__main__':
    unittest.main()
