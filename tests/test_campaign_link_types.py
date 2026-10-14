from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as E

from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors
from campaign_dependencies import DependencyImporter, ImportPlan
from campaign_link_types import LinkTypeAdapter, data_expression, convert_world_links, link_definition
from campaign_ai_types import AITypeSource, AIStructureAdapter
from campaign_entity_links import native_guid


class Scalar:
    def plan(self, identity):
        if identity != 'string':
            raise ValueError('Unsupported test scalar')
        return ImportPlan()

    def convert(self, identity, plan, registered):
        return identity, {}, {}


class LinkTypeTests(unittest.TestCase):
    def test_link_data_write_uses_registered_type_and_preserves_local_rhs(self):
        with tempfile.TemporaryDirectory() as directory:
            types=AITypeSource(E.fromstring('<TypeDefinitions version="1"><Type name="reactionState"><Member name="expiration" type="int"/></Type></TypeDefinitions>'), [], 'Imported', directory)
            importer=DependencyImporter({'link_types':self.adapter(directory,
                '<LinkTag name="temporaryReaction" variableName="reactionData" type="reactionState"/>'),
                'ai_types':AIStructureAdapter(types)})
            model=source('<Root><LinkDataExpression From="&quot;this.id&quot;" To="&quot;__player&quot;" '
                'Expresssion="&quot;$reactionData.expiration = $timestamp&quot;"/></Root>')
            files,_,report=convert_behaviors([model],'Converted',catalog(),importer=importer)
            node=E.fromstring(next(iter(files.values()))).find('.//LinkDataExpression')
            self.assertEqual(node.get('Expresssion'),'$__link_imported_temporaryReaction.expiration = $timestamp')
            self.assertEqual(node.get('From'),'$this.id')
            self.assertEqual(node.get('To'),'$__player')
            self.assertEqual(report['whole_trees_emitted'],1)
            self.assertFalse(convert_behaviors([model],'Converted',catalog())[0])

    def test_contextual_work_fields_keep_their_source_names_and_types(self):
        with tempfile.TemporaryDirectory() as directory:
            types = AITypeSource(E.fromstring('''<TypeDefinitions version="1"><Type name="workRequest">
              <Member name="event" type="string"/><Member name="work" type="string"/>
              <Member name="priority" type="int"/><Member name="interrupt" type="bool"/>
              </Type></TypeDefinitions>'''), [], 'Imported', directory)
            importer = DependencyImporter({'link_types': self.adapter(directory,
                '<LinkTag name="Work" type="workRequest"/>'), 'ai_types': AIStructureAdapter(types)})
            self.assertEqual(link_definition("Work[event('questChanged'),work('sell'),priority(7),interrupt(true)]", importer),
                "imported_Work[event('questChanged'),work('sell'),priority(7),interrupt(true)]")
            for bad in ("Work[unknown('x')]", "Work[priority('seven')]", "Work[event('x'),1]",
                        "Work[priority(2147483648)]"):
                with self.subTest(label=bad), self.assertRaises(ValueError):
                    link_definition(bad, importer)
    def test_route_reservation_and_release_use_same_converted_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            importer = DependencyImporter({'link_types': self.adapter(directory,
                '<LinkTag name="reservation" persistent="0"/>')})
            model = source('''<Root><FuseBox><Child><Sequence>
              <AddLink From="&quot;route&quot;" To="&quot;this.id&quot;" Tag="&quot;reservation&quot;"
                       Data="&quot;&quot;" LinkOpHandleMode="&quot;Fail&quot;"/>
              <HandCheck who="&quot;this.id&quot;" LeftHand="&quot;left&quot;" RightHand="&quot;right&quot;"/>
              <GetPredefPathTraverseInfo ObjectWuid="&quot;this.id&quot;" PathWuid="&quot;route&quot;"
                 Out_DistToEnd="&quot;remaining&quot;" Out_DistToPath="&quot;distance&quot;" Out_ClosestPointOnPath="&quot;point&quot;"/>
              </Sequence></Child><OnFail><RemoveLink From="&quot;route&quot;" To="&quot;this.id&quot;"
                 Tag="&quot;reservation&quot;" RemoveAll="&quot;false&quot;" LinkOpHandleMode="&quot;Success&quot;"/>
              </OnFail></FuseBox></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog(), importer=importer)
            root = E.fromstring(next(iter(files.values())))
            self.assertEqual(root.find('.//AddLink').get('Tag'), "'imported_reservation'")
            self.assertEqual(root.find('.//OnFail/RemoveLink').get('Tag'), "'imported_reservation'")
            self.assertEqual(root.find('.//HandCheck').get('RightHand'), '$right')
            self.assertEqual(root.find('.//GetPredefPathTraverseInfo').get('PathWuid'), '$route')
            self.assertEqual(report['whole_trees_emitted'], 1)
    def adapter(self, path, extra=''):
        return LinkTypeAdapter(E.fromstring('''<LinkTagDefinitions version="1">
          <LinkTag name="StoryActor" type="string" persistent="1" ownershipIgnore="1"/>
          <LinkTag name="StoryPlace" type="string" variableName="placeData"/>
          ''' + extra + '</LinkTagDefinitions>'), E.fromstring('''<LinkTagDefinitions version="1">
          <LinkTag name="native_tag" persistent="1"/></LinkTagDefinitions>'''), 'Imported', path)

    def test_filter_imports_tag_and_changes_only_its_data_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            importer = DependencyImporter({'link_types': self.adapter(directory), 'ai_types': Scalar()})
            model = source('''<Root><GraphSearch Origin="&quot;owner&quot;">
              <LinkDataFilter tag="&quot;StoryActor&quot;" condition="&quot;$StoryActor == 'worker'&quot;"
                Child="&quot;worker&quot;" prune="&quot;true&quot;"/></GraphSearch></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog(), importer=importer)
            root = E.fromstring(next(iter(files.values())))
            node = root.find('.//LinkDataFilter')
            self.assertEqual(node.get('tag'), "'imported_StoryActor'")
            self.assertEqual(node.get('condition'), "$__link_imported_StoryActor == 'worker'")
            self.assertEqual(node.get('Child'), '$worker')
            self.assertEqual(report['whole_trees_emitted'], 1)
            importer.ensure('link_types', 'StoryPlace')
            merged = E.parse(importer.files['AI/LinkTagDefinitions.xml']).getroot()
            self.assertEqual({n.get('name') for n in merged}, {'native_tag', 'imported_StoryActor', 'imported_StoryPlace'})
            self.assertEqual(merged.find("LinkTag[@name='imported_StoryActor']").get('ownershipInclude'), '0')

    def test_invalid_pruning_and_missing_type_prevent_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.adapter(directory, '<LinkTag name="Pruned" defaultPruning="maybe"/>')
            importer = DependencyImporter({'link_types': adapter})
            self.assertIsNone(importer.ensure('link_types', 'Pruned'))
            self.assertIsNone(importer.ensure('link_types', 'StoryActor'))
            self.assertIsNone(importer.ensure('link_types', 'NotDeclared'))
            self.assertFalse(importer.registered['link_types'])
            self.assertFalse(importer.files)

    def test_home_inverse_preserves_default_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            importer = DependencyImporter({'link_types': self.adapter(directory,
                '<LinkTag name="Resident" defaultPruning="1" persistent="1"/>'
                '<LinkTag name="Home" autoInverse="Resident" persistent="1"/>')})
            self.assertEqual(importer.ensure('link_types', 'Home'), 'imported_Home')
            root = E.parse(importer.files['AI/LinkTagDefinitions.xml']).getroot()
            self.assertEqual(root.find("LinkTag[@name='imported_Resident']").get('defaultPruning'), '1')
            self.assertEqual(root.find("LinkTag[@name='imported_Home']").get('autoInverse'), 'imported_Resident')

    def test_link_data_symbol_is_token_aware_and_preserves_literals(self):
        self.assertEqual(data_expression("$data == '$data' | $database == $data.field", 'data', 'newtag'),
                         "$__link_newtag == '$data' | $database == $__link_newtag.field")

    def test_graph_masks_use_the_same_converted_names_as_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            importer = DependencyImporter({'link_types': self.adapter(directory), 'ai_types': Scalar()})
            model = source('''<Root><GraphSearch EdgePruning="&quot;parent,StoryPlace&quot;"
              AllowedEdges="&quot;StoryActor&quot;">
              <LinkTagFilter tag="&quot;StoryActor&quot;"/></GraphSearch></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog(), importer=importer)
            node = E.fromstring(next(iter(files.values()))).find('.//GraphSearch')
            self.assertEqual(node.get('EdgePruning'), "'parent,imported_StoryPlace'")
            self.assertEqual(node.get('AllowedEdges'), node.find('LinkTagFilter').get('tag'))
            self.assertEqual(report['whole_trees_emitted'], 1)
            model = source('<Root><GraphSearch AllowedEdges="&quot;$mask&quot;"/></Root>')
            files, _, report = convert_behaviors([model], 'Converted', catalog(), importer=importer)
            self.assertFalse(files)
            self.assertIn('Dynamic', report['trees'][0]['unresolved'][0]['reason'])

    def test_world_edges_preserve_cycles_data_and_missing_placements(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second, missing = (native_guid(i) for i in (1, 2, 3))
            importer = DependencyImporter({'link_types': self.adapter(directory), 'ai_types': Scalar()},
                {'entities': {first: first, second: second, missing: missing}})
            world = dict(entities={str(i): dict(attributes={'EntityGuid': format(i, '016X')}) for i in (1,2,3)},
                links=[{'from': '1', 'to': '2', 'source_link': {'Name': "StoryActor[('worker')]"}},
                       {'from': '2', 'to': '1', 'source_link': {'Name': ''}},
                       {'from': '1', 'to': '3', 'source_link': {'Name': "StoryPlace[work]"}}])
            links, report = convert_world_links(world, importer, {first, second})
            self.assertEqual(links, [(first, second, "imported_StoryActor['worker']"), (second, first, '')])
            self.assertEqual(len(report['pending']), 1)
            self.assertIn('not been placed', report['pending'][0]['reason'])
            self.assertFalse(report['runtime_validated'])

    def test_failed_filter_does_not_emit_a_partial_graph_search(self):
        model = source('<Root><GraphSearch><LinkDataFilter tag="&quot;Unknown&quot;" condition="&quot;true&quot;"/></GraphSearch></Root>')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)


if __name__ == '__main__':
    unittest.main()
