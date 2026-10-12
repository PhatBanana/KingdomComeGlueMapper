from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from ladders import convert, SOURCE_TYPE
from region_travel import guid
from seating_animations import HELPERS, ANIMATIONS
from test_cooking_pots import archive

SOURCE = f'''<Objects>
<Entity EntityId="9" Pos="10,20,30" Rotate="0.7071067811865476,0,0,0.7071067811865476"/>
<Entity EntityId="1" EntityClass="Ladder" ParentId="9" Pos="1,0,0">
<Properties fileModel="original.cgf" height="15.75" soclasses_SmartObjectHelpers="Ladder_mineshaft"
guidSmartObjectType="{SOURCE_TYPE}" bUsable="1" bInteractiveCollisionClass="1" bTopBlocked="1">
<Offsets getOnDistanceAwayTop="0.85" verticalDistanceBetweenRungs="0.25" bShowHelpers="0"/>
<Movement movementSpeedUpwards="2.5"/></Properties></Entity>
<Entity EntityId="2" EntityClass="Ladder" Layer="quest_state1{{x}}"><Properties/></Entity>
</Objects>'''.encode()
DEFS = b'''<SmartObjects><Helper className="Ladder_mineshaft" name="up" pos="0,-0.48,15.5" rot="1,0,0,0"/>
<Helper className="Ladder_mineshaft" name="down" pos="0,0.54,0" rot="0,0,0,1"/>
<Helper className="Ladder_mineshaft" name="align" pos="0,-1.09,0.4" rot="1,0,0,0"/></SmartObjects>'''


class LadderTests(unittest.TestCase):
    def build(self, source=SOURCE, defs=DEFS, files=None):
        files = files or {'objects_mission0.xml': b'''<Objects>
<Entity EntityId="30" Name="glue_item_1" Geometry="gluebuild/ladder.cgf" Material="gluebuild/ladder.mtl"/>
<Entity EntityId="31" Name="keep_me" EntityClass="GeomEntity"/></Objects>''',
                         ANIMATIONS: b'<database><SmartObjectAnimationss><SmartObjectAnimations EntityGuid="999"/></SmartObjectAnimationss></database>'}
        with archive({'objects_mission0.xml':source}) as src, archive({
            'objects_mission0.xml':b'<Objects><Entity EntityClass="Ladder"><Properties guidSmartObjectType="native-type"/></Entity></Objects>',
            HELPERS:b'<SmartObjectAnimationCollections><Collection HelperSetName="Ladder_mineshaft"><SmartObjectHelperSetAnimationCollection/></Collection></SmartObjectAnimationCollections>'}) as native:
            return convert(files,src,native,DEFS,defs,guid)

    def test_native_contract_preserves_geometry_height_flags_and_world_transform(self):
        files,r=self.build();root=E.fromstring(files['objects_mission0.xml'])
        node=root.find("Entity[@EntityClass='Ladder']");p=node.find('Properties')
        self.assertEqual(node.get('Pos'),'10,21,30')
        self.assertNotIn('ParentId',node.attrib)
        self.assertEqual(p.get('fileModel'),'gluebuild/ladder.cgf')
        self.assertEqual(p.get('height'),'15.75')
        self.assertEqual(p.get('guidSmartObjectType'),'native-type')
        self.assertEqual(p.get('soclass_SmartObjectHelpers'),'Ladder_mineshaft')
        self.assertNotIn('soclasses_SmartObjectHelpers',p.attrib)
        self.assertEqual(p.get('bUsable'),'true');self.assertEqual(p.get('bTopBlocked'),'true')
        self.assertEqual(p.find('Offsets').get('verticalDistanceBetweenRungs'),'0.25')
        self.assertIsNone(root.find("Entity[@Name='glue_item_1']"))
        self.assertIsNotNone(root.find("Entity[@Name='keep_me']"))
        self.assertEqual(r['converted'],1);self.assertEqual(len(r['inactive_layers']),1)
        rows=E.fromstring(files[ANIMATIONS]).find('SmartObjectAnimationss')
        self.assertEqual(len(rows),2);self.assertEqual(rows[1].get('AllowRuntimeAnimValidationFallback'),'true')
        self.assertEqual(rows[1].find('SmartObjectTransform').get('Position'),'10,21,30')

    def test_helper_mismatch_missing_mesh_and_repeat_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Different native ladder helper'):
            self.build(defs=DEFS.replace(b'15.5',b'15.0'))
        with self.assertRaisesRegex(ValueError,'geometry is missing'):
            self.build(files={'objects_mission0.xml':b'<Objects/>'})
        files,_=self.build()
        with self.assertRaisesRegex(ValueError,'already converted'):self.build(files=files)

    def test_player_only_watchtower_retains_empty_ai_contract(self):
        source=SOURCE.replace(b'Ladder_mineshaft',b'').replace(SOURCE_TYPE.encode(),b'')
        files,r=self.build(source=source)
        p=E.fromstring(files['objects_mission0.xml']).find("Entity[@EntityClass='Ladder']/Properties")
        self.assertEqual(p.get('guidSmartObjectType'),'')
        self.assertEqual(p.get('soclass_SmartObjectHelpers'),'')
        self.assertEqual(len(E.fromstring(files[ANIMATIONS]).find('SmartObjectAnimationss')),1)

    def test_helpers_without_ai_type_stay_player_only_and_nonunit_scale_is_rejected(self):
        files,_=self.build(source=SOURCE.replace(SOURCE_TYPE.encode(),b''))
        p=E.fromstring(files['objects_mission0.xml']).find("Entity[@EntityClass='Ladder']/Properties")
        self.assertEqual(p.get('soclass_SmartObjectHelpers'),'Ladder_mineshaft')
        self.assertEqual(p.get('guidSmartObjectType'),'')
        with self.assertRaisesRegex(ValueError,'non-unit scale'):
            self.build(source=SOURCE.replace(b'ParentId="9"',b'ParentId="9" Scale="1,1,2"'))


if __name__ == '__main__': unittest.main()
