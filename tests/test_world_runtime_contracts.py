import tempfile
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_runtime_contracts import apply
from upgrade_map import xml


class WorldRuntimeContractsTests(unittest.TestCase):
    def test_merge_preserves_gameplay_data_and_is_idempotent(self):
        mission = b'''<Objects>
          <Entity Name="sa_land" EntityClass="SmartAreaShape" EntityId="1" EntityGuid="00000001-0000-0000" Pos="0,0,0"/>
          <Entity Name="person" EntityClass="NPC" EntityId="2" EntityGuid="00000002-0000-0000"/>
        </Objects>'''
        files = {'objects_mission0.xml':mission,
          'tables/ai/scheduler.xml':b'<database><Schedulers><C_SmartHub EntityGuid="2"/></Schedulers></database>',
          'waitinglinks.xml':b'''<StaticLinksInfo version="1"><WaitingLinks>
            <WaitingLink SourceId="00000002-0000-0000" TargetId="00000001-0000-0000">
              <LinkDefinition>_,schedulerWait</LinkDefinition><LinkDefinition>shopKeeper</LinkDefinition>
              <LinkDefinition>home</LinkDefinition>
            </WaitingLink></WaitingLinks></StaticLinksInfo>''',
          'whdata_0':b'existing quest and soul data', 'quest.xml':b'unchanged'}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        stream = Path(temporary.name)/'native.pak'
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('objects_mission0.xml','''<Objects>
              <Entity Name="PlayerLinkRerouter" EntityClass="TagPoint"><Properties bSaved_by_game="0"/></Entity>
              <Entity Name="hangoverSpotsHub" EntityClass="TagPoint"><Properties bSaved_by_game="0"/></Entity>
            </Objects>''')
            archive.writestr('whdata_0','<Root><SoulList><Souls><Soul><Player>1</Player><EntityGuid>00007777-0000-0000</EntityGuid></Soul></Souls></SoulList></Root>')
            archive.writestr('smartobjecthelpersetanimations.xml','<SmartObjectAnimationCollections/>')
        with zipfile.ZipFile(stream) as native:
            result, report = apply(files,native)
            again, _ = apply(result,native)
        for key in ('whdata_0','quest.xml','tables/ai/scheduler.xml'):
            self.assertEqual(result[key],files[key])
        self.assertEqual(result,again)
        waiting=ET.fromstring(result['waitinglinks.xml'])
        labels={e.text for e in waiting.iter('LinkDefinition')}
        self.assertEqual(labels,{'shopKeeper','home','playerLinkRerouter','hangoverSpotsHub'})
        self.assertEqual(waiting.find('StreamableTargets/StreamableTarget').get('TargetId'),'00007777-0000-0000')
        self.assertEqual(len(report['removed_authoring_links']),1)
        self.assertEqual(files['objects_mission0.xml'],mission)


if __name__ == '__main__': unittest.main()
