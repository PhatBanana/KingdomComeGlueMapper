import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_work_coverage import Ownership, assess, compound_targets


class WorkOwnershipTests(unittest.TestCase):
    def setUp(self):
        profiles = E.fromstring('''<Profiles>
          <GameProfile><Name>opening</Name><GameLayers><GameLayer>start</GameLayer></GameLayers></GameProfile>
          <GameProfile><Name>later</Name><GameLayers><GameLayer>later</GameLayer></GameLayers></GameProfile>
        </Profiles>''')
        docs = {'objects_mission0.xml': '<Objects><Entity Name="shared area" EntityId="1" EntityGuid="1" Pos="1,1,1"/></Objects>',
                'layers/start.xml': '<Objects><Entity Name="local" EntityId="2" EntityGuid="2"/></Objects>',
                'layers/later.xml': '<Objects><Entity Name="later chair" EntityId="3" EntityGuid="3" Pos="1,1,1"/></Objects>',
                'layers/unknown.xml': '<Objects><Entity Name="unowned" EntityId="4" EntityGuid="4"/></Objects>'}
        self.ownership = Ownership(profiles, docs)
        self.entry = dict(activity='work', area=dict(EntityId='1', EntityGuid='1'), source_link="Work[('Leader')]",
                          behavior=dict(sa_behaviour_tag_name='Leader'), target_links=[
                              dict(TargetId='3', TargetGuid='3', Name="compWork[srcBeh('Leader')]"),
                              dict(TargetId='2', TargetGuid='2', Name="compWork[srcBeh('Other')]"),
                              dict(TargetId='2', TargetGuid='2', Name='inside')])
        self.controller = E.fromstring('''<BehaviorTrees><BehaviorTree name="CompoundWork2_main"><Root>
          <GraphSearch Origin="&quot;t_compoundWorkplace&quot;" depth="&quot;1&quot;" SubGraph="&quot;compWork&quot;">
          <Gen2HasBehaviorFilter Condition="&quot;$compWork.srcBeh == $__behaviorName&quot;" BehaviorList="&quot;$compWork.behavior&quot;"/>
          </GraphSearch></Root></BehaviorTree></BehaviorTrees>''')

    def test_remote_candidates_do_not_become_local_job_from_actor_profile(self):
        result = assess(self.entry, self.ownership, ['opening'], compound=self.controller)
        self.assertEqual(result['ownership_status'], 'outside_selected_profiles')
        self.assertEqual([r['guid'] for r in result['resources']], ['3'])
        self.assertFalse(result['activates_job'])
        self.assertEqual(result['resources'][0]['profiles'], ['later'])

    def test_profile_change_changes_ownership_without_names_or_distances(self):
        result = assess(self.entry, self.ownership, ['opening', 'later'], compound=self.controller)
        self.assertEqual(result['resources'][0]['availability'], 'selected_profile')
        # Shared area alone still cannot prove a town-local dispatcher.
        self.assertEqual(result['ownership_status'], 'ownership_unresolved')

    def test_global_or_unowned_area_is_unknown_not_assumed_remote(self):
        for guid in ('1', '4'):
            entry = copy.deepcopy(self.entry)
            entry['area'] = dict(EntityId=guid, EntityGuid=guid)
            self.assertEqual(assess(entry, self.ownership, ['opening'])['ownership_status'], 'ownership_unresolved')

    def test_profile_owned_area_distinguishes_local_and_later(self):
        for guid, status in (('2', 'selected_profile_assignment'), ('3', 'outside_selected_profiles')):
            entry = copy.deepcopy(self.entry)
            entry['area'] = dict(EntityId=guid, EntityGuid=guid)
            self.assertEqual(assess(entry, self.ownership, ['opening'])['ownership_status'], status)

    def test_compound_filter_drift_fails_instead_of_selecting_every_link(self):
        self.controller.find('.//Gen2HasBehaviorFilter').set('Condition', 'true')
        with self.assertRaisesRegex(ValueError, 'selection contract'):
            compound_targets(self.entry, self.controller)

    def test_ambiguous_identity_and_id_disagreement_fail(self):
        with self.assertRaisesRegex(ValueError, 'disagree'):
            self.ownership.target('3', '2')
        self.ownership.by_guid[3].append(dict(self.ownership.by_guid[3][0]))
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.ownership.target('3')

    def test_audit_does_not_mutate_inputs(self):
        before = copy.deepcopy(self.entry)
        xml_before = E.tostring(self.controller)
        assess(self.entry, self.ownership, ['opening'], compound=self.controller)
        self.assertEqual(self.entry, before)
        self.assertEqual(E.tostring(self.controller), xml_before)


if __name__ == '__main__':
    unittest.main()
