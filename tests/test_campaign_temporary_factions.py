import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_temporary_factions import FactionBridge, OPTION
from campaign_quest_bridge import UnsupportedOperation
from campaign_behavior import convert_behaviors
from campaign_compile import wire_bridge
from campaign_quest_graph import emit_project
from quest_import import ast
from test_campaign_behavior import source, catalog
from test_campaign_quest_graph import model as quest
from test_campaign_combat_runtime import Graph


SOUL = '11111111-2222-3333-4444-555555555555'
OTHER = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
SITE = dict(owner='q_test', document='libs/ai/quests/q_test.xml', tree='onUpdate', path='Root')
NATIVE = b'''<Database><Skald><Module><Nodes><TemporaryFactionEffect Name="native">
<Asset Name="Souls" Alias="actor"/><Constant Name="Faction" Value="native_faction"/>
<Edge From="active" To="IsActive"/></TemporaryFactionEffect></Nodes></Module></Skald></Database>'''
GROUPS = [dict(superfaction_id=str(i), superfaction_name=n) for i, n in [(1,'Civilians'), (2,'Rivals')]]
TREE = b'''<database><FactionTree><Faction Name="gluemapper_kcd1_superfaction_1"/>
<Faction Name="gluemapper_kcd1_superfaction_2"/></FactionTree></database>'''


def fixture():
    bindings = {('q_test', SITE['document'], 'onUpdate', ref): actor
                for ref, actor in [('this.id', SOUL), ('tutor', SOUL), ('other', OTHER), ("actors['tutor']", SOUL)]}
    return FactionBridge('Imported', bindings, GROUPS, TREE, NATIVE)


def operation(bridge, op, actor='this.id', faction=None):
    attrs = dict(soul=actor)
    if faction is not None: attrs['superfaction'] = faction
    node = bridge.lower(ast(E.Element(op, attrs)), SITE)
    return node.tag.removeprefix('SendAIConceptSignal_') + '.OnNotification'


def context(bridge, set_, reason):
    method = 'SetPersistentOption' if set_ else 'ClearOption'
    node = bridge.lower_context(f"Contexts.{method}(entity, '{OPTION}', '{reason}')", SITE)
    return node.tag.removeprefix('SendAIConceptSignal_') + '.OnNotification'


def combat(bridge):
    node = E.Element('IfCondition', failOnCondition='false', condition=
        f"($target == $__player) & ($options.clearTempSuperfactionAgainstPlayer == true) & !$b_context['{OPTION}']")
    E.SubElement(node, 'ClearTemporarySuperfaction', soul='')
    return bridge.combat_guard(ast(node), SITE)


def graph(bridge):
    return Graph(bridge.emit()['Quests/Imported_temporary_factions.xml'])


def enabled(g):
    return [(n.find('Asset').get('Alias'), n.find('Constant').get('Value'))
            for n in g.nodes.values() if n.tag == 'TemporaryFactionEffect'
            and g.value(n.find('Edge').get('From'))]


class TemporaryFactionTests(unittest.TestCase):
    def test_replace_clear_exposes_underlying_faction_without_restore_snapshot(self):
        bridge = fixture()
        first = operation(bridge, 'SetTemporarySuperfaction', faction='Civilians')
        second = operation(bridge, 'SetTemporarySuperfaction', faction='Rivals')
        clear = operation(bridge, 'ClearTemporarySuperfaction')
        g = graph(bridge)
        self.assertFalse(enabled(g))
        g.fire(first); self.assertEqual([f for _, f in enabled(g)], ['gluemapper_kcd1_superfaction_1'])
        g.fire(second); self.assertEqual([f for _, f in enabled(g)], ['gluemapper_kcd1_superfaction_2'])
        g.fire(clear); self.assertFalse(enabled(g))
        g.fire(clear); self.assertFalse(enabled(g))
        # No permanent faction setter or guessed original faction snapshot.
        self.assertFalse(g.root.findall('.//SetFaction'))
        self.assertEqual({n.tag for n in g.nodes.values()},
                         {'State', 'TemporaryFactionEffect', 'AIConceptSignalTrigger', 'TriggerSequence'})

    def test_combat_clear_requires_original_opponent_and_policy(self):
        bridge = fixture()
        node = combat(bridge)
        self.assertEqual(node.get('condition'),
            '($target == $__player) & ($options.clearTempSuperfactionAgainstPlayer == true)')
        for target_is_player in (False, True):
            for clear_policy in (False, True):
                set_ = operation(bridge, 'SetTemporarySuperfaction', faction='Civilians')
                g = graph(bridge); g.fire(set_)
                if target_is_player and clear_policy:
                    g.fire(node[0].tag.removeprefix('SendAIConceptSignal_') + '.OnNotification')
                self.assertEqual(bool(enabled(g)), not (target_is_player and clear_policy))

    def test_independent_protection_handles_and_explicit_clear(self):
        bridge = fixture()
        set_ = operation(bridge, 'SetTemporarySuperfaction', faction='Civilians')
        clear = operation(bridge, 'ClearTemporarySuperfaction')
        protect_a, protect_b = context(bridge, True, 'owner_a'), context(bridge, True, 'owner_b')
        unprotect_a, unprotect_b = context(bridge, False, 'owner_a'), context(bridge, False, 'owner_b')
        on_combat = combat(bridge)[0].tag.removeprefix('SendAIConceptSignal_') + '.OnNotification'
        g = graph(bridge); g.fire(set_); g.fire(protect_a); g.fire(protect_b)
        g.fire(on_combat); self.assertTrue(enabled(g))
        g.fire(unprotect_a); g.fire(on_combat); self.assertTrue(enabled(g))
        g.fire(clear); self.assertFalse(enabled(g))  # Explicit clear bypasses suppression.
        g.fire(set_); g.fire(on_combat); self.assertTrue(enabled(g))  # Clear did not remove context.
        g.fire(unprotect_b); g.fire(on_combat); self.assertFalse(enabled(g))

    def test_souls_and_restored_persistent_state_are_independent(self):
        bridge = fixture()
        a = operation(bridge, 'SetTemporarySuperfaction', faction='Civilians')
        b = operation(bridge, 'SetTemporarySuperfaction', actor='other', faction='Rivals')
        clear = operation(bridge, 'ClearTemporarySuperfaction')
        protect = context(bridge, True, 'owner')
        on_combat = combat(bridge)[0].tag.removeprefix('SendAIConceptSignal_') + '.OnNotification'
        g = graph(bridge); g.fire(a); g.fire(b); g.fire(protect)
        restored = graph(bridge); restored.states = copy.deepcopy(g.states)
        restored.fire(on_combat); self.assertEqual(len(enabled(restored)), 2)
        restored.fire(clear)
        self.assertEqual([f for _, f in enabled(restored)], ['gluemapper_kcd1_superfaction_2'])

    def test_external_context_receiver_resolves_same_soul(self):
        bridge = fixture()
        local = bridge.lower_context(f"Contexts.ClearOption(entity, '{OPTION}', 'owner')", SITE)
        external = bridge.lower_context(
            f"Contexts.ClearOption(XGenAIModule.GetEntityByWUID(data.actors['tutor']), '{OPTION}', 'owner')", SITE)
        self.assertEqual(local.tag, external.tag)

    def test_unknown_scope_group_context_program_and_guard_are_rejected(self):
        for fn in (
            lambda b: operation(b, 'SetTemporarySuperfaction', faction='Missing'),
            lambda b: operation(b, 'SetTemporarySuperfaction', actor='unbound', faction='Civilians'),
            lambda b: b.lower_context(f"Contexts.SetNonpersistentOption(entity, '{OPTION}', 'owner')", SITE),
            lambda b: b.lower_context(f"Contexts.SetPersistentOption(entity, '{OPTION}', 'owner'); unknown()", SITE),
        ):
            b = fixture()
            with self.assertRaises(UnsupportedOperation): fn(b)
            self.assertFalse(b.actions)
        b = fixture(); before = copy.deepcopy(b.actions)
        n = E.Element('IfCondition', condition=f"$b_context['{OPTION}']")
        self.assertIsNone(b.combat_guard(ast(n), SITE))
        self.assertEqual(before, b.actions)

    def test_constructor_requires_registered_group_and_native_effect(self):
        for groups, tree, native in [(GROUPS + GROUPS[:1], TREE, NATIVE),
                                    (GROUPS, b'<database/>', NATIVE), (GROUPS, TREE, b'<Database/>')]:
            with self.assertRaises(ValueError):
                FactionBridge('Imported', {}, groups, tree, native)

    def test_compiler_lowers_original_sites_and_wires_module(self):
        root = E.Element('Root'); seq = E.SubElement(root, 'Sequence')
        E.SubElement(seq, 'SetTemporarySuperfaction', soul='tutor', superfaction='Civilians')
        E.SubElement(seq, 'ExecuteLua', code=f"Contexts.SetPersistentOption(entity, '{OPTION}', 'owner')")
        guard = E.SubElement(seq, 'IfCondition', condition='$hasStarted')
        E.SubElement(guard, 'ClearTemporarySuperfaction', soul='tutor')
        m = source(E.tostring(root, encoding='unicode'))
        before = copy.deepcopy(m)
        files, bridges, report = convert_behaviors([m], 'Imported', catalog(), faction_adapter=fixture())
        self.assertEqual(report['whole_trees_emitted'], 1)
        native_root = E.fromstring(next(iter(files.values())))
        self.assertTrue(native_root.find('.//IfCondition')[0].tag.startswith('SendAIConceptSignal_'))
        self.assertFalse(report['temporary_factions']['runtime_validated'])
        project, _ = emit_project([quest()], 'world')
        wire_bridge(project, 'world', bridges, report)
        host = E.fromstring(project['world.xml']).find('./Skald/Project')
        self.assertIsNotNone(host.find("Nodes/Imported_temporary_factions[@Name='source_temporary_factions']"))
        self.assertEqual(m, before)

    def test_compiler_does_not_reinterpret_unrecognized_context_read(self):
        root = E.Element('Root')
        E.SubElement(root, 'IfCondition', condition=f"$b_context['{OPTION}']")
        files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))],
            'Imported', catalog(), faction_adapter=fixture())
        self.assertFalse(files)
        self.assertIn('Unconverted temporary faction context read', report['trees'][0]['unresolved'][0]['reason'])

    def test_compiler_combat_guard_has_only_the_guarded_clear_signal(self):
        root = E.Element('Root')
        guard = E.SubElement(root, 'IfCondition', failOnCondition='false', condition=
            f"($target == $__player) & ($options.clearTempSuperfactionAgainstPlayer == true) & !$b_context['{OPTION}']")
        E.SubElement(guard, 'ClearTemporarySuperfaction', soul='', id='42')
        bridge = fixture()
        files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))],
            'Imported', catalog(), faction_adapter=bridge)
        self.assertEqual(report['whole_trees_emitted'], 1)
        guard = E.fromstring(next(iter(files.values()))).find('.//IfCondition')
        self.assertEqual(len(guard), 1)
        self.assertTrue(guard[0].tag.startswith('SendAIConceptSignal_'))
        self.assertEqual([a['kind'] for a in bridge.actions.values()], ['combat_clear'])

    def test_unconverted_context_in_other_operations_is_not_silently_accepted(self):
        for operation_ in ('IfElseCondition', 'Expression'):
            root = E.Element('Root')
            field = 'expressions' if operation_ == 'Expression' else 'condition'
            E.SubElement(root, operation_, {field: f"$b_context['{OPTION}']"})
            files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))],
                'Imported', catalog(), faction_adapter=fixture())
            self.assertFalse(files)
            self.assertIn('Unconverted temporary faction context use', report['trees'][0]['unresolved'][0]['reason'])

    def test_context_read_without_adapter_withholds_tree(self):
        root = E.Element('Root')
        E.SubElement(root, 'IfCondition', condition=f"!$b_context['{OPTION}']")
        files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))],
                                             'Imported', catalog())
        self.assertFalse(files)
        self.assertIn('Unconverted temporary faction context use', report['trees'][0]['unresolved'][0]['reason'])


if __name__ == '__main__': unittest.main()
