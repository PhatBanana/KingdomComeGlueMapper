import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from control_world_compile import compile_world
from campaign_entity_links import guid_value


class ControlWorldTests(unittest.TestCase):
    def fixture(self):
        mission = ET.fromstring('''<Objects>
          <Entity Name="land" EntityClass="SmartAreaShape" EntityGuid="00000001-0000-0000">
            <EntityLinks><Link Name="playerLinkRerouter" TargetGuid="00000004-0000-0000"/></EntityLinks>
          </Entity>
          <Entity Name="person" EntityClass="NPC" EntityGuid="00000002-0000-0000">
            <EntityLinks><Link Name="_,schedulerWait" TargetGuid="00000003-0000-0000"/>
            <Link Name="home" TargetGuid="00000001-0000-0000"/></EntityLinks>
          </Entity>
          <Entity Name="idle" EntityClass="TagPoint" EntityGuid="00000003-0000-0000">
            <EntityLinks><Link Name="^delegate" TargetGuid="00000001-0000-0000"/></EntityLinks>
          </Entity>
          <Entity Name="rerouter" EntityClass="TagPoint" EntityGuid="00000004-0000-0000"/>
        </Objects>''')
        souls = [ET.fromstring('<Soul><Player>1</Player><EntityGuid>00007777-0000-0000</EntityGuid></Soul>')]
        return mission, souls

    def test_compiled_links_resolve_delegate_and_player_without_leaking_scheduler_syntax(self):
        mission, souls = self.fixture()
        files = compile_world(mission, souls, 'control')
        waiting = ET.fromstring(files['waitinglinks.xml'])
        self.assertEqual({n.text for n in waiting.iter('LinkDefinition')}, {'home','playerLinkRerouter'})
        player_link = next(n for n in waiting.iter('WaitingLink') if n.findtext('LinkDefinition') == 'playerLinkRerouter')
        self.assertEqual(player_link.get('TargetId'), '00007777-0000-0000')
        self.assertEqual(waiting.find('StreamableTargets/StreamableTarget').get('TargetId'), player_link.get('TargetId'))
        activity = ET.fromstring(files['tables/ai/scheduler.xml']).find('.//S_ActivityLink')
        self.assertEqual(activity.get('TargetGuid'), str(guid_value('00000001-0000-0000')))
        self.assertEqual(activity.get('PositioningDelegate'), str(guid_value('00000003-0000-0000')))

    def test_unsupported_home_scheduler_is_not_silently_static(self):
        mission, souls = self.fixture()
        mission.find("Entity[@Name='person']/EntityLinks/Link").set('Name','_!home')
        with self.assertRaisesRegex(ValueError, 'Unsupported scheduler activity'):
            compile_world(mission, souls, 'control')

    def test_missing_destination_fails_before_packaging(self):
        mission, souls = self.fixture()
        mission.find("Entity[@Name='person']/EntityLinks/Link").set('TargetGuid','00000009-0000-0000')
        with self.assertRaisesRegex(ValueError, 'Unresolved entity link'):
            compile_world(mission, souls, 'control')


if __name__ == '__main__': unittest.main()
