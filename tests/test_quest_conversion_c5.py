import copy
import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_scenes as scenes
from campaign_quest_graph import emit_project
from quest_lab.runner import Runner
from quest_lab.source import Source
from test_campaign_quest_graph import model as quest_model

QUEST = 'arbitrary_quest'
DOCUMENT = 'libs/ai/quests/' + QUEST + '.xml'
KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
GOLDEN = Path(__file__).parent / 'fixtures/quest_conversion/q_skalitz.c5.golden.json'
VIDEOS = {'a.pak': ['Videos/arbitrary_quest/cin_11_forge.usm', 'Videos/other/cin_1_x.usm'],
          'b.pak': ['Videos/arbitrary_quest/cin_12_visit.usm', 'Videos/arbitrary_quest/cin_13_spare.usm']}
CUTSCENES = b'<database><Cutscenes><RenderedCutscene Name="intro"/></Cutscenes></database>'
native = lambda guid: 'native-%d' % guid


def node(op, *children, **attributes):
    return dict(op=op, attributes={k: '"' + v + '"' for k, v in attributes.items()}, children=list(children), text='')


def message(values, kind='cutscene'):
    return dict(op='InstantSendMessageToNPC', attributes=dict(target='this.id', type=kind, values=values), children=[], text='')


def objective(name, function='CompleteObjective', quest=''):
    return node('SetQuestObjective', quest=quest, objective=name, function=function)


def tree(*children):
    return dict(root=node('Root', node('Behavior', node('Sequence', *children))))


def switch(enable, disable):
    return node('EnableProfile', profileEnable=enable, profileDisable=disable)


def loaded(profile, *children):
    return node('ProfileLoadedGate', *children, LayerName=profile, NegateTo='false', RunLogic='KeepRunning')


def source(visit=None):
    """A quest whose controller asks for two videos, an in-engine scene, a dialogue scene and a plain fade."""
    m = quest_model()
    update = tree(message("alias('forge'), state($enum:cutsceneState.doStart)"),
                  message("alias('visit'), saveGameQuest('q_next'), saveGameObjective('save')"),
                  message("alias('quarrel'), dialogFadeIn(true)"), message("alias ('talk'), dialogFadeIn(true)"),
                  message("alias('fade')"), message("name('spare')"), message("alias('forge')"),
                  message("add(true)", kind='daycycle:change'))
    visit = visit or tree(message("add(false)", kind='daycycle:change'), node('ExecuteLua', code='x()'),
                          objective('first', 'StartObjective'), switch('attack', 'normal'),
                          loaded('attack', switch('horses', 'house')),
                          loaded('horses', node('IncludeTree', File='lib.xml', Name='refresh')),
                          objective('second'),
                          node('QuestObjectiveGate', questName='q_next', objectiveName='save', objectiveState='Started',
                               NegateTo='false', RunLogic='KeepRunning'),
                          node('AddBuff', SoulWUID='__player', BuffGUID='g'), objective('returnHome'))
    m['behavior_documents'] = {
        DOCUMENT: dict(trees={'onUpdate': update, 'cutscene_forge': tree(message("add(true)", kind='daycycle:change'), objective('intro')),
                              'cutscene_visit': visit, 'cutscene_quarrel': tree(objective('first'))}),
        'libs/ai/final/lib.xml': dict(trees={'refresh': tree(node('Expression', expressions='$a = 1'))})}
    return m


def whdata():
    def profile(name, identity, layers, navigation='0'):
        return ('<GameProfile><Name>%s</Name><Id>%s</Id><HasNavigation>%s</HasNavigation><NeedsSVORebuild>0</NeedsSVORebuild>'
                '<GameLayers>%s</GameLayers></GameProfile>' % (name, identity, navigation,
                                                                 ''.join('<GameLayer>%s</GameLayer>' % l for l in layers)))
    return ('<Root><GameProfileManager><GameProfiles>' + profile('normal', 1, ['common', 'people', 'homes'], '1')
            + profile('attack', 2, ['common', 'raiders'], '1') + profile('horses', 3, ['given']) + profile('house', 4, ['decals'])
            + profile(QUEST + '_cutscene_quarrel', 5, ['cameras'])
            + '</GameProfiles><GameProfileGroups><Groups><Group><Profiles><Profile>4</Profile></Profiles></Group></Groups>'
              '</GameProfileGroups></GameProfileManager></Root>').encode()


def layers():
    entity = lambda guid, kind, name: dict(guid=guid, kind=kind, name=name)
    return dict(common=[entity(1, 'TagPoint', 'square')],
                people=[entity(10, 'NPC', 'smith'), entity(11, 'NPC_Female', 'mother'), entity(12, 'NPC', 'absent')],
                homes=[entity(20, 'SmartAreaShape', 'home'), entity(None, 'Object:Decal', None)],
                raiders=[entity(30, 'NPC', 'raider'), entity(31, 'Horse', 'horse')],
                given=[entity(40, 'Horse', 'gift')], decals=[entity(None, 'Object:Decal', None)], cameras=[entity(50, 'CameraSource', 'c')])


LEVEL = {'native-10', 'native-11', 'native-20', 'native-1'}


def converted(m=None, selection=('forge', 'visit')):
    return scenes.convert(m or source(), VIDEOS, whdata(), layers(), LEVEL, native, CUTSCENES, selection, 'helper.xml')


class SceneTests(unittest.TestCase):
    def test_every_request_is_categorised_from_the_data(self):
        result = converted()
        records = {r['alias']: r for r in result['records']}
        self.assertEqual({a: r['category'] for a, r in records.items()},
                         dict(forge='video', visit='video', spare='video', quarrel='in_engine', talk='dialogue', fade='fader'))
        self.assertEqual({a: r['status'] for a, r in records.items() if r['status'] == 'converted'}, dict(forge='converted', visit='converted'))
        self.assertEqual({a: r['residue'] for a, r in records.items() if r['status'] == 'residue'},
                         dict(spare='video_not_selected', quarrel='scene_handoff', talk='dialogue_scene', fade='fader_scene'))
        self.assertEqual(len(records['forge']['requests']), 2)
        self.assertEqual(records['forge']['video'], dict(archive='a.pak', entry='Videos/arbitrary_quest/cin_11_forge.usm', id='11'))
        self.assertEqual((records['forge']['callback'], records['talk']['callback']), ('cutscene_forge', None))
        self.assertEqual(result['ledger']['scenes']['requests'], 7)            # the daycycle message is not a scene
        self.assertEqual(result['ledger']['scenes']['categories'], dict(dialogue=1, fader=1, in_engine=1, video=3))

    def test_selection_must_be_requested_videos_and_videos_are_unique(self):
        with self.assertRaisesRegex(scenes.Unsupported, 'not requested videos: quarrel'):
            converted(selection=('forge', 'quarrel'))
        with self.assertRaisesRegex(scenes.Unsupported, 'Two source videos'):
            scenes.video_sources({'a': ['Videos/q/cin_1_x.usm'], 'b': ['videos/q/cin_2_x.usm']})

    def test_the_callback_program_keeps_source_order_and_never_drops_an_operation(self):
        found = scenes.program(source(), 'visit')
        kinds = [(s['kind'], s.get('op') or s.get('objective') or s.get('profile') or s.get('enable')) for s in found['steps']]
        self.assertEqual(kinds, [('deferred', 'InstantSendMessageToNPC'), ('deferred', 'ExecuteLua'), ('objective', 'first'),
                                 ('profile', 'attack'), ('await', 'attack'), ('await', 'horses'), ('objective', 'second'),
                                 ('deferred', 'QuestObjectiveGate'), ('deferred', 'AddBuff'), ('deferred', 'SetQuestObjective')])
        self.assertEqual(found['steps'][4]['steps'], [dict(kind='profile', enable='horses', disable='house', path='Root/0/0/4/0')])
        include = found['steps'][5]['steps'][0]
        self.assertEqual((include['op'], include['blocking'], include['owner']), ('IncludeTree', False, 'C2'))
        self.assertEqual(found['steps'][1]['owner'], 'C4')
        # The gate can block, so the objective action after it is not lowered ahead of it.
        self.assertTrue(found['steps'][7]['blocking'])
        self.assertEqual(found['steps'][9]['reason'], 'follows a deferred operation that can block')
        lowered = sum(v for k, v in found['counts'].items() if k != 'deferred')
        self.assertEqual(lowered + found['deferred_operations'], found['source_operations'])
        self.assertIsNone(scenes.program(source(), 'talk'))

    def test_only_plain_owned_operations_are_lowered(self):
        cases = [objective('nowhere'), objective('first', quest='q_other'), objective('first', 'ResetObjective'),
                 node('EnableProfile', profileEnable='same', profileDisable='same'), node('EnableProfile'),
                 node('ProfileLoadedGate', LayerName='attack', NegateTo='true', RunLogic='KeepRunning'),
                 node('ProfileLoadedGate', LayerName='attack', NegateTo='false', RunLogic='Halt')]
        for case in cases:
            with self.subTest(case=case['attributes']):
                found = scenes.program(source(tree(case)), 'visit')
                self.assertEqual([s['kind'] for s in found['steps']], ['deferred'])
        unknown = scenes.program(source(tree(node('IncludeTree', File='x.xml', Name='missing'), objective('first'))), 'visit')
        self.assertEqual([(s['kind'], s['blocking']) for s in unknown['steps']], [('deferred', True), ('deferred', False)])

    def test_a_wait_for_a_profile_that_is_never_switched_is_refused(self):
        with self.assertRaisesRegex(scenes.Unsupported, 'never switches: elsewhere'):
            converted(source(tree(loaded('elsewhere', objective('first')))))


class ControllerSeamTests(unittest.TestCase):
    def test_a_callback_the_controller_converter_owns_is_played_and_announced_but_not_lowered(self):
        result = scenes.convert(source(), VIDEOS, whdata(), layers(), LEVEL, native, CUTSCENES, ('forge', 'visit'), 'helper.xml',
                                controller_owned=('visit',))
        module = E.fromstring(result['module']).find('./Skald/Module')
        ports = [p.get('Name') for p in module.find('Ports')]
        self.assertEqual(ports, ['play_forge', 'callback_forge', 'complete_intro', 'finished_forge',
                                 'play_visit', 'callback_visit', 'finished_visit'])
        self.assertEqual([p['alias'] for p in result['programs']], ['forge'])
        self.assertEqual(result['plan'], {})                                  # its profiles are the controller's now
        self.assertFalse(module.findall('Nodes/streamprofileshandling'))
        self.assertEqual(result['report']['wiring'], [dict(port='complete_intro', quest=QUEST, input='complete_intro')])
        ledger = result['ledger']
        self.assertEqual([r for r in ledger['residue'] if r['kind'] == 'callback_handed_to_controller'],
                         [dict(kind='callback_handed_to_controller', alias='visit', tree='cutscene_visit', owner='C2')])
        self.assertEqual(ledger['residue_by_kind']['callback_op_deferred'], 1)
        files, _ = emit_project([source()], 'Example')
        quest = E.fromstring(files['Example/' + QUEST + '.xml']).find('./Skald/Quest')
        quest_ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest.find('Ports')}
        self.assertEqual(scenes.equivalence(source(), result, quest_ports)['verdict'], 'PASS')
        with self.assertRaisesRegex(scenes.Unsupported, 'not converted scenes: quarrel'):
            converted_owned = scenes.convert(source(), VIDEOS, whdata(), layers(), LEVEL, native, CUTSCENES, ('forge',), 'helper.xml',
                                             controller_owned=('quarrel',))


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.result = converted()
        self.module = E.fromstring(self.result['module']).find('./Skald/Module')
        self.nodes = {n.get('Name'): n for n in self.module.find('Nodes')}

    def edges(self, name):
        return [(e.get('From'), e.get('To')) for e in self.nodes[name].findall('Edge')]

    def test_ports_and_objective_actions_go_through_the_quest(self):
        ports = [(p.get('Name'), p.get('Direction'), p.get('Type')) for p in self.module.find('Ports')]
        self.assertEqual(ports, [(n, d, 'trigger') for n, d in (
            ('play_forge', 'In'), ('callback_forge', 'Out'), ('complete_intro', 'Out'), ('finished_forge', 'Out'),
            ('play_visit', 'In'), ('callback_visit', 'Out'), ('start_first', 'Out'), ('complete_second', 'Out'),
            ('finished_visit', 'Out'))])
        self.assertEqual(self.result['report']['wiring'], [dict(port=p, quest=QUEST, input=p)
                                                           for p in ('complete_intro', 'start_first', 'complete_second')])
        # No node of the module sets an objective or quest state by itself.
        self.assertFalse([n for n in self.nodes.values() if n.get('TypeT', 'bool') != 'bool'])

    def test_the_callback_follows_the_end_of_the_cutscene_once(self):
        self.assertEqual(self.nodes['scene_forge_play'].tag, 'CutsceneHandler')
        self.assertEqual(self.nodes['scene_forge_play'].find('Asset').attrib, dict(Name='CutsceneHolder', Alias='gm_arbitrary_quest_scene_forge'))
        self.assertEqual(self.edges('scene_forge_play'), [('play_forge', 'EnqueueCutscene')])
        self.assertEqual(self.edges('scene_forge_ended'), [('scene_forge_play.OnFinished', 'Exec'), ('scene_forge_pending.State', 'Condition')])
        self.assertEqual(self.edges('scene_forge_pending'), [('play_forge', 'SetTrue'), ('scene_forge_callback_0.A', 'SetFalse')])
        self.assertEqual(self.edges('Output')[:3], [('scene_forge_callback_0.B', 'callback_forge'),
                                                    ('scene_forge_callback_0.C', 'complete_intro'),
                                                    ('scene_forge_callback_0.D', 'finished_forge')])
        self.assertEqual(self.result['report']['world_requirements'][0],
                         dict(kind='CutsceneHolder', alias='gm_arbitrary_quest_scene_forge', cutscene='gm_arbitrary_quest_forge'))

    def test_profiles_switch_through_the_retail_helper_and_wait_for_its_acknowledgement(self):
        self.assertEqual({a.get('Name'): a.get('AssetProfiles') for a in self.module.findall('Assets/ProfileAsset')},
                         {'profile_%s_asset' % n: 'gm_' + n for n in ('attack', 'normal', 'horses', 'house')})
        self.assertEqual(self.module.find('Definitions/Definition').get('File'), 'helper.xml')
        self.assertEqual(self.edges('profile_attack'), [('scene_visit_callback_0.D', 'streamprofiles')])
        self.assertEqual(self.edges('profile_normal'), [('scene_visit_callback_0.E', 'unstreamprofiles')])
        self.assertEqual(self.edges('profile_attack_loaded'), [('profile_attack.onloaded', 'SetTrue'), ('profile_attack.onunloaded', 'SetFalse')])
        waits = sorted(n for n in self.nodes if n.startswith('scene_visit_wait_') and self.nodes[n].tag == 'State')
        first, second = waits
        self.assertEqual(self.edges(first + '_now'), [('scene_visit_callback_0.G', 'Exec'), ('profile_attack_loaded.State', 'Condition')])
        self.assertEqual(self.edges(first + '_later'), [('profile_attack.onloaded', 'Exec'), (first + '.State', 'Condition')])
        self.assertEqual(self.edges(first + '_then_0'), [(first + '_now.True', 'Exec'), (first + '_later.True', 'Exec')])
        self.assertEqual(self.edges('profile_horses'), [(first + '_then_0.B', 'streamprofiles')])
        self.assertEqual(self.edges(second + '_now')[1], ('profile_horses_loaded.State', 'Condition'))
        self.assertIn((second + '_then_0.B', 'complete_second'), self.edges('Output'))

    def test_attach_wires_only_declared_quest_inputs(self):
        m = source()
        files, _ = emit_project([m], 'Example')
        quest = E.fromstring(files['Example/' + QUEST + '.xml']).find('./Skald/Quest')
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest.find('Ports')}
        entry = scenes.attach(files['Example.xml'], self.result['module'], 'scenes.xml', self.result['report'], ports)
        quest_node = E.fromstring(entry).find('./Skald/Project/Nodes/' + QUEST)
        self.assertEqual([(e.get('From'), e.get('To')) for e in quest_node.findall('Edge')],
                         [('gm_arbitrary_quest_scenes.' + p, p) for p in ('complete_intro', 'start_first', 'complete_second')])
        with self.assertRaisesRegex(ValueError, 'already registered'):
            scenes.attach(entry, self.result['module'], 'other.xml', self.result['report'], ports)
        with self.assertRaisesRegex(ValueError, 'does not take the scene action'):
            scenes.attach(files['Example.xml'], self.result['module'], 'scenes.xml', self.result['report'], {})


class LabTests(unittest.TestCase):
    """Layer 2: the lowered scene in quest_lab, with the cutscene and the profile streaming as engine boundaries."""
    MODULE = 'gm_arbitrary_quest_scenes'

    def world(self):
        m = source()
        result = converted(m)
        files, _ = emit_project([m], 'Example')
        quest = E.fromstring(files['Example/' + QUEST + '.xml']).find('./Skald/Quest')
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest.find('Ports')}
        entry = E.fromstring(scenes.attach(files['Example.xml'], result['module'], 'scenes.xml', result['report'], ports))
        project = entry.find('./Skald/Project')
        # The scenario plays the controller: it asks for a scene through the entry's own ports.
        declared = E.SubElement(project, 'Ports')
        instance = project.find('Nodes/' + self.MODULE)
        for alias in ('forge', 'visit'):
            E.SubElement(declared, 'Port', Name='play_' + alias, Direction='In', Type='trigger')
            E.SubElement(instance, 'Edge', From='play_' + alias, To='play_' + alias)
        # The retail streaming helper is the engine boundary here: its file is present but not interpreted,
        # so each instance is a contracted node whose acknowledgements the scenario supplies.
        helper = b'<Database><Skald><Module Name="helper_not_interpreted"><Nodes/></Module></Skald></Database>'
        files = dict(files, **{'Example.xml': E.tostring(entry), 'scenes.xml': result['module'], 'helper.xml': helper})
        contracts = {}
        for alias in ('forge', 'visit'):
            contracts[self.MODULE + '.scene_' + alias + '_play'] = dict(
                reason='Cutscene playback is the engine: the scenario says when it ends, played or skipped',
                inputs=dict(EnqueueCutscene='trigger', CutsceneHolder='value'), outputs=dict(OnFinished='trigger'))
        for profile in ('attack', 'normal', 'horses', 'house'):
            contracts[self.MODULE + '.profile_' + profile] = dict(
                reason='Profile streaming is the engine: the scenario supplies the loaded acknowledgement',
                inputs=dict(streamprofiles='trigger', unstreamprofiles='trigger', profiles='value'),
                outputs=dict(onloaded='trigger', onunloaded='trigger'))
        return files, contracts

    def run_steps(self, steps):
        files, contracts = self.world()
        scenario = dict(schema=1, name='scene', entry='Example', contracts=contracts, steps=steps)
        return Runner(scenario, source=Source.blobs(files)).run()

    def state(self, **values):
        return dict(action='assert', values={QUEST + '.' + k: v for k, v in values.items()})

    def fire(self, port):
        return dict(action='fire', port=port)

    def end(self, alias):
        return self.fire(self.MODULE + '.scene_' + alias + '_play.OnFinished')

    def ack(self, profile, event='onloaded'):
        return self.fire(self.MODULE + '.profile_' + profile + '.' + event)

    def test_a_video_changes_nothing_until_it_ends_and_then_runs_its_callback_once(self):
        result = self.run_steps([
            self.fire('play_forge'), self.state(intro_Completed=False),
            self.end('forge'), self.state(intro_Completed=True),
            dict(action='assert', events={self.MODULE + '.callback_forge': 1, self.MODULE + '.finished_forge': 1}),
            # A second end with no new request (a stray engine event) does not run the callback again.
            self.end('forge'),
            dict(action='assert', events={self.MODULE + '.callback_forge': 1}),
            self.fire('play_forge'), self.end('forge'),
            dict(action='assert', events={self.MODULE + '.callback_forge': 2})])
        self.assertEqual(result['status'], 'PASS', result['error'])

    def test_an_end_without_a_request_is_ignored(self):
        result = self.run_steps([self.end('forge'), self.state(intro_Completed=False),
                                 dict(action='assert', events={self.MODULE + '.callback_forge': 0})])
        self.assertEqual(result['status'], 'PASS', result['error'])

    def visit(self, *acknowledgements):
        return self.run_steps([self.fire('play_visit'), self.end('visit'), *acknowledgements])

    def test_the_profile_acknowledgements_gate_the_rest_as_in_the_source(self):
        before = self.state(first_Started=True, second_Completed=False)
        after = self.state(first_Started=True, second_Completed=True)
        done = dict(action='assert', events={self.MODULE + '.finished_visit': 1})
        waiting = dict(action='assert', events={self.MODULE + '.finished_visit': 0})
        # Played through or skipped is the same boundary event, so both reach the same state.
        result = self.visit(before, waiting, self.ack('attack'), before, waiting, self.ack('horses'), after, done)
        self.assertEqual(result['status'], 'PASS', result['error'])
        # An unload acknowledgement of the profile that was switched off does not let the rest through.
        result = self.visit(self.ack('normal', 'onunloaded'), before, waiting)
        self.assertEqual(result['status'], 'PASS', result['error'])
        # A repeated acknowledgement does not run the rest twice.
        result = self.visit(self.ack('attack'), self.ack('attack'), self.ack('horses'), self.ack('horses'), after, done)
        self.assertEqual(result['status'], 'PASS', result['error'])

    def test_a_profile_that_is_already_loaded_does_not_wait(self):
        result = self.run_steps([self.ack('attack'), self.ack('horses'), self.fire('play_visit'),
                                 self.state(first_Started=False), self.end('visit'),
                                 self.state(first_Started=True, second_Completed=True),
                                 dict(action='assert', events={self.MODULE + '.finished_visit': 1})])
        self.assertEqual(result['status'], 'PASS', result['error'])

    def test_save_and_load_while_waiting_for_a_profile(self):
        result = self.run_steps([self.fire('play_visit'), self.end('visit'), dict(action='save', name='waiting'),
                                 self.ack('attack'), self.ack('horses'), self.state(second_Completed=True),
                                 dict(action='load', name='waiting'), self.state(second_Completed=False),
                                 self.ack('attack'), self.ack('horses'), self.state(second_Completed=True)])
        self.assertEqual(result['status'], 'PASS', result['error'])


class MovieTests(unittest.TestCase):
    def test_one_row_per_converted_video_and_native_rows_are_kept(self):
        result = converted()
        table = E.fromstring(result['table']).find('Cutscenes')
        self.assertEqual([r.get('Name') for r in table], ['intro', 'gm_arbitrary_quest_forge', 'gm_arbitrary_quest_visit'])
        row = table[1]
        self.assertEqual((row.get('Root'), row.find('Profiles/Profile').attrib),
                         ('Videos/gluemapper/arbitrary_quest/forge', dict(Type='Default', FileName='cinematic')))
        self.assertEqual(result['rows'][0], dict(name='gm_arbitrary_quest_forge', root='Videos/gluemapper/arbitrary_quest/forge',
            file='Videos/gluemapper/arbitrary_quest/forge/cinematic.bk2',
            source=dict(archive='a.pak', entry='Videos/arbitrary_quest/cin_11_forge.usm', id='11')))
        with self.assertRaisesRegex(ValueError, 'already registered'):
            scenes.movie_rows(result['table'], result['records'], QUEST)
        streams = [dict(codec_type='audio'), dict(codec_type='video', width=1920, height=1080, r_frame_rate='30/1')]
        self.assertEqual(scenes.media_expectation(streams, 451), dict(width=1920, height=1080, r_frame_rate='30/1', nb_frames='451'))


class ProfileTests(unittest.TestCase):
    def test_every_layer_and_entity_is_accounted(self):
        plan = converted()['plan']
        self.assertEqual(list(plan), ['attack', 'normal', 'horses', 'house'])
        normal = plan['normal']
        self.assertEqual([(l['layer'], l['status']) for l in normal['layers']], [('common', 'shared'), ('people', 'own'), ('homes', 'own')])
        self.assertEqual(normal['totals'], dict(layers=3, shared=1, entities=5, in_level=3, unconverted=2))
        self.assertEqual(normal['layers'][1]['move'], ['native-10', 'native-11'])
        self.assertEqual([(r['kind'], r.get('layer'), r.get('entities')) for r in normal['residue']],
                         [('profile_layer_unconverted', 'people', 1), ('profile_layer_unconverted', 'homes', 1), ('profile_nav_variant', None, None)])
        self.assertEqual(plan['attack']['totals'], dict(layers=2, shared=1, entities=2, in_level=0, unconverted=2))
        self.assertEqual(plan['attack']['layers'][1]['missing_kinds'], dict(Horse=1, NPC=1))
        self.assertEqual([r['kind'] for r in plan['house']['residue']], ['profile_layer_unconverted', 'profile_group_conflict'])
        for record in plan.values():
            own = [l for l in record['layers'] if l['status'] == 'own']
            self.assertEqual(sum(l['entities'] for l in own), record['totals']['in_level'] + record['totals']['unconverted'])

    def level(self):
        entity = lambda guid, name: '<Entity Name="%s" EntityGuid="native-%d" EntityClass="NPC" Pos="1,2,3" Rotate="1,0,0,0"/>' % (name, guid)
        return {'objects_mission0.xml': ('<Mission><Objects>' + entity(10, 'smith') + entity(11, 'mother') + entity(20, 'home')
                                         + entity(1, 'square') + entity(99, 'other') + '</Objects></Mission>').encode(),
                'leveldata.xml': b'<LevelData><Layers><Layer Name="old" Id="4" Specs="-1" Physics="0"/></Layers></LevelData>',
                'whdata_1': b'<Root><GameProfileManager><GameProfiles><GameProfile><Name>gm_old</Name><Id>7</Id></GameProfile>'
                            b'</GameProfiles></GameProfileManager></Root>'}

    def test_moving_changes_only_where_an_entity_lives(self):
        plan = converted()['plan']
        before = {e.get('EntityGuid'): dict(e.attrib) for e in E.fromstring(self.level()['objects_mission0.xml']).iter('Entity')}
        files, report = scenes.register_profiles(self.level(), plan)
        left = [e.get('Name') for e in E.fromstring(files['objects_mission0.xml']).iter('Entity')]
        self.assertEqual(left, ['square', 'other'])                        # the shared layer and unrelated entities stay flat
        layer = E.fromstring(files['layers/gm_normal_layer.xml'])
        self.assertEqual([e.get('Name') for e in layer], ['smith', 'mother', 'home'])
        for entity in layer:
            attributes = dict(entity.attrib)
            self.assertEqual(attributes.pop('Layer'), 'gm_normal_layer')
            self.assertEqual(attributes, before[entity.get('EntityGuid')])
        self.assertEqual(len(E.fromstring(files['layers/gm_attack_layer.xml'])), 0)
        level = E.fromstring(files['leveldata.xml'])
        self.assertEqual([(l.get('Name'), l.get('Id')) for l in level.find('Layers')],
                         [('old', '4'), ('gm_attack_layer', '5'), ('gm_normal_layer', '6'), ('gm_horses_layer', '7'), ('gm_house_layer', '8')])
        records = E.fromstring(files['whdata_1']).find('GameProfileManager/GameProfiles')
        self.assertEqual([(p.findtext('Name'), p.findtext('Id'), p.findtext('HasNavigation'), p.findtext('GameLayers/GameLayer'))
                          for p in records][1:],
                         [('gm_attack', '8', '0', 'gm_attack_layer'), ('gm_normal', '9', '0', 'gm_normal_layer'),
                          ('gm_horses', '10', '0', 'gm_horses_layer'), ('gm_house', '11', '0', 'gm_house_layer')])
        self.assertEqual([(r['profile'], r['moved']) for r in report], [('gm_attack', 0), ('gm_normal', 3), ('gm_horses', 0), ('gm_house', 0)])
        with self.assertRaisesRegex(ValueError, 'already registered'):
            scenes.register_profiles(files, plan)

    def test_a_missing_or_doubly_planned_entity_is_refused(self):
        plan = converted()['plan']
        level = self.level()
        level['objects_mission0.xml'] = level['objects_mission0.xml'].replace(b'native-11', b'native-12')
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            scenes.register_profiles(level, plan)
        twice = copy.deepcopy(plan)
        twice['attack']['layers'][1]['move'] = ['native-10']
        with self.assertRaisesRegex(ValueError, 'two profiles'):
            scenes.register_profiles(self.level(), twice)
        with self.assertRaisesRegex(scenes.Unsupported, 'Unknown source profiles'):
            scenes.profile_plan([('nowhere', None)], scenes.source_profiles(whdata()), layers(), LEVEL, native)


class LedgerTests(unittest.TestCase):
    def test_every_record_is_converted_or_typed_residue(self):
        ledger = converted()['ledger']
        self.assertEqual(ledger['residue_by_kind'], dict(callback_op_deferred=7, dialogue_scene=1, fader_scene=1,
            profile_group_conflict=1, profile_layer_unconverted=5, profile_nav_variant=2, request_save_deferred=2,
            scene_handoff=1, video_not_selected=1))
        self.assertEqual(ledger['lowered'], dict(objective=3, profile=2, **{'await': 2}))
        for callback in ledger['callbacks']:
            self.assertEqual(sum(callback['lowered'].values()) + callback['deferred_operations'], callback['source_operations'])
        self.assertEqual(len(ledger['scenes']['records']), ledger['scenes']['aliases'])
        self.assertFalse(ledger['runtime_verified'])
        golden = scenes.golden(ledger, converted()['module'], converted()['rows'])
        self.assertEqual(golden, json.loads(json.dumps(golden)))


@unittest.skipUnless((KCD1 / 'Data/Tables.pak').exists() and (KCD2 / 'Data/Tables.pak').exists(),
                     'requires installed KCD1 and KCD2 data')
class RetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scenes.convert_retail(KCD1, KCD2, 'q_skalitz')

    def test_golden_fixture(self):
        result = self.result
        golden = json.loads(json.dumps(scenes.golden(result['ledger'], result['module'], result['rows']), sort_keys=True))
        self.assertEqual(golden, json.loads(GOLDEN.read_text(encoding='utf-8')))

    def test_the_three_main_path_videos_and_their_callbacks(self):
        ledger = self.result['ledger']
        self.assertEqual(ledger['scenes']['converted'], ['navsteva_racka', 'kovani_otcem', 'forging_father_insert'])
        self.assertEqual((ledger['scenes']['requests'], ledger['scenes']['aliases']), (21, 15))
        self.assertEqual(ledger['scenes']['categories'], dict(dialogue=6, fader=1, in_engine=3, video=5))
        racek = ledger['callbacks'][0]
        self.assertEqual((racek['source_operations'], racek['lowered'], racek['deferred_operations']),
                         (27, dict(objective=2, profile=2, **{'await': 2}), 21))
        self.assertEqual([w['port'] for w in ledger['module']['wiring']],
                         ['start_unloadNormalSkalitz', 'complete_henryGetsTheSword', 'complete_fatherAndHenryMakeSword'])

    def test_every_source_operation_and_profile_entity_is_counted_once(self):
        ledger = self.result['ledger']
        for callback in ledger['callbacks']:
            self.assertEqual(sum(callback['lowered'].values()) + callback['deferred_operations'], callback['source_operations'])
        totals = {n: p['totals'] for n, p in ledger['profiles'].items()}
        self.assertEqual((totals['q_skalitz_attack']['layers'], totals['q_skalitz_attack']['shared'], totals['q_skalitz_attack']['entities']),
                         (9, 7, 88))
        self.assertEqual((totals['q_skalitz_normal']['layers'], totals['q_skalitz_normal']['shared']), (73, 7))
        pursuit = next(l for l in ledger['profiles']['q_skalitz_attack']['layers'] if l['layer'].startswith('pursuit'))
        self.assertEqual((pursuit['kinds']['NPC'], pursuit['kinds']['NPC_Female'], pursuit['kinds']['Horse']), (46, 16, 11))

    def test_objective_actions_are_real_inputs_of_the_emitted_quest(self):
        files, _ = emit_project([self.result['model']], 'Example')
        quest = E.fromstring(files['Example/q_skalitz.xml']).find('./Skald/Quest')
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest.find('Ports')}
        entry = scenes.attach(files['Example.xml'], self.result['module'], 'scenes.xml', self.result['report'], ports)
        self.assertEqual(len(E.fromstring(entry).findall('./Skald/Project/Nodes/q_skalitz/Edge')), 3)


if __name__ == '__main__':
    unittest.main()
