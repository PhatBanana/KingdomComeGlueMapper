import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_training_presentation import build, wire, recordings
from test_campaign_training_curriculum import fixture, archive, PATH, InstructionGraph
from test_dialogue_dubbing import ogg


def source():
    files = fixture()
    for i in range(3):
        p = f'Quests/Final/Arbitrary/phase{i}.xml'; r = E.fromstring(files[p])
        r.find('.//State').set('TypeT', 'Progress')
        files[p] = E.tostring(r)
    p = 'Quests/Final/Arbitrary/phase1.xml'; r = E.fromstring(files[p])
    n = E.SubElement(r.find('.//Nodes'), 'LessonGoal', Name='visual', RequiredForOutput='original_world')
    E.SubElement(n, 'Edge', From='active.State', To='Progress'); files[p] = E.tostring(r)
    files['Quests/Final/Arbitrary.xml'] = b'''<Database><Skald><Quest Name="NativeParent">
      <Objectives><Objective Name="LessonGoal" TypeT="Progress"><LocalizedName StringName="native_goal"/></Objective></Objectives>
    </Quest></Skald></Database>'''
    return files


class NativePresentationTests(unittest.TestCase):
    def build(self, files=None, **kw):
        with archive(files or source()) as z:
            return build(z, PATH, 'Basic', 'ConvertedLesson', {'ARBITRARY_TUTOR':'converted_tutor'}, **kw)

    def test_imports_actual_ui_tracker_and_dialogues_without_double_dispatch(self):
        files=source(); before=copy.deepcopy(files)
        generated, additions, report=self.build(files)
        self.assertEqual(before,files)
        self.assertEqual(len(report['dialogue_sources']),3)
        aliases=[]; tutorials=[]
        for blob in generated.values():
            root=E.fromstring(blob)
            self.assertFalse(root.findall('.//Edge[@To="EnqueueDialogue"]'))
            aliases += [d.get('Alias') for d in root.iter('Decision') if d.get('Alias')]
            tutorials += [c.get('Value') for c in root.findall('.//DisplayTutorial/Constant[@Name="Tutorial"]')]
        self.assertEqual(sorted(aliases),['native_chain_3','native_draw_0','native_zone_7'])
        self.assertEqual(sorted(tutorials),['Native_chain_3','Native_draw_0','Native_zone_7'])
        self.assertIsNotNone(E.fromstring(additions).find('Objectives/Objective[@Name="ConvertedLesson_LessonGoal"]'))
        self.assertIn('ConvertedLesson_LessonGoal',generated['ConvertedLesson_phase_1.xml'].decode())

    def test_bound_souls_are_local_and_native_voices_retained(self):
        files=source(); p='Quests/Final/Arbitrary/instruction0.xml'; r=E.fromstring(files[p])
        selected=E.SubElement(r.find('.//Dialogue'),'SelectedSouls')
        E.SubElement(selected,'SelectedSoul',Role='ARBITRARY_TUTOR',Voice='NativeVoice',Language='ENG',Type='Wave')
        files[p]=E.tostring(r)
        generated,_,report=self.build(files)
        path=next(p for p,s in report['dialogue_sources'].items() if s.endswith('instruction0.xml'))
        selected=E.fromstring(generated[path]).find('.//SelectedSoul')
        self.assertEqual(selected.get('Soul'),'converted_tutor')
        self.assertEqual(selected.get('Voice'),'NativeVoice')
        self.assertFalse(any(p.startswith('Libs/') for p in generated))

    def test_only_explicitly_optional_unreferenced_barks_may_be_omitted(self):
        for connected in (False,True):
            files=source(); p='Quests/Final/Arbitrary/phase0.xml'; r=E.fromstring(files[p])
            E.SubElement(r.find('.//Definitions'),'Definition',File='crowd.xml')
            E.SubElement(r.find('.//Nodes'),'Crowd',Name='spectator')
            if connected:
                counter=E.SubElement(r.find('.//Nodes'),'State',Name='crowd_counter',TypeT='int')
                E.SubElement(counter,'Edge',From='spectator.ready',To='Increment')
            files[p]=E.tostring(r)
            files['Quests/Final/Arbitrary/crowd.xml']=b'<Database><Skald><Dialog Name="Crowd"><Dialogue><Response Role="CROWD"/></Dialogue></Dialog></Skald></Database>'
            with self.assertRaisesRegex(ValueError,'Unbound'): self.build(files)
            if connected:
                with self.assertRaisesRegex(ValueError,'Unbound'): self.build(files,optional_roles={'CROWD'})
            else:
                generated,_,report=self.build(files,optional_roles={'CROWD'})
                self.assertEqual(len(report['omitted_passive_barks']),1)
                self.assertNotIn('spectator',generated['ConvertedLesson_phase_0.xml'].decode())

    def test_native_instruction_release_and_cancellation_gate_continuation(self):
        generated,_,report=self.build()
        main=E.fromstring(generated[report['root']]); graph=InstructionGraph(E.tostring(main))
        graph.values.update(active=True,phase=0)
        graph.fire('step0.ready')
        self.assertNotIn('output.continue',graph.events)
        graph.fire('ConvertedLesson_phase_0.gm_instruction_released')
        self.assertIn('output.continue',graph.events)
        for values in (dict(active=False,phase=0),dict(active=True,phase=2)):
            graph=InstructionGraph(E.tostring(main)); graph.values.update(values)
            graph.fire('ConvertedLesson_phase_0.gm_instruction_released')
            self.assertNotIn('output.continue',graph.events)
        phase=E.fromstring(generated['ConvertedLesson_phase_0.xml'])
        waiter=phase.find('.//SceneFinishedWaiter')
        self.assertTrue(waiter.find('Edge').get('From').endswith('.AfterPlay'))
        self.assertIsNotNone(phase.find('.//State[@Name="gm_instruction_pending"]/Edge[@From="gm_stop"]'))
        self.assertIsNone(E.fromstring(generated['ConvertedLesson_phase_1.xml']).find('.//SceneFinishedWaiter[@Name="gm_instruction_release"]'))

    def test_cancellation_does_not_falsely_release_an_active_native_scene(self):
        generated,_,_=self.build()
        root=E.fromstring(generated['ConvertedLesson_phase_0.xml'])
        busy=next(n for n in root.findall('.//State') if n.get('Name').startswith('gm_talking_'))
        before=busy.find('Edge[@To="SetTrue"]').get('From')
        release=next(n for n in root.findall('.//SceneFinishedWaiter') if n.get('Name').startswith('gm_talking_'))
        root.find('./Skald/*').tag='Module'  # simulator accepts Module containers
        graph=InstructionGraph(E.tostring(root));graph.values['gm_active']=True
        graph.fire(before)
        self.assertTrue(graph.states[busy.get('Name')])
        graph.values['gm_active']=False
        graph.fire('gm_stop');graph.fire('gm_reset')
        self.assertTrue(graph.states[busy.get('Name')])
        cue=root.find('.//If[@Name="gm_live_instruction_cue"]/Edge[@To="Exec"]').get('From')
        graph.fire(cue)
        self.assertFalse(graph.states['gm_instruction_pending'])
        graph.fire(release.get('Name')+'.OnFinished')
        self.assertFalse(graph.states[busy.get('Name')])

    def test_stop_hides_tutorials_and_blocks_late_instruction_activation(self):
        generated,_,_=self.build()
        for i in range(3):
            root=E.fromstring(generated[f'ConvertedLesson_phase_{i}.xml'])
            ui=root.find('.//DisplayTutorial')
            self.assertIsNotNone(ui.find('Edge[@From="gm_stop"][@To="Hide"]'))
            self.assertTrue(ui.find('Edge[@To="Show"]').get('From').startswith('gm_live_'))
            state=root.find('.//State[@Name="active"]')
            self.assertTrue(state.find('Edge[@To="SetActive"]').get('From').startswith('gm_live_'))

    def test_effects_require_a_native_lesson_dependency_and_explicit_soul_binding(self):
        files=source(); root=E.fromstring(files[PATH]); nodes=root.find('.//Nodes')
        for name, activation in [('phase_buff','native.Phase'), ('active_buff','running.State'),
                                  ('unrelated','other.State'), ('constant_buff',None)]:
            effect=E.SubElement(nodes,'BuffEffect',Name=name)
            E.SubElement(effect,'Asset',Name='Souls',Alias='trainer')
            if activation: E.SubElement(effect,'Edge',From=activation,To='IsActive')
            else: E.SubElement(effect,'Constant',Name='IsActive',Value='true')
        E.SubElement(nodes,'State',Name='other',TypeT='bool')
        files[PATH]=E.tostring(root)
        with self.assertRaisesRegex(ValueError,'Unbound native lesson effect'): self.build(files)
        generated,_,_=self.build(files,asset_ports={'trainer':'tutor_souls'})
        main=E.fromstring(generated['ConvertedLesson.xml'])
        effects=main.findall('.//BuffEffect')
        self.assertEqual({n.get('Name') for n in effects},{'phase_buff','active_buff'})
        self.assertFalse(main.findall('.//Asset'))
        for effect in effects:
            self.assertEqual(effect.find('Edge[@To="Souls"]').get('From'),'tutor_souls')
            self.assertIsNotNone(effect.find('Edge[@To="IsActive"]'))

    def test_completion_wiring_distinguishes_cancellation_from_tutorial_end(self):
        nodes=E.Element('Nodes'); life=E.SubElement(nodes,'Life',Name='life'); present=E.SubElement(nodes,'Presentation',Name='present')
        wire(nodes,life,present)
        self.assertEqual(present.find('Edge[@To="finished"]').get('From'),'life.exercises_finished')
        self.assertEqual(present.find('Edge[@To="stop"]').get('From'),'life.stop_workers')
        before=E.tostring(nodes)
        with self.assertRaisesRegex(ValueError,'already'): wire(nodes,life,present)
        self.assertEqual(before,E.tostring(nodes))

    def test_recordings_resolve_inherited_native_voice_without_global_actor_changes(self):
        files=source()
        for i in range(3):
            p=f'Quests/Final/Arbitrary/instruction{i}.xml'; r=E.fromstring(files[p])
            E.SubElement(r.find('.//Response'),'Text',StringName='line_'+str(i))
            files[p]=E.tostring(r)
        generated,_,report=self.build(files); before=copy.deepcopy(generated)
        voices=b'<database><voices><voice voice_id="7" voice_technical_name="Original" abbreviation="orig"/></voices></database>'
        characters=b'<database><skald_characters><skald_character master_role_name="ARBITRARY_TUTOR" voice_id="7"/></skald_characters></database>'
        depot=E.Element('database');rows=E.SubElement(depot,'DialogueDubbingData')
        for i in range(3):E.SubElement(rows,'DialogueDubbing',FileHash=str(zlib.crc32(('orig_line_'+str(i)).encode())),Duration='1.5')
        def lookup(stem):return 'dialog/native/'+stem+'.ogg',ogg()
        changed,media,evidence=recordings(generated,report,voices,lookup,parent_namespace=('world','quest'),
            characters=characters,native_dubbing=E.tostring(depot))
        self.assertEqual(before,generated)
        self.assertEqual(len(media),3)
        self.assertTrue(all(n.startswith('dialog/world/quest/convertedlesson_dialog_') for n in media))
        for p in report['dialogue_sources']:
            r=E.fromstring(changed[p]);s=r.find('.//SelectedSoul')
            self.assertEqual((s.get('Soul'),s.get('Voice')),('converted_tutor','Original'))
            self.assertEqual(r.find('.//Response').get('ReferenceLength'),'1.500000')
        self.assertEqual(len(evidence),3)
        with self.assertRaisesRegex(ValueError,'dubbing index'):
            recordings(generated,report,voices,lookup,parent_namespace=('world','quest'),
                characters=characters,native_dubbing=b'<database/>')


if __name__ == '__main__': unittest.main()
