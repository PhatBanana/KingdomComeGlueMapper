import sys
from pathlib import Path
import unittest
import tempfile
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_import import behavior_path, import_quest, parse_behavior, parse_graph, resolve_null_tracking_edges, walk
from campaign_sources import MissingRetailSource


GRAPH = b'''<Graph><Nodes><Node Id="2" Class="Quest:Begin"><Inputs Name="q_test"/></Node>
<Node Id="5" Class="Quest:Objective"><Inputs Name="speakWithFather" IsHidden="0"/></Node>
</Nodes><Edges><Edge nodeOut="2" nodeIn="5" enabled="1"/>
<Edge nodeOut="0" nodeIn="5" enabled="0"/></Edges></Graph>'''


class QuestImportTests(unittest.TestCase):
    def test_runtime_editor_and_disconnected_nodes_are_separate(self):
        data = b'''<BehaviorTrees><BehaviorTree name="onUpdate"><Variables>
<Variable name="phase" type="_int" isPersistent="1" values="0"/></Variables>
<Root><Sequence><UnknownOperation code="keep this"/></Sequence></Root>
<ForestContainer><ExecuteLua code="disconnected"/></ForestContainer>
<EditorData><Root><ExecuteLua code="editor duplicate"/></Root></EditorData>
</BehaviorTree></BehaviorTrees>'''
        tree = parse_behavior(data, 'test')['onUpdate']
        self.assertEqual([n['op'] for n in walk(tree['root'])], ['Root', 'Sequence', 'UnknownOperation'])
        self.assertEqual(tree['disconnected'][0]['attributes']['code'], 'disconnected')
        self.assertEqual(tree['variables'][0]['isPersistent'], '1')

    def test_edges_and_unknown_sentinels_are_retained_not_rewired(self):
        graph = parse_graph(GRAPH, 'q_test')
        self.assertEqual(len(graph['edges']), 2)
        self.assertEqual(graph['unresolved_edges'], [graph['edges'][1]])
        self.assertEqual(graph['edges'][1]['enabled'], '0')
        with self.assertRaises(ValueError): parse_graph(GRAPH, 'different')
        with self.assertRaises(ValueError): parse_graph(GRAPH.replace(b'Id="5"', b'Id="2"'), 'q_test')

    def test_include_paths_cannot_escape_retail_namespace(self):
        self.assertEqual(behavior_path('"final/questUtils.xml"'), 'Libs/AI/final/questUtils.xml')
        for value in ('../file.xml', '/file.xml', 'C:/file.xml', 'file.lua'):
            with self.assertRaises(ValueError): behavior_path(value)

    def test_recursive_and_dynamic_includes_are_preserved_with_provenance(self):
        documents = {
            'Libs/Tables/quest/quest.xml': b'<database><table name="quest"><rows><row quest_id="7" quest_name="q_test"/><row quest_id="9" quest_name="other"/></rows></table></database>',
            'Libs/Tables/quest/quest_objective.xml': b'<database><table name="quest_objective"><rows><row quest_id="7" objective_id="5" objective_name="speakWithFather"/><row quest_id="9" objective_id="5" objective_name="other"/></rows></table></database>',
            'Libs/quests/flowgraphs/q_test.xml': GRAPH,
            'Libs/AI/quests/q_test.xml': b'''<BehaviorTrees><BehaviorTree name="onUpdate"><Root>
<IncludeTree File="final/shared.xml" Name="helper"/>
<IncludeTree File="$filename" Name="$tree"/>
<ExecuteLua code="System.DoThing()"/></Root></BehaviorTree></BehaviorTrees>''',
            'Libs/AI/quests/q_master_main.xml': b'<BehaviorTrees><BehaviorTree name="onUpdate"><Root/></BehaviorTree></BehaviorTrees>',
            'Libs/AI/final/shared.xml': b'''<BehaviorTrees><BehaviorTree name="helper"><Root>
<IncludeTree File="quests/q_test.xml" Name="onUpdate"/>
<IncludeTree File="final/shared.xml" Name="missing"/>
<IncludeTree File="final/shared.xml" Name="second"/>
</Root></BehaviorTree><BehaviorTree name="second"><Root>
<IncludeTree File="final/shared.xml" Name="helper"/>
</Root></BehaviorTree><BehaviorTree name="unrelated"><Root>
<IncludeTree File="quests/unrelated_region.xml" Name="start"/>
<EnableProfile profileEnable="unrelated_population"/>
</Root></BehaviorTree></BehaviorTrees>''',
        }
        def resolve(game, requested):
            return {label: dict(entry=entry, data=documents[entry], candidates=[{'archive': pak, 'sha256': 'fixture'}])
                    for label, (pak, entry) in requested.items()}
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp); (game / 'Data').mkdir()
            with zipfile.ZipFile(game / 'Data/Tables.pak', 'w') as archive:
                for entry, data in documents.items():
                    if entry.startswith('Libs/Tables/'): archive.writestr(entry, data)
            with patch('quest_import.retail_sources', side_effect=resolve):
                model, raw = import_quest(game, 'q_test')
                documents['Libs/Tables/quest/quest_objective.xml'] = documents['Libs/Tables/quest/quest_objective.xml'].replace(b'speakWithFather', b'wrong')
                renamed, _ = import_quest(game, 'q_test')
                self.assertEqual(renamed['graph']['objective_table_differences']['name_mismatches'],
                    [dict(id='5', graph='speakWithFather', table='wrong')])
                self.assertEqual(renamed['graph']['nodes']['5']['payload'][0]['attributes']['Name'], 'speakWithFather')
                self.assertEqual(renamed['tables']['quest_objective']['rows'][0]['objective_name'], 'wrong')
        self.assertEqual(len(raw), 5)
        self.assertEqual(model['quest_id'], '7')
        self.assertEqual(len(model['tables']['quest_objective']['rows']), 1)
        self.assertEqual(len(model['unresolved_includes']), 2)
        self.assertTrue(model['unresolved_includes'][0]['dynamic'])
        self.assertEqual(model['lua_sites'][0]['code'], 'System.DoThing()')
        self.assertFalse(model['executable'])
        self.assertEqual(model['behavior_documents']['libs/ai/final/shared.xml']['provenance'][0]['sha256'], 'fixture')
        self.assertEqual(set(model['behavior_documents']['libs/ai/final/shared.xml']['trees']), {'helper','second'})
        self.assertEqual(model['unreferenced_library_trees']['libs/ai/final/shared.xml'], ['unrelated'])

    def test_ambiguous_behavior_names_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_behavior(b'<BehaviorTrees><BehaviorTree name="x"><Root/></BehaviorTree><BehaviorTree name="x"><Root/></BehaviorTree></BehaviorTrees>', 'test')

    def test_dynamic_tree_selection_keeps_every_candidate_in_known_file(self):
        documents = {
            'Libs/Tables/quest/quest.xml': b'<database><table name="quest"><rows><row quest_id="7" quest_name="q_test"/></rows></table></database>',
            'Libs/quests/flowgraphs/q_test.xml': GRAPH,
            'Libs/AI/quests/q_test.xml': b'''<BehaviorTrees><BehaviorTree name="onUpdate"><Root>
              <IncludeTree File="final/shared.xml" Name="first"/>
              <IncludeTree File="final/shared.xml" Name="$chosenAtRuntime"/>
              </Root></BehaviorTree></BehaviorTrees>''',
            'Libs/AI/final/shared.xml': b'''<BehaviorTrees>
              <BehaviorTree name="first"><Root/></BehaviorTree>
              <BehaviorTree name="second"><Root/></BehaviorTree></BehaviorTrees>''',
            'Libs/Tables/quest/quest_objective.xml': b'<database><table name="quest_objective"><rows/></table></database>',
        }
        def resolve(game, requested):
            return {label:dict(entry=entry,data=documents[entry],candidates=[])
                    for label,(_,entry) in requested.items()}
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp);(game/'Data').mkdir()
            with zipfile.ZipFile(game/'Data/Tables.pak','w') as archive:
                for path,data in documents.items():
                    if path.startswith('Libs/Tables/'):archive.writestr(path,data)
            model,_=import_quest(game,'q_test',source_reader=resolve)
        self.assertEqual(set(model['behavior_documents']['libs/ai/final/shared.xml']['trees']), {'first','second'})
        self.assertEqual(len(model['unresolved_includes']),1)
        self.assertTrue(model['unresolved_includes'][0]['dynamic'])
        self.assertFalse(model['unreferenced_library_trees'])

    def test_database_dispatched_work_is_followed_and_missing_include_is_reported(self):
        documents = {
            'Libs/Tables/quest/quest.xml': b'<database><table name="quest"><rows><row quest_id="7" quest_name="q_test"/></rows></table></database>',
            'Libs/Tables/quest/quest_objective.xml': b'<database><table name="quest_objective"><rows><row quest_id="7" objective_id="5" objective_name="speakWithFather"/></rows></table></database>',
            'Libs/quests/flowgraphs/q_test.xml': GRAPH,
            'Libs/AI/quests/q_test.xml': b'''<BehaviorTrees><BehaviorTree name="onUpdate"><Root>
<SmartAreaBehaviorTag preferredBehaviors="arbitraryJob" preferredBehaviorsOnly="true"/>
</Root></BehaviorTree></BehaviorTrees>''',
            'Libs/Tables/ai/sa_behaviour_tag.xml': b'''<database><table><rows>
<row sa_behaviour_tag_name="arbitraryJob" tree_file="final/any_work.xml" tree_name="doWork"/>
</rows></table></database>''',
            'Libs/AI/final/any_work.xml': b'''<BehaviorTrees><BehaviorTree name="doWork"><Root>
<IncludeTree File="final/absent.xml" Name="helper"/>
</Root></BehaviorTree></BehaviorTrees>''',
        }
        def resolve(game, requested):
            result = {}
            for label, (pak, entry) in requested.items():
                if entry not in documents:
                    raise MissingRetailSource('Fixture missing ' + entry)
                result[label] = dict(entry=entry, data=documents[entry],
                                     candidates=[dict(archive=pak, sha256='fixture')])
            return result
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp); (game / 'Data').mkdir()
            with zipfile.ZipFile(game / 'Data/Tables.pak', 'w') as archive:
                for entry, data in documents.items():
                    if entry.startswith('Libs/Tables/'):
                        archive.writestr(entry, data)
            model, raw = import_quest(game, 'q_test', source_reader=resolve)
        self.assertIn('libs/ai/final/any_work.xml', model['behavior_documents'])
        self.assertIn('Libs/Tables/ai/sa_behaviour_tag.xml', raw)
        self.assertEqual(model['work_program_calls'][0]['candidates'][0]['tree'], 'doWork')
        self.assertFalse(model['work_program_calls'][0]['unresolved'])
        self.assertIn('libs/ai/final/absent.xml', model['missing_behavior_documents'])
        self.assertEqual(model['unresolved_includes'][0]['name'], 'helper')
        self.assertFalse(model['executable'])

    def test_null_asset_requires_exact_database_evidence(self):
        data = b'''<Graph><Nodes><Node Id="2" Class="Quest:Begin"><Inputs Name="q_test"/></Node>
<Node Id="9" Class="Quest:AssetPlace"/><Node Id="4" Class="Quest:Objective"/>
<Node Id="7" Class="Quest:AssetTracked"><Inputs MapAsset="9" TrackCnt="1" User="0" OnMap="1"/></Node>
</Nodes><Edges><Edge nodeOut="0" nodeIn="7" portOut="Out" portIn="Asset" enabled="1"/>
<Edge nodeOut="7" nodeIn="4" portOut="Objective" portIn="Tracked" enabled="1"/></Edges></Graph>'''
        row = dict(objective_id='4', quest_asset_id='', map_asset_id='9', count='1', user_id='0', on_map='True')
        graph = parse_graph(data, 'q_test')
        resolve_null_tracking_edges(graph, {'quest_tracked_asset': {'rows': [row]}})
        self.assertFalse(graph['unresolved_edges'])
        self.assertEqual(graph['edges'][0]['nodeOut'], '0')
        self.assertEqual(len(graph['null_tracking_edges']), 1)
        graph = parse_graph(data, 'q_test'); row['quest_asset_id'] = '9'
        resolve_null_tracking_edges(graph, {'quest_tracked_asset': {'rows': [row]}})
        self.assertEqual(len(graph['unresolved_edges']), 1)

    def test_null_tracking_uses_verified_runtime_marker_or_explicit_empty_placeholder(self):
        import copy
        data = b'''<Graph><Nodes><Node Id="2" Class="Quest:Begin"><Inputs Name="q_test"/></Node>
<Node Id="9" Class="Quest:AssetPlace"/><Node Id="4" Class="Quest:Objective"/>
<Node Id="7" Class="Quest:AssetTracked"><Inputs Asset="" MapAsset="9" TrackCnt="1" User="0" OnMap="1"/></Node>
</Nodes><Edges><Edge nodeOut="0" nodeIn="7" portOut="Out" portIn="Asset" enabled="1"/>
<Edge nodeOut="7" nodeIn="4" portOut="Objective" portIn="Tracked" enabled="1"/></Edges></Graph>'''
        row = dict(quest_id='42', objective_id='4', quest_asset_id='', map_asset_id='99', count='1', user_id='0', on_map='True')
        tables = dict(quest_tracked_asset=dict(rows=[row]), quest_asset=dict(rows=[dict(quest_id='42',quest_asset_id='99')]))
        g = parse_graph(data, 'q_test'); resolve_null_tracking_edges(g, tables)
        self.assertFalse(g['unresolved_edges'])
        self.assertEqual(g['null_tracking_edges'][0]['graph_map_asset'], '9')
        self.assertEqual(g['null_tracking_edges'][0]['runtime_map_asset'], '99')
        self.assertEqual(g['nodes']['7']['payload'][0]['attributes']['MapAsset'], '9')
        for change in ('missing_asset', 'wrong_quest', 'ambiguous_asset', 'ambiguous_tracking', 'counted_asset'):
            t = copy.deepcopy(tables)
            if change == 'missing_asset': t['quest_asset']['rows'] = []
            if change == 'wrong_quest': t['quest_asset']['rows'][0]['quest_id'] = 'other'
            if change == 'ambiguous_asset': t['quest_asset']['rows'] *= 2
            if change == 'ambiguous_tracking': t['quest_tracked_asset']['rows'] *= 2
            if change == 'counted_asset': t['quest_tracked_asset']['rows'][0]['quest_asset_id'] = '99'
            g = parse_graph(data, 'q_test'); resolve_null_tracking_edges(g, t)
            self.assertEqual(len(g['unresolved_edges']), 1, change)
        row.update(map_asset_id='', count='0'); tables['quest_asset']['rows'] = []
        null_data = data.replace(b'MapAsset="9" TrackCnt="1"', b'MapAsset="0" TrackCnt="0"')
        g = parse_graph(null_data, 'q_test'); resolve_null_tracking_edges(g, tables)
        self.assertFalse(g['unresolved_edges'])
        row['count'] = '1'
        g = parse_graph(null_data.replace(b'TrackCnt="0"', b'TrackCnt="1"'), 'q_test')
        resolve_null_tracking_edges(g, tables)
        self.assertEqual(len(g['unresolved_edges']), 1)

    def test_profile_transition_discovers_both_populations_and_their_work(self):
        documents = {
            'Libs/Tables/quest/quest.xml': b'<database><table name="quest"><rows><row quest_id="7" quest_name="q_test"/></rows></table></database>',
            'Libs/Tables/quest/quest_objective.xml': b'<database><table name="quest_objective"><rows><row quest_id="7" objective_id="5" objective_name="speakWithFather"/></rows></table></database>',
            'Libs/quests/flowgraphs/q_test.xml': GRAPH,
            'Libs/AI/quests/q_test.xml': b'<BehaviorTrees><BehaviorTree name="onUpdate"><Root><EnableProfile profileEnable="late" profileDisable="early"/></Root></BehaviorTree></BehaviorTrees>',
            'Libs/AI/custom/work.xml': b'<BehaviorTrees><BehaviorTree name="job"><Root/></BehaviorTree></BehaviorTrees>',
        }
        def resolve(game, requested):
            result = {}
            for label, (pak, entry) in requested.items():
                if entry not in documents: raise MissingRetailSource(entry)
                result[label] = dict(entry=entry,data=documents[entry],candidates=[dict(archive=pak,sha256='fixture')])
            return result
        def population(profiles, souls, documents, names, tables, world=None, native_person_brains=None):
            self.assertIsNotNone(world)
            return dict(profiles=names,actors=[],programs=[dict(file='Libs/AI/custom/work.xml',tree='job')])
        with tempfile.TemporaryDirectory() as temp:
            game=Path(temp)
            level=game/'Data/Levels/anywhere';level.mkdir(parents=True)
            with zipfile.ZipFile(game/'Data/Tables.pak','w') as archive:
                for name,data in documents.items():
                    if name.startswith('Libs/Tables/'): archive.writestr(name,data)
            with zipfile.ZipFile(level/'level.pak','w') as archive:
                archive.writestr('whdata_0','<Root/>')
                archive.writestr('whdata_1','<Root/>')
                archive.writestr('objects_mission0.xml','<Objects/>')
            with patch('campaign_profile_work.discover',side_effect=population) as discovered:
                model, _=import_quest(game,'q_test',source_reader=resolve,profile_level='anywhere')
            self.assertEqual(discovered.call_count,2)
            self.assertIs(discovered.call_args_list[0].kwargs['world'],
                          discovered.call_args_list[1].kwargs['world'])
            # Explicit builder selections use the same include traversal even
            # when no profile transition introduces them. Keep library scope.
            documents['Libs/AI/quests/q_test.xml'] = b'<BehaviorTrees><BehaviorTree name="onUpdate"><Root/></BehaviorTree></BehaviorTrees>'
            documents['Libs/AI/custom/work.xml'] = b'<BehaviorTrees><BehaviorTree name="job"><Root/></BehaviorTree><BehaviorTree name="unrelated"><Root/></BehaviorTree></BehaviorTrees>'
            with patch('campaign_profile_work.discover_selected', side_effect=population) as selected:
                explicit, _ = import_quest(game, 'q_test', source_reader=resolve,
                    profile_level='anywhere', actor_roots=['arbitraryActor'])
            self.assertEqual(selected.call_args.args[3], ['arbitraryActor'])
            self.assertEqual(set(explicit['behavior_documents']['libs/ai/custom/work.xml']['trees']), {'job'})
            self.assertEqual(len(explicit['profile_work_dependencies']), 1)
        self.assertEqual([r['profiles'] for r in model['profile_work_dependencies']],[['late'],['early']])
        self.assertIn('libs/ai/custom/work.xml',model['behavior_documents'])
        self.assertEqual(model['profile_work_provenance']['level'],'anywhere')
        self.assertEqual(len(model['profile_work_provenance']['documents']['whdata_0']),64)


if __name__ == '__main__': unittest.main()
