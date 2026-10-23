import unittest
import xml.etree.ElementTree as E
from campaign_work_metaroles import resolve, register, partition, dispatch_proof, validate_dispatch, select_recordings


class WorkMetaroleTests(unittest.TestCase):
    def tables(self):
        return dict(role=[dict(role_id='17', role_name='source_role', metarole_id='8')],
            metarole=[dict(metarole_id='8', metarole_name='RENAMED_WORK')],
            soul2role=[dict(soul_id='a', role_id='17'), dict(soul_id='outside', role_id='17')],
            topictorole=[dict(topic_id='91', role_id='17'),dict(topic_id='92', role_id='17')],
            v_branch=[dict(start_topic='91',is_test='False'),dict(start_topic='92',is_test='True')])

    def test_membership_and_test_branch_filter(self):
        bindings, branches = resolve(self.tables(), {'a':'registered'}, ['RENAMED_WORK'])
        self.assertEqual(set(bindings), {'a'})
        self.assertEqual([b['start_topic'] for b in branches], ['91'])
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            resolve(self.tables(), {'a':'registered'}, ['guessed'])

    def test_registration_isolates_metaroles_and_keeps_source_soul_selection(self):
        bindings, _ = resolve(self.tables(), {'a':'registered'}, ['RENAMED_WORK'])
        files, roles, metas = register({'Libs/Storm/storm.xml':b'<storm><tasks><task name="roles"/></tasks></storm>'},
            bindings, {'a':'registered'}, [], 'gm_work')
        self.assertEqual(metas, {'RENAMED_WORK':'gm_work_RENAMED_WORK'})
        self.assertEqual(roles, {'source_role':'gm_work_17'})
        role=E.fromstring(files['Libs/Tables/rpg/role__gm_work.xml']).find('.//role')
        self.assertEqual(role.get('metarole_name'), metas['RENAMED_WORK'])
        rule=E.fromstring(files['Libs/Storm/roles/gm_work.xml'])
        self.assertEqual(rule.find('.//hasName').get('name'), 'registered')
        self.assertIsNone(rule.find('.//startDialogue'))

    def test_one_unknown_sequence_keeps_whole_connected_branch_pending(self):
        model=dict(alias='',topics={'1':dict(sequences=[dict(source=dict(sequence_id='1',timeout='0',flags='0')),
            dict(source=dict(sequence_id='2',timeout='10',flags='0'))])})
        ready,pending=partition({'91':model})
        self.assertFalse(ready)
        self.assertEqual(pending['91']['blockers'][0]['sequence'],'2')

    def model(self):
        return dict(start_topic='91',participants=[dict(topic_id='91',role_id='17')],
            roles={'17':dict(role_id='17',metarole_id='8')})

    def test_dispatch_requires_real_source_request_actor_membership_and_native_mode(self):
        bindings,_=resolve(self.tables(),{'a':'registered'},['RENAMED_WORK'])
        request=dict(type='dialog:monologRequest',target='this.id',values="metarole('RENAMED_WORK')")
        native=E.fromstring('<Root><Dialog><Dialogue Type="ingame monolog"/></Dialog></Root>')
        proof=dispatch_proof(self.model(),bindings,'RENAMED_WORK',request,native)
        validate_dispatch(self.model(),proof)
        for req,bnd in ((dict(request,values="metarole('OTHER')"),bindings),(request,{})):
            with self.assertRaises(ValueError):dispatch_proof(self.model(),bnd,'RENAMED_WORK',req,native)
        with self.assertRaisesRegex(ValueError,'mode is unverified'):
            dispatch_proof(self.model(),bindings,'RENAMED_WORK',request,E.Element('Root'))

    def test_shared_recordings_select_source_actor_voice_and_reject_missing_variant(self):
        model=dict(topics={'91':dict(sequences=[dict(lines=[dict(response=dict(role_id='17'),
            voices=[dict(voice_id='1',wave_file='one'),dict(voice_id='2',wave_file='two')])])])})
        memberships=[dict(soul_id='a',role_id='17')]
        selected=select_recordings(model,'a',[dict(soul_id='a',voice_id='2')],memberships)
        line=selected['topics']['91']['sequences'][0]['lines'][0]
        self.assertEqual(line['voices'],[dict(voice_id='2',wave_file='two')])
        self.assertEqual(len(model['topics']['91']['sequences'][0]['lines'][0]['voices']),2)
        with self.assertRaisesRegex(ValueError,'no unique recorded'):
            select_recordings(model,'a',[dict(soul_id='a',voice_id='9')],memberships)


if __name__=='__main__': unittest.main()
