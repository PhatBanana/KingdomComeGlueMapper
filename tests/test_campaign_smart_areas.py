from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_smart_areas import SmartAreaAdapter
from campaign_ai_registration import tree_identity
from campaign_dependencies import ImportPlan
from campaign_dependency_adapters import EntityAdapter
from campaign_entity_links import native_guid
from campaign_trigger_areas import TriggerArea, write_areas, read_areas
from campaign_smart_areas import area_bindings, source_geometry
from quest_import import ast
from test_campaign_ai_registration import setup, emitted


class Trees:
    def plan(self, identity):
        return ImportPlan()

    def convert(self, identity, plan, registered):
        _, path, tree = identity.split('|')
        return 'converted/' + path + '|' + bytes.fromhex(tree).decode(), {}, {}


class AreaRegistrationTests(unittest.TestCase):
    def test_xml_only_workplace_geometry_is_transformed_once(self):
        entity=E.fromstring('''<Entity EntityGuid="0000000000001234" Pos="10,20,30" Scale="2,2,3">
          <Area Height="2"><Points><Point Pos="0,0,0"/><Point Pos="1,0,0"/>
          <Point Pos="1,1,0"/></Points></Area></Entity>''')
        geometry=source_geometry(ast(entity))
        self.assertEqual(geometry.height,6)
        self.assertEqual(geometry.points,((10,20,30),(12,20,30),(12,22,30)))

    def test_unconverted_sibling_prevents_incomplete_area_registration(self):
        class MissingTree(Trees):
            def plan(self, identity):
                raise ValueError('unconverted source job')
        with tempfile.TemporaryDirectory() as directory:
            _,_,importer,_=self.configure(directory)
            importer.adapters['behavior_trees']=MissingTree()
            self.assertIsNone(importer.ensure('smart_areas','q_other|area'))
            self.assertFalse(importer.files)

    def test_placed_area_keeps_world_vertices_and_uses_registered_template(self):
        with tempfile.TemporaryDirectory() as directory:
            tables,native,importer,model=self.configure(directory)
            guid=native_guid(0x1234)
            entity=E.fromstring('''<Entity Name="AnyHome" EntityClass="SmartAreaShape"
              EntityGuid="0000000000001234" Pos="10,20,30"><Properties guidSmartAreaTemplate="area"
              bSaved_by_game="1" sWH_AI_EntityCategory="Home"><Script Misc=""/></Properties></Entity>''')
            record=dict(attributes=dict(entity.attrib),entity=ast(entity),source='objects_mission0.xml')
            world=dict(entities={'area':record})
            bindings={'q_other':dict(bindings=[dict(registration=dict(guid=guid))])}
            owners=area_bindings(bindings,world)
            shape=TriggerArea(0x1234,3,((10,20,30),(11,20,30),(11,21,30)))
            importer.adapters['entities']=EntityAdapter(world,E.fromstring('<Root/>'),write_areas([shape],7),7,
                smart_areas=owners)
            self.assertEqual(importer.ensure('entities',guid),guid)
            output=E.fromstring(importer.files['world/entities/'+guid+'.xml'])
            self.assertEqual(output.get('Pos'),'10,20,30')
            self.assertEqual(output.find('Properties').get('guidSmartAreaTemplate'),
                importer.registered['smart_areas']['q_other|area'])
            geometry=read_areas(importer.files['world/triggerareas/'+guid+'.fubar'])
            self.assertEqual(geometry['areas'][0].points,shape.points)

    def configure(self, directory):
        tables, native, importer, model = setup(directory)
        tables.rows.update(sa_smart_area=[dict(sa_smart_area_id='area',sa_smart_area_name='AnyWorkshop',
            brain_id='',priority='False')], sa_smart_area2sa_behaviour_tag=[dict(sa_smart_area_id='area',
            sa_behaviour_tag_id='job',priority='0')],sa_behaviour_tag=[dict(sa_behaviour_tag_id='job',
            sa_behaviour_tag_name='OriginalWork',tree_file='work/other.xml',tree_name='Work',
            on_enter_child_action='7',on_leave_action='7',on_success_action='8',on_fail_action='8')],
            sa_behaviour_action=[dict(sa_behaviour_action_id='7',sa_behaviour_action_name='keep'),
                                 dict(sa_behaviour_action_id='8',sa_behaviour_action_name='drop')])
        importer.adapters.update(smart_areas=SmartAreaAdapter(tables,native),behavior_trees=Trees())
        return tables,native,importer,model

    def test_area_keeps_names_and_dependencies_without_inventing_a_brain(self):
        with tempfile.TemporaryDirectory() as directory:
            tables,native,importer,_=self.configure(directory)
            target=importer.ensure('smart_areas','q_other|area')
            self.assertIsNotNone(target)
            root=E.fromstring(next(iter(importer.files.values())))
            template=root.find('.//SmartEntityTemplate')
            self.assertEqual(template.get('DatabaseId'),target)
            self.assertNotIn('BrainId',template.attrib)
            behavior=template.find('BehaviorTemplates/SmartBehaviorTemplate')
            self.assertEqual(behavior.get('Name'),'OriginalWork')
            self.assertEqual(behavior.get('MaxInstances'),'-1')
            self.assertEqual(behavior.find('TreeLocation').get('TreeName'),'Work')
            self.assertIn(('behavior_trees',tree_identity('q_other','work/other.xml','Work')),importer.jobs)

    def test_nondefault_lifetime_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            tables,native,importer,_=self.configure(directory)
            tables.rows['sa_behaviour_tag'][0]['on_leave_action']='8'
            self.assertIsNone(importer.ensure('smart_areas','q_other|area'))
            self.assertFalse(importer.files)

    def test_smart_area_subbrain_preserves_enter_exit_and_request_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            tables,native,importer,_=self.configure(directory)
            tables.rows['subbrain'][0]['subbrain_type']='3'
            tables.rows['subbrain_type'].append(dict(subbrain_type_id='3',subbrain_type_name='SmartArea'))
            native.tables['subbrain_type']['rows'].append(dict(subbrain_type_id='23',subbrain_type_name='SmartArea'))
            row=dict(subbrain_id='source-sub',file_name='work/callbacks.xml',on_enter_tree='Enter',
                on_exit_tree='Exit',on_request_tree='Request',on_release_tree='Release',on_update_tree='Update')
            tables.rows['subbrain_smart_area']=[row]
            native.tables['subbrain_smart_area']=dict(container='subbrain_smart_areas',attributes=dict(version='1'),
                row_tag='subbrain_smart_area',rows=[row])
            self.assertIsNotNone(importer.ensure('subbrains','q_other|source-sub'))
            converted=emitted(importer,'subbrain_smart_area')[0]
            for field in ('on_enter_tree','on_exit_tree','on_request_tree','on_release_tree','on_update_tree'):
                self.assertEqual(converted.get(field),row[field])
            self.assertEqual(emitted(importer,'subbrain')[0].get('subbrain_type'),'23')

    def test_empty_authored_default_uses_matching_native_empty_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            tables,native,importer,_=self.configure(directory)
            tables.rows['subbrain_smart_object'][0].update(file_name='default.xml',on_update_tree='')
            self.assertIsNotNone(importer.ensure('subbrains','q_other|source-sub'))
            row=emitted(importer,'subbrain_smart_object')[0]
            self.assertEqual(row.get('file_name'),'default.xml')
            self.assertFalse(row.get('on_update_tree'))
