from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_ai_types import AITypeSource, AIEnumAdapter, AIStructureAdapter
from campaign_behavior import BehaviorCompiler
from campaign_dependencies import DependencyImporter


SOURCE = '''<TypeDefinitions version="1">
  <Enum name="customState"><waiting value="-1"/><active value="4"/><done/></Enum>
  <Type name="customMessage"><Member name="enabled" type="bool">true</Member>
    <Type name="started"><Member name="source" type="common:wuid"/>
      <Member name="state" type="enum:customState">$enum:customState.waiting</Member>
    </Type>
  </Type>
  <Type name="customMessage"><Type name="finished"/></Type>
</TypeDefinitions>'''


def importer_at(path):
    source=AITypeSource(E.fromstring(SOURCE),[dict(archive='retail')],'DifferentCampaign',path)
    return source,DependencyImporter(dict(ai_types=AIStructureAdapter(source),ai_enums=AIEnumAdapter(source)))


class AITypeImportTests(unittest.TestCase):
    def test_nested_engine_message_members_use_native_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = AITypeSource(E.fromstring('''<TypeDefinitions version="1"><Type name="work">
              <Member name="sender" type="common:senderInfo"/>
              <Member name="behavior" type="common:senderInfo:senderInfoBehavior"/>
              </Type></TypeDefinitions>'''), [], 'AnyCampaign', Path(tmp))
            importer = DependencyImporter(dict(ai_types=AIStructureAdapter(source,
                ['senderInfo', 'senderInfo:senderInfoBehavior'])))
            self.assertEqual(importer.ensure('ai_types', 'work'), 'anycampaign:work')
            root = E.parse(next(iter(importer.files.values()))).getroot()
            self.assertEqual({n.get('Name'): n.get('Type') for n in root.findall('.//Member')},
                dict(sender='senderInfo', behavior='senderInfo:senderInfoBehavior'))
            self.assertEqual([n.get('Name') for n in root.findall('.//Type')], ['anycampaign', 'work'])

    def test_engine_alias_requires_installed_native_type_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, _ = importer_at(Path(tmp))
            importer = DependencyImporter(dict(ai_types=AIStructureAdapter(source, ['senderInfo'])))
            self.assertEqual(importer.ensure('ai_types', 'common:senderInfo'), 'senderInfo')
            self.assertIsNone(importer.ensure('ai_types', 'common:senderInfo:senderInfoBehavior'))
            self.assertFalse(importer.files)

    def test_work_structure_scalar_aliases_match_behavior_variable_scalars(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = AITypeSource(E.fromstring('''<TypeDefinitions version="1"><Type name="job">
              <Member name="count" type="_int">2</Member>
              <Member name="timestamp" type="_int64">4294967296</Member>
              <Member name="duration" type="_float">0.5</Member>
              <Member name="station" type="_wuid"/>
              </Type></TypeDefinitions>'''), [], 'AnyCampaign', Path(tmp))
            importer = DependencyImporter(dict(ai_types=AIStructureAdapter(source)))
            self.assertEqual(importer.ensure('ai_types', 'job'), 'anycampaign:job')
            root = E.parse(next(iter(importer.files.values()))).getroot()
            self.assertEqual({n.get('Name'): n.get('Type') for n in root.findall('.//Member')},
                             dict(count='int', timestamp='int64', duration='float', station='wuid'))

    def test_string_defaults_are_raw_text_and_not_enum_expressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = AITypeSource(E.fromstring('''<TypeDefinitions version="1"><Type name="work">
              <Member name="duration" type="string">1h</Member>
              <Member name="label" type="_string">$enum:literal.text &amp; 'quotes'</Member>
              </Type></TypeDefinitions>'''), [], 'AnyCampaign', Path(tmp))
            importer = DependencyImporter(dict(ai_types=AIStructureAdapter(source)))
            self.assertEqual(importer.ensure('ai_types','work'), 'anycampaign:work')
            root = E.parse(next(iter(importer.files.values()))).getroot()
            members = {n.get('Name'): n for n in root.findall('.//Member')}
            self.assertEqual(members['duration'].get('InitialValue'), '1h')
            self.assertEqual(members['label'].get('InitialValue'), "$enum:literal.text & 'quotes'")
            self.assertFalse(any(group=='ai_enums' for group, _ in importer.jobs))

    def test_serialized_enum_fills_missing_metadata_without_importing_engine_types(self):
        saved = E.fromstring('''<TypeDefinitions version="1">
          <enum name="animationOverride"><userControlled value="0"/>
            <dialogControlled value="1"/><noOverride value="2"/></enum>
          <Type name=""><Member name="opaque" type="int"/></Type>
          <Type name="gameVersion"><Member name="loaded" type="int"/></Type>
        </TypeDefinitions>''')
        with tempfile.TemporaryDirectory() as tmp:
            source, importer = importer_at(Path(tmp))
            source.add_serialized_enums(saved, [dict(archive='save-schema', sha256='evidence')])
            self.assertEqual(importer.ensure('ai_enums', 'animationOverride'),
                             'differentcampaign_animationOverride')
            job = importer.jobs[('ai_enums', 'animationoverride')]
            self.assertEqual(job['source']['provenance'][0]['archive'], 'save-schema')
            self.assertEqual([v['ordinal'] for v in job['source']['values']], [0, 1, 2])
            self.assertIsNone(importer.ensure('ai_types', 'gameVersion'))
            self.assertIsNone(importer.ensure('ai_enums', 'gameVersion'))

    def test_live_enum_ordinals_take_precedence_over_historical_save_schema(self):
        saved = E.fromstring('''<TypeDefinitions version="1">
          <enum name="customState"><waiting value="999"/></enum>
        </TypeDefinitions>''')
        with tempfile.TemporaryDirectory() as tmp:
            source, importer = importer_at(Path(tmp))
            source.add_serialized_enums(saved, [dict(archive='save-schema')])
            importer.ensure('ai_enums', 'customState')
            job = importer.jobs[('ai_enums', 'customstate')]
            self.assertEqual(job['source']['values'][0]['ordinal'], -1)
            self.assertEqual(job['source']['provenance'][0]['archive'], 'retail')

    def test_recursive_type_import_registers_parent_members_enum_and_ordinals(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,importer=importer_at(Path(tmp))
            target=importer.ensure('ai_types','customMessage:started')
            self.assertEqual(target,'differentcampaign:customMessage:started')
            self.assertEqual(importer.ensure('ai_types','customMessage:finished'),'differentcampaign:customMessage:finished')
            files={k:E.parse(v).getroot() for k,v in importer.files.items()}
            types=next(v for k,v in files.items() if 'ai_types__' in k)
            parent=types.find("Types/Type/Type[@Name='customMessage']")
            self.assertEqual(parent.find('Member').get('InitialValue'),'true')
            child=parent.find("Type[@Name='started']")
            self.assertEqual(child.find("Member[@Name='source']").get('Type'),'wuid')
            state=child.find("Member[@Name='state']")
            self.assertEqual(state.get('Type'),'enum:differentcampaign_customState')
            self.assertEqual(state.get('InitialValue'),'$enum:differentcampaign_customState.waiting')
            self.assertEqual(len(parent.findall('Type')),2)
            enums=next(v for k,v in files.items() if 'ai_enums__' in k)
            self.assertEqual([n.get('Value') for n in enums.findall('Enums/Enum/Value')],['-1','4','5'])

    def test_compiler_imports_missing_variable_type_and_enum_at_use_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,importer=importer_at(Path(tmp))
            compiler=BehaviorCompiler([], 'DifferentCampaign',dict(enum_types=[],variable_types=[],nodes={}),importer=importer)
            variable=compiler.variable(dict(name='message',type='customMessage:started',values='',form='single',isPersistent='1'))
            self.assertEqual(variable.get('type'),'differentcampaign:customMessage:started')
            self.assertEqual(variable.get('isPersistent'),'1')
            expr="$state = $enum:customState.active, $text = '$enum:unknown.literal'"
            self.assertEqual(compiler.typed_expression(expr),"$state = $enum:differentcampaign_customState.active, $text = '$enum:unknown.literal'")
            with self.assertRaisesRegex(ValueError,'Unknown source enum value'):
                compiler.typed_expression('$enum:customState.nonexistent')
            with self.assertRaisesRegex(ValueError,'no explicit type'):
                compiler.variable(dict(name='untyped',values=''))

    def test_engine_owned_unknown_types_do_not_become_empty_structures(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,importer=importer_at(Path(tmp))
            self.assertIsNone(importer.ensure('ai_types','missingEngineType'))
            self.assertNotIn('missingenginetype',importer.registered['ai_types'])

    def test_associative_variables_import_key_and_value_types_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,importer=importer_at(Path(tmp))
            compiler=BehaviorCompiler([], 'DifferentCampaign',dict(enum_types=[],variable_types=[],nodes={}),importer=importer)
            result=compiler.variable(dict(name='actors',type='common:wuid,customMessage:started',form='custom_associative',values=''))
            self.assertEqual(result.get('type'),'_wuid,differentcampaign:customMessage:started')
            self.assertEqual(result.get('form'),'custom_associative')
            self.assertNotIn(('ai_types','common:wuid,custommessage:started'),importer.jobs)
            result=compiler.variable(dict(name='byName',type='customMessage:started',form='associative',values=''))
            self.assertEqual(result.get('form'),'associative')
            with self.assertRaisesRegex(ValueError,'arity mismatch'):
                compiler.variable(dict(name='bad',type='_string',form='custom_associative'))

    def test_conflicting_source_fields_are_rejected(self):
        source=SOURCE.replace('<Type name="customMessage"><Type name="finished"/></Type>',
            '<Type name="customMessage"><Member name="enabled" type="int"/></Type>')
        with tempfile.TemporaryDirectory() as tmp,self.assertRaisesRegex(ValueError,'Conflicting'):
            AITypeSource(E.fromstring(source),[],'AnyCampaign',Path(tmp))


if __name__ == '__main__': unittest.main()
