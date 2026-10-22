import copy
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from procedural_lights import expand, append_group, transform


class ProceduralLightsTests(unittest.TestCase):
    def schema(self):
        return E.fromstring('''<Properties Radius="2" bActive="1"><Color clrDiffuse="1,1,1"/>
          <Shadows nCastShadows="0"/><Options file_deferred_clip_geom=""/>
          <Projector texture_Texture=""/><Style flare_Flare="" lightanimation_LightAnimation=""/></Properties>''')

    def test_archetype_and_flame_resolve_without_legacy_script(self):
        p=E.fromstring('''<Prefab><Objects>
          <Object Id="a" Type="EntityArchetype" Prototype="{A}" Pos="1,0,0"/>
          <Object Id="b" EntityClass="ParticleEffect"><Properties ParticleEffect="OLD.Candle"/></Object>
          <Object Id="c" EntityClass="PrefabRoot"/>
          </Objects></Prefab>''')
        a=E.fromstring('<Prototype Class="Light"><Properties Radius="4" oldScript="bad"><Shadows nCastShadows="7"/></Properties></Prototype>')
        parts=expand(p,{'{a}':a},self.schema(),{'old.candle':'Old.Candle'})
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[0][1].find('Properties').get('Radius'),'4')
        self.assertIsNone(parts[0][1].find('Properties').get('oldScript'))
        self.assertEqual(parts[0][1].find('Properties/Shadows').get('nCastShadows'),'5')
        self.assertEqual(parts[1][1].find('Properties').get('ParticleEffect'),'Old.Candle')
        with self.assertRaisesRegex(ValueError,'Missing native particle'):
            expand(p,{'{a}':a},self.schema(),{})

    def test_repeat_keeps_ids_and_rejects_conflicting_existing_light(self):
        root=E.fromstring('<Entities><Entity EntityId="30582" Name="other"/></Entities>')
        lamp=E.fromstring('<Entity EntityClass="Light" Pos="1,0,0"><Properties Radius="2"/></Entity>')
        parent=((10,20,30),(2**-.5,0,0,2**-.5),(2,2,2))
        self.assertEqual(append_group(root,'123',parent,[('a',lamp)]),1)
        self.assertEqual(root[-1].get('EntityId'),'30584')  # reserved player ID skipped
        self.assertEqual(root[-1].get('Pos'),'10,22,30')
        before=E.tostring(root)
        self.assertEqual(append_group(root,'123',parent,[('a',lamp)]),0)
        self.assertEqual(E.tostring(root),before)
        bad=copy.deepcopy(lamp);bad.find('Properties').set('Radius','3')
        with self.assertRaisesRegex(ValueError,'Changed registered light'):
            append_group(root,'123',parent,[('a',bad)])

    def test_unknown_components_are_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            expand(E.fromstring('<Prefab><Objects><Object EntityClass="Unknown"/></Objects></Prefab>'),{},self.schema(),{})


if __name__=='__main__':unittest.main()
