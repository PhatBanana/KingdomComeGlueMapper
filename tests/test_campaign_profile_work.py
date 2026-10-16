import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_profile_work import discover, import_dependencies, ProfileWorld
from test_campaign_profile_actors import ProfileActorTests
from campaign_smart_areas import area_bindings


class ProfileWorkTests(unittest.TestCase):
    def test_native_person_services_do_not_import_an_unused_legacy_brain(self):
        class Tables:
            def row(self, *args): return {}
            def get(self, name): return {'rows': []}
        original = dict(entry_points=[dict(file='final/sb_daycycles.xml', tree='root')],
                        unresolved=[dict(reason='legacy combat subbrain')])
        ai = dict(source_brain={'brain_id': 'old', 'brain_name': 'npc_daycycle'})
        native = dict(brain_id='native-person', brain_name='npc_basic')
        with patch('campaign_profile_work.capture_person_ai', return_value=ai), \
             patch('campaign_profile_work.brain_definition', return_value=original), \
             patch('campaign_profile_work.plan', return_value={'resolved': [], 'pending': []}):
            result = discover(*ProfileActorTests().fixtures(), ['opening'], Tables(),
                              native_person_brains={'npc_daycycle': native})
        self.assertEqual(result['programs'], [])
        self.assertEqual(result['actors'][0]['native_brain'], native)
        self.assertEqual(result['actors'][0]['brain_dependencies'], original)

    def test_native_person_brain_must_match_actual_soul_registration(self):
        class Importer:
            def __init__(self, actual):
                self.calls = []
                self.jobs = {('souls', 'soul'): dict(evidence={'native_brain': actual})}
            def ensure(self, group, identity, site):
                self.calls.append(group)
                return identity
        population = dict(actors=[dict(actor=dict(soul_id='soul', entity_guid='10', profiles=['early']),
            source_brain={'brain_id': 'old'}, brain_dependencies={'unresolved': ['old combat type']},
            native_brain={'brain_id': 'native-person'}, schedule={'resolved': [], 'pending': []})], programs=[])
        models = [dict(quest='owner', profile_work_dependencies=[population])]
        for actual in ('native-person', 'wrong-person'):
            importer = Importer(actual)
            record = import_dependencies(models, importer)[0]
            self.assertNotIn('brains', importer.calls)
            self.assertEqual(record['brain'], actual if actual == 'native-person' else None)
            self.assertEqual(bool(record['brain_binding_error']), actual != 'native-person')

    def test_profile_world_index_reused_without_reparsing_documents(self):
        profiles, souls, documents = ProfileActorTests().fixtures()
        world = ProfileWorld(profiles, souls, documents)
        class Tables:
            def row(self, *args): return {}
            def get(self, name): return {'rows': []}
        with patch('campaign_profile_work.capture_person_ai', return_value={'source_brain': {'brain_id':'special'}}), \
             patch('campaign_profile_work.plan', return_value={'resolved': [], 'pending': []}), \
             patch('xml.etree.ElementTree.fromstring', side_effect=AssertionError('source reparsed')):
            early = discover(profiles, souls, documents, ['opening'], Tables(), world=world)
            late = discover(profiles, souls, documents, ['later'], Tables(), world=world)
        self.assertEqual(early['actors'][0]['actor']['soul_id'], 'early')
        self.assertEqual(late['actors'][0]['actor']['soul_id'], 'late')

    def test_work_area_registration_does_not_require_a_quest_asset(self):
        activity=dict(target_kind='smart_area',area={'EntityGuid':'10'},
                      area_template={'sa_smart_area_id':'TEMPLATE'})
        model=dict(quest='owner',profile_work_dependencies=[dict(actors=[dict(schedule=dict(resolved=[activity]))])])
        result=area_bindings({},dict(entities={}),[model])
        self.assertEqual(list(result.values()),[['owner|template']])

    def test_all_members_request_conversion_without_activating_profiles(self):
        class Importer:
            calls=[]
            def ensure(self,group,identity,site):
                self.calls.append((group,identity,site))
                return None if group=='brains' else 'converted-'+identity
        population=dict(actors=[dict(actor=dict(soul_id='soul',entity_guid='10',profiles=['early']),
            source_brain={'brain_id':'brain'},brain_dependencies={'unresolved':[]},
            schedule={'pending':[{'reason':'quest assignment'}]})],
            programs=[dict(file='Libs/AI/custom/job.xml',tree='Run',actors=['10'])])
        importer=Importer()
        result=import_dependencies([dict(quest='anyQuest',profile_work_dependencies=[population])],importer)
        self.assertEqual([c[0] for c in importer.calls],['souls','entities','brains','behavior_trees'])
        self.assertEqual(result[0]['profiles'],['early'])
        self.assertIsNone(result[0]['brain'])
        self.assertEqual(result[0]['pending_schedule'][0]['reason'],'quest assignment')
        self.assertFalse(result[0]['runtime_verified'])

    def test_profile_job_discovers_siblings_and_keeps_activation_owner(self):
        profiles, souls, documents = ProfileActorTests().fixtures()
        class Tables:
            def row(self, *args): return {'soul_id': args[-1]}
            def get(self, name):
                rows = {
                    'ai/sa_smart_area': [dict(sa_smart_area_id='yard')],
                    'ai/sa_smart_area2sa_behaviour_tag': [
                        dict(sa_smart_area_id='yard',sa_behaviour_tag_id=i) for i in ('job','release')],
                    'ai/sa_behaviour_tag': [dict(sa_behaviour_tag_id=i,sa_behaviour_tag_name=i,
                        tree_file='custom/'+i+'.xml',tree_name='Run') for i in ('job','release')],
                }
                return {'rows': rows.get(name, [])}
        ai = dict(source_brain={'brain_id':'source'},schedule=[],links=[])
        schedule = dict(resolved=[dict(target_kind='smart_area',behavior=dict(
            sa_behaviour_tag_id='job',tree_file='custom/job.xml',tree_name='Run'))],pending=[])
        with patch('campaign_profile_work.capture_person_ai',return_value=ai), \
             patch('campaign_profile_work.plan',return_value=schedule):
            result=discover(profiles,souls,documents,['opening'],Tables())
        self.assertEqual([r['actor']['soul_id'] for r in result['actors']], ['early'])
        self.assertEqual({r['file'] for r in result['programs']},
                         {'Libs/AI/custom/job.xml','Libs/AI/custom/release.xml'})
        self.assertTrue(all(r['actors']==['10'] for r in result['programs']))
        self.assertFalse(result['runtime_verified'])

    def test_unsupported_schedule_is_reported_without_inventing_a_job(self):
        class Tables:
            def row(self, *args): return {}
            def get(self, name): return {'rows':[]}
        with patch('campaign_profile_work.capture_person_ai',return_value={'source_brain':{'brain_id':'special'}}), \
             patch('campaign_profile_work.plan',side_effect=ValueError('unsupported activity')):
            result=discover(*ProfileActorTests().fixtures(),['later'],Tables())
        self.assertEqual(result['programs'],[])
        self.assertEqual(result['actors'][0]['unresolved'],'unsupported activity')
        self.assertEqual(result['actors'][0]['actor']['soul_id'],'late')


if __name__ == '__main__': unittest.main()
