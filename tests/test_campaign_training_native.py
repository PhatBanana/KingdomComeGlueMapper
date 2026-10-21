import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_training_native import assemble, settings, SOUL, SOULS
from campaign_dialogue_runtime import voice_namespace
from test_campaign_training_presentation import source
from test_campaign_training_curriculum import archive, PATH

SETTINGS='Quests/Final/Arbitrary/protections.xml'
HELPER='Quests/Final/Arbitrary/context.xml'


def fixture():
    files=source()
    files[SETTINGS]=f'''<Database><Skald><Module Name="Protections"><Ports>
      <Port Name="isactive" Direction="In" Type="bool"/>
      <Port Name="trainers" Direction="In" Type="{SOULS}"/></Ports><Nodes>
      <MakeArray Name="player" TypeT="{SOULS}"><Asset Name="A" Alias="protagonist"/></MakeArray>
      <BuffEffect Name="playerBuff"><Asset Name="Souls" Alias="protagonist"/>
        <Edge From="isactive" To="IsActive"/></BuffEffect>
      <Contexts Namespace="native" Name="one"><Edge From="isactive" To="isactive"/></Contexts>
      <Contexts Namespace="native" Name="two"><Edge From="isactive" To="isactive"/></Contexts>
      </Nodes></Module></Skald></Database>'''.encode()
    files[HELPER]=b'''<Database><Skald><Module Name="Contexts"><Ports>
      <Port Name="isactive" Direction="In" Type="bool"/></Ports><Nodes>
      <SetGameContext Name="scoped"><Constant Name="Context" Value="native_example"/>
      <Edge From="isactive" To="IsActive"/></SetGameContext>
      </Nodes></Module></Skald></Database>'''
    return files


class NativeLessonAssemblyTests(unittest.TestCase):
    def assemble(self,files):
        with archive(files) as z:
            return assemble(z,PATH,'Basic','GenericLesson',{'ARBITRARY_TUTOR':'local_tutor'},
                effect_roles={},settings_source=SETTINGS,
                settings_symbols={('native','Contexts'):HELPER},player_alias='protagonist')

    def test_complete_native_curriculum_is_wired_once_behind_lifecycle(self):
        files=fixture(); before=copy.deepcopy(files)
        generated,additions,report=self.assemble(files)
        self.assertEqual(files,before)
        root=E.fromstring(generated[report['root']])
        life=root.find('.//GenericLesson_lifecycle')
        self.assertEqual(life.find('Edge[@To="instruction_ack"]').get('From'),'GenericLesson_presentation.continue')
        self.assertEqual(life.find('Edge[@To="ack_phase"]').get('From'),'GenericLesson_lifecycle.phase')
        self.assertFalse(root.findall('.//Ports/*[@Name="instruction_ack"]'))
        self.assertFalse(root.findall('.//Ports/*[@Name="ack_phase"]'))
        output=root.find('.//Output')
        self.assertEqual(output.find('Edge[@To="finished"]').get('From'),'GenericLesson_lifecycle.finished')
        self.assertIsNotNone(root.find('.//Nodes/*[@Name="settings"]/Edge[@From="GenericLesson_lifecycle.training_active"]'))
        self.assertFalse(report['installed']); self.assertFalse(report['ready_for_game_test'])
        self.assertIn('workers_stopped',report['required_host_bindings'])
        self.assertIsNotNone(E.fromstring(additions).find('Objectives/*'))

    def test_native_settings_resolve_namespace_and_shared_helper_without_global_assets(self):
        with archive(fixture()) as z:
            files,name,evidence=settings(z,SETTINGS,'Settings',{('native','Contexts'):HELPER},'protagonist')
        self.assertEqual(len(files),2); self.assertEqual(len(evidence),2)
        root=E.fromstring(files[name+'.xml'])
        self.assertFalse(root.findall('.//Asset'))
        self.assertFalse(root.findall('.//*[@Namespace]'))
        self.assertEqual(len(root.findall('.//Definitions/Definition')),1)
        self.assertEqual(root.find('.//Ports/Port[@Name="gm_player"]').get('Type'),SOUL)
        self.assertEqual(root.find('.//Ports/Port[@Name="gm_player_souls"]').get('Type'),SOULS)
        self.assertEqual(root.find('.//SetGameContext'),None)

    def test_unresolved_namespace_and_actor_assets_fail_closed(self):
        for kind in ('namespace','asset','contract'):
            files=fixture(); r=E.fromstring(files[SETTINGS])
            if kind=='namespace': r.find('.//Contexts').set('Namespace','unknown')
            if kind=='asset': r.find('.//Asset').set('Alias','some_other_actor')
            if kind=='contract': r.find('.//Port[@Name="trainers"]').set('Type',SOUL)
            files[SETTINGS]=E.tostring(r)
            with self.subTest(kind=kind),self.assertRaises(ValueError): self.assemble(files)

    def test_audio_namespace_resolves_through_the_actual_module_instances(self):
        files,_,report=self.assemble(fixture())
        files['project.xml']=b'''<Database><Skald><Project Name="Project"><Definitions>
          <Definition File="quest.xml"/></Definitions><Nodes><Quest Name="Quest"/></Nodes>
          </Project></Skald></Database>'''
        files['quest.xml']=b'''<Database><Skald><Quest Name="Quest"><Definitions>
          <Definition File="GenericLesson.xml"/></Definitions><Nodes><GenericLesson Name="GenericLesson"/></Nodes>
          </Quest></Skald></Database>'''
        for path in report['presentation']['dialogue_sources']:
            name=E.fromstring(files[path]).find('./Skald/*').get('Name')
            self.assertEqual(voice_namespace(files,path),('Quest',name))

    def test_cyclic_helper_dependencies_are_rejected(self):
        files=fixture(); r=E.fromstring(files[HELPER])
        E.SubElement(r.find('.//Nodes'),'Protections',Name='cycle',Namespace='native')
        files[HELPER]=E.tostring(r)
        with archive(files) as z,self.assertRaisesRegex(ValueError,'Cyclic'):
            settings(z,SETTINGS,'Settings',{('native','Contexts'):HELPER,
                ('native','Protections'):SETTINGS},'protagonist')


if __name__=='__main__':unittest.main()
