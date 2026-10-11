from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from washing_troughs import convert, PREFAB
from region_travel import guid
from campaign_entity_links import guid_value, native_guid
from test_cooking_pots import archive


class WashingTests(unittest.TestCase):
    def build(self,missing=False,external=False,existing=None):
        source={'objects_mission0.xml':b'''<Objects>
          <Entity EntityId="1" EntityClass="PickableItem" Pos="10,20,30"><Properties soclasses_SmartObjectHelpers="water_tube_1"/></Entity>
          <Entity EntityId="2" EntityClass="SequenceTrigger"><EntityLinks><Link TargetId="1"/></EntityLinks><Properties><Click UseMessage="@ui_use_wash"/></Properties></Entity>
          <Entity EntityId="3" EntityClass="SequenceTrigger" Layer="later{x}"><Properties><Click UseMessage="@ui_use_wash"/></Properties></Entity>
          </Objects>'''}
        native={'objects_mission0.xml':f'''<Objects>
          <Entity EntityId="3040" EntityGuid="{native_guid(100)}" EntityClass="SmartObjectHolder" Pos="100,200,300">
            <Properties soclass_SmartObjectHelpers="watertube" guidSmartObjectType="native"/>
            <EntityLinks><Link TargetId="3039" Name="trigger"/><Link TargetId="3040" Name="+Clean[washFace,0.9]"/><Link TargetId="999" Name="schedulerReservedItem"/></EntityLinks></Entity>
          <Entity EntityId="3039" EntityGuid="{native_guid(101)}" EntityClass="WaterTubeActionTrigger" Pos="100,200,300.6" Scale="0.3,0.3,0.3">
            <Properties><Click sAction="WashFace" UseMessage="@ui_use_wash" CannotWashReason="@waterTube_wash_max_text"/></Properties>
            <EntityLinks><Link TargetId="3040" Name=""/></EntityLinks></Entity></Objects>'''.encode(),
          'tables/ai/scheduler.xml':('<database><Schedulers><C_SmartHub EntityGuid="100">'+
              ('<Links/>' if external else '')+'<PostSearchData><SmartHubPostSearchData><SchedulerEffect><EffectClean CleanTarget="0.9" Role="washFace"/></SchedulerEffect></SmartHubPostSearchData></PostSearchData></C_SmartHub></Schedulers></database>').encode(),
          'smartobjecthelpersetanimations.xml':b'<SmartObjectAnimationCollections><Collection HelperSetName="watertube"/></SmartObjectAnimationCollections>'}
        old={'Libs/SmartObjects.xml':b'<SmartObjects><Helper className="water_tube_1" name="washPoint" pos="0,0.2,0" rot="1,0,0,0"/></SmartObjects>'}
        new={'Libs/SmartObjects.xml':b'<SmartObjects><Helper className="watertube" name="Place0" pos="0,0,0" rot="1,0,0,0"/></SmartObjects>',
             PREFAB:b'<Prefab><Objects><Object Type="Brush" Prefab="native_water.cgf"/></Objects></Prefab>'}
        files=existing or {'objects_mission0.xml':b'<Objects><Entity EntityId="10" Name="unrelated"/><Entity Name="glue_item_1" Geometry="old.cgf" Material="old.mtl"><Properties/></Entity></Objects>',
               'tables/ai/scheduler.xml':b'<database><Schedulers><C_SmartHub EntityGuid="77"/></Schedulers></database>'}
        if missing:files['objects_mission0.xml']=b'<Objects><Entity EntityId="10"/></Objects>'
        with archive(source) as s,archive(native) as n,archive(old) as o,archive(new) as g:
            return convert(files,s,n,o,g,guid)

    def test_native_wash_contract_replaces_visual_and_preserves_existing_systems(self):
        files,report=self.build();root=E.fromstring(files['objects_mission0.xml'])
        self.assertEqual(report['converted'],1)
        self.assertEqual(len(report['inactive_layer_troughs']),1)
        self.assertIsNotNone(root.find("Entity[@Name='unrelated']"))
        visual=root.find("Entity[@Name='glue_item_1']")
        self.assertEqual(visual.get('Geometry'),'native_water.cgf');self.assertNotIn('Material',visual.attrib)
        self.assertEqual(visual.get('Pos'),'10,20.2,30')
        owner=root.find("Entity[@EntityClass='SmartObjectHolder']")
        trigger=root.find("Entity[@EntityClass='WaterTubeActionTrigger']")
        self.assertEqual(trigger.get('Pos'),'10,20.2,30.6')
        self.assertEqual(trigger.find('Properties/Click').get('CannotWashReason'),'@waterTube_wash_max_text')
        ids={e.get('EntityId'):e for e in root}
        for node in (owner,trigger):
            for link in node.findall('EntityLinks/Link'):
                self.assertEqual(ids[link.get('TargetId')].get('EntityGuid'),link.get('TargetGuid'))
        rows=E.fromstring(files['tables/ai/scheduler.xml'])
        self.assertIsNotNone(rows.find(".//C_SmartHub[@EntityGuid='77']"))
        row=rows.find(f".//C_SmartHub[@EntityGuid='{guid_value(owner.get('EntityGuid'))}']")
        self.assertEqual(row.find('.//EffectClean').get('Role'),'washFace')
        animations=E.fromstring(files['tables/ai/smartobjectanimations.xml'])
        self.assertEqual(animations.find('.//SmartObjectAnimations').get('AllowRuntimeAnimValidationFallback'),'true')
        with self.assertRaisesRegex(ValueError,'already converted'):self.build(existing=files)

    def test_missing_visual_or_external_scheduler_dependencies_fail(self):
        with self.assertRaisesRegex(ValueError,'Missing converted wash tub visual'):self.build(missing=True)
        with self.assertRaisesRegex(ValueError,'dependency adapter'):self.build(external=True)


if __name__=='__main__':unittest.main()
