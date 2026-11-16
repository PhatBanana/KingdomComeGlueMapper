"""Converter C2: ownership a controller grants, held by the quest's SetOwner effect."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_ownership as ownership
import campaign_quest_ownership as quest_side

DOCUMENT = 'libs/ai/quests/q_example.xml'
ASSETS = {"t_places['home']": dict(alias='q_home', asset_type='SmartAreaAsset'),
          "t_items['chest']": dict(alias='q_chest', asset_type='StashAsset'),
          "t_places['spot']": dict(alias='q_spot', asset_type='TagPointAsset')}


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def owner(objects="t_places['home']", **changes):
    return node('SetOwner', **dict(dict(Objects='"%s"' % objects, Owner='"__player"', MarkAsStolen='"false"'), **changes))


def loot(variable='chest', value='true'):
    return node('ExecuteLua', code='"XGenAIModule.GetEntityByWUID(data.%s):SetLootLegal(%s)"' % (variable, value))


def assign(text="$chest = $t_items['chest']"):
    return node('Expression', expressions='"%s"' % text)


def model(*steps):
    return dict(quest='q_example', behavior_documents={DOCUMENT: dict(trees=dict(
        entry=dict(variables=[], root=node('Root', [node('Sequence', steps)]))))})


def run(*steps):
    subject = model(*steps)
    report = ownership.apply(subject, ASSETS)
    return subject['behavior_documents'][DOCUMENT]['trees']['entry']['root']['children'][0]['children'], report


class ControllerTests(unittest.TestCase):
    def test_a_level_bound_object_becomes_a_signal_to_the_quest(self):
        steps, report = run(owner())
        self.assertEqual((steps[0]['op'], steps[0]['attributes'], steps[0]['source_op'], 'stand_in' in steps[0]),
                         ('OwnershipSignal', dict(module='q_example', port='own_home'), 'SetOwner', False))
        self.assertEqual(ownership.quest_assets(report), [dict(port='own_home', alias='q_home', asset_type='SmartAreaAsset')])

    def test_anything_the_effect_cannot_express_is_left_as_written(self):
        cases = [(owner('things[$i]'), 'object is found at run time'),
                 (owner(Owner='"t_actors[\'kunes\']"'), 'owner is not the player, or the object is marked stolen'),
                 (owner(MarkAsStolen='"true"'), 'owner is not the player, or the object is marked stolen'),
                 (owner(Extra='"1"'), 'fields outside Objects, Owner, MarkAsStolen'),
                 (owner("t_places['elsewhere']"), 'the level does not bind the object to one entity'),
                 (owner("t_places['spot']"), 'no retail SetOwner takes this class: TagPointAsset')]
        for step, reason in cases:
            steps, report = run(step)
            self.assertEqual((steps[0]['op'], [r['reason'] for r in report['left']], report['owned']), ('SetOwner', [reason], []))

    def test_loot_made_legal_on_a_level_stash_is_the_flagged_stand_in(self):
        steps, report = run(assign(), loot())
        self.assertEqual((steps[1]['op'], steps[1]['attributes']['port'], steps[1]['stand_in'], steps[1]['source_op']),
                         ('OwnershipSignal', 'own_chest', 'SetOwner', 'ExecuteLua'))
        self.assertEqual(steps[0]['op'], 'Expression')
        self.assertTrue(report['owned'][0]['stand_in'])

    def test_loot_on_an_object_only_known_at_run_time_is_left(self):
        reason = 'loot legality of an object found at run time'
        for steps_ in ([loot()], [loot(), assign()], [assign(), assign(), loot()], [assign('$chest = $found'), loot()],
                       [assign(), loot(value='false')], [assign("$other = $t_items['chest']"), loot()]):
            steps, report = run(*steps_)
            self.assertEqual(([s['op'] for s in steps], {r['reason'] for r in report['left']}),
                             ([s['op'] for s in steps_], {reason}))
        entity = node('ExecuteLua', code='"entity.SetLootLegal(true)"')
        self.assertEqual(run(entity)[1]['left'][0]['reason'], reason)
        wrapper = node('LuaWrapper', [node('Success')], onEnter='"entity.SetLootLegal(true)"', onExit='"entity.SetLootLegal(false)"')
        steps, report = run(wrapper)
        self.assertEqual((steps[0]['op'], [(r['operation'], r['reason']) for r in report['left']]),
                         ('LuaWrapper', [('LuaWrapper', reason)]))
        # Assigned a second time elsewhere in the tree: not one object.
        steps, report = run(node('Sequence', [assign('$chest = $found')]), assign(), loot())
        self.assertEqual(report['owned'], [])

    def test_two_objects_cannot_share_a_port(self):
        assets = dict(ASSETS, **{"t_other['home']": dict(alias='q_other', asset_type='StashAsset')})
        subject = model(owner(), owner("t_other['home']"), owner())
        report = ownership.apply(subject, assets)
        self.assertEqual(([s['alias'] for s in report['owned']], [r['reason'] for r in report['left']]),
                         (['q_home', 'q_home'], ['port name is taken: own_home']))
        self.assertEqual(len(ownership.quest_assets(report)), 1)

    def test_the_signal_is_a_bridge_action_on_the_quest_port(self):
        class Bridge:
            actions = {}
            def _name(self, kind, quest, port): return '_'.join((kind, quest, port))
        class Compiler: bridge = Bridge()
        emitted = ownership.LOWERINGS['OwnershipSignal'](Compiler, node('OwnershipSignal', module='q_example', port='own_home'), 'q_example')
        self.assertEqual(emitted.tag, 'SendAIConceptSignal_action_q_example_own_home')
        self.assertEqual(Bridge.actions['action_q_example_own_home'],
                         dict(kind='action', quest='q_example', port='own_home', source_operation='OwnershipSignal',
                              name='action_q_example_own_home'))


QUEST = (b'<Database Name="brambora"><Skald><Quest Name="q_example"><Ports>'
         b'<Port Name="start" Direction="In" Type="trigger" /></Ports><Nodes /></Quest></Skald></Database>')
ROWS = dict(q_example=[dict(port='own_home', alias='q_home', asset_type='SmartAreaAsset'),
                       dict(port='own_chest', alias='q_chest', asset_type='StashAsset')])


class QuestTests(unittest.TestCase):
    def test_the_quest_holds_the_retail_effect_behind_a_latched_port(self):
        blob, report = quest_side.bind(QUEST, dict(quest='q_example'), dict(owned_assets=ROWS, player_asset='player'))
        quest = ET.fromstring(blob).find('./Skald/Quest')
        self.assertEqual([(p.get('Name'), p.get('Direction'), p.get('Type')) for p in quest.find('Ports')][1:],
                         [('own_home', 'In', 'trigger'), ('own_chest', 'In', 'trigger')])
        latch = quest.find("Nodes/State[@Name='lowered_own_own_home']")
        effect = quest.find("Nodes/SetOwner[@Name='lowered_own_own_home_effect']")
        self.assertEqual((latch.get('TypeT'), latch.find('Constant').attrib, latch.find('Edge').attrib),
                         ('bool', dict(Name='DefaultValue', Value='false'), dict(From='own_home', To='SetTrue')))
        self.assertEqual(([a.attrib for a in effect.findall('Asset')], effect.find('Edge').attrib),
                         ([dict(Name='What', Alias='q_home'), dict(Name='Who', Alias='player')],
                          dict(From='lowered_own_own_home.State', To='IsActive')))
        self.assertEqual(len(quest.findall('Nodes/SetOwner')), 2)
        self.assertEqual([r['what'] for r in report['converted']], ['q_home', 'q_chest'])

    def test_nothing_changes_without_rows_or_without_the_player(self):
        self.assertEqual(quest_side.bind(QUEST, dict(quest='q_example'), dict(player_asset='player'))[0], QUEST)
        self.assertEqual(quest_side.bind(QUEST, dict(quest='q_other'), dict(owned_assets=ROWS, player_asset='player'))[0], QUEST)
        blob, report = quest_side.bind(QUEST, dict(quest='q_example'), dict(owned_assets=ROWS))
        self.assertEqual((blob, len(report['pending'])), (QUEST, 2))

    def test_a_taken_port_a_second_run_or_a_foreign_class_is_refused(self):
        bindings = dict(owned_assets=ROWS, player_asset='player')
        blob, _ = quest_side.bind(QUEST, dict(quest='q_example'), bindings)
        with self.assertRaises(ValueError): quest_side.bind(blob, dict(quest='q_example'), bindings)
        with self.assertRaises(ValueError):
            quest_side.bind(QUEST.replace(b'"start"', b'"own_home"'), dict(quest='q_example'), bindings)
        with self.assertRaises(ValueError):
            quest_side.bind(QUEST, dict(quest='q_example'), dict(player_asset='player', owned_assets=dict(
                q_example=[dict(port='own_x', alias='q_x', asset_type='TagPointAsset')])))


if __name__ == '__main__': unittest.main()
