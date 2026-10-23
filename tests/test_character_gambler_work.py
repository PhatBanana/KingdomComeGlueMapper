import copy
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

import character_gambler_work as work
from campaign_entity_links import native_guid
from character_city_benches import signature
from upgrade_map import xml
import test_character_city_work as city_fixture


class GamblerWorkTests(unittest.TestCase):
    def fixture(self):
        files,schedules=city_fixture.CityWorkTests().prepared();entry=schedules['person'][0]
        mission=E.fromstring(files['objects_mission0.xml'])
        mission.find("Entity[@Name='person']").set('EntityClass','NPC')
        files['objects_mission0.xml']=xml(mission)
        source=E.Element('Entity',entry['arrival'])
        def stage(*args):
            number=args[-1]
            table=E.Element('Entity',EntityId=str(number),EntityGuid=native_guid(700),
                            Name='gm_dice_'+source.get('EntityId')+'_table',Pos='1,2,3')
            E.SubElement(table,'EntityLinks')
            lean=E.Element('Entity',EntityId=str(number+1),EntityGuid=native_guid(701),
                Name='gm_dice_'+source.get('EntityId')+'_lean_host',Pos='2,3,4')
            row=E.Element('C_SmartHub',EntityGuid='700',IgnoreDeadEnds='false',StupidHub='false')
            activity=E.fromstring('''<S_ActivityLink TargetGuid="700" PositioningDelegate="0"><Parameters
              BehaviorName="use_opponent" BehaviorOverride="true" ProvidedRole="opponent" Priority="0"
              TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>''')
            return [table,lean],[row,E.Element('C_SmartHub',EntityGuid='701',IgnoreDeadEnds='false',StupidHub='false')],table,activity,{},dict(source_seats=[],runtime_verified=False)
        return files,entry,source,stage

    def test_preserves_clipped_work_clock_and_unrelated_quest_then_repeats(self):
        files,entry,source,stage=self.fixture()
        scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
        links=scheduler.find('Schedulers')[0].find('Links')
        links[0].find('Parameters').set('TimeOfDayStart','420')
        quest=copy.deepcopy(links[0]);quest.find('Parameters').set('Priority','50')
        quest.find('Parameters').set('RequiredRole','quest');quest.set('TargetGuid','999')
        links.append(quest);before=signature(quest)
        # A separate quest remains intact; it is not mistaken for owned work.
        files['tables/ai/scheduler.xml']=xml(scheduler)
        with patch.object(work,'resolve',return_value=(source,None,{})),patch.object(work,'stage',side_effect=stage):
            result,_,report=work.extend(files,'person',entry,None,None,None)
            repeated,_,_=work.extend(result,'person',entry,None,None,None)
        self.assertEqual(report['intervals'],[('420','720')])
        s=E.fromstring(result['tables/ai/scheduler.xml'])
        self.assertEqual(signature(s.find(".//S_ActivityLink[@TargetGuid='999']")),before)
        clock=[p for p in s.findall('.//S_ActivityLink/Parameters') if p.get('TimeOfDayStart')=='420' and p.get('Priority')=='0']
        self.assertTrue(clock)
        self.assertTrue(all(p.get('HaltOnInvalid')=='true' for p in clock))
        choices=[l for l in s.findall('.//S_ActivityLink') if l.find('Parameters').get('LinkTag')]
        self.assertEqual(len(choices),2)
        self.assertEqual({l.get('TargetGuid') for l in choices},{'700','701'})
        self.assertEqual({l.find('Parameters').get('InvertLinkTagRequirement') for l in choices},{'true','false'})
        branches={l.find('Parameters').get('InvertLinkTagRequirement'):l.find('Parameters') for l in choices}
        # The inverse branch can win before initial funds activation resolves.
        # Its tag becoming invalid must release leaning so dice can acquire.
        self.assertEqual(branches['true'].get('HaltOnInvalid'),'true')
        # Paying a stake can invalidate the funded tag mid-game; do not cancel
        # native dice ownership until its own round/result lifecycle finishes.
        self.assertEqual(branches['false'].get('HaltOnInvalid'),'false')
        self.assertEqual(result,repeated)

    def test_quest_override_on_same_job_is_rejected_without_mutation(self):
        files,entry,source,stage=self.fixture()
        scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
        scheduler.find('.//S_ActivityLink/Parameters').set('RequiredRole','quest')
        files['tables/ai/scheduler.xml']=xml(scheduler);before=dict(files)
        with patch.object(work,'resolve',return_value=(source,None,{})),patch.object(work,'stage',side_effect=stage):
            with self.assertRaisesRegex(ValueError,'quest or conditional'):
                work.extend(files,'person',entry,None,None,None)
        self.assertEqual(files,before)


if __name__=='__main__':unittest.main()
