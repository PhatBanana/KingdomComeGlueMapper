"""Converter C2 (controller trees): source preparation, blocker ledger, golden."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_contracts as contracts
import quest_controller_conversion as c2

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'quest_conversion'
KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
RETAIL = (KCD1 / 'Data/Scripts.pak').is_file() and (KCD2 / 'Data/Scripts.pak').is_file()


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def model(callee, entry_variables, callee_variables=()):
    trees = dict(entry=dict(variables=list(entry_variables), root=node('Root')),
                 callback=dict(variables=list(callee_variables), root=node('Root', [callee])))
    return dict(quest='q_example', behavior_documents={'libs/ai/quests/q_example.xml': dict(trees=trees)})


ACTORS = dict(name='t_actors', type='common:wuid', form='associative')


class PrepareTests(unittest.TestCase):
    def test_a_callback_tree_types_a_bare_index_from_its_document(self):
        source = model(node('Send', target='t_actors[worker]', values="handle('a[b]')", code='x[y]'), [ACTORS])
        prepared, report = contracts.prepare([source])
        attrs = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]['attributes']
        self.assertEqual(attrs, dict(target="t_actors['worker']", values="handle('a[b]')", code='x[y]'))
        self.assertEqual([r['source'] for r in report['scope_resolutions']], ['t_actors[worker]'])
        self.assertEqual(source['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]
                         ['attributes']['target'], 't_actors[worker]')
        self.assertEqual(prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['variables'], [])

    def test_an_index_is_left_alone_when_its_type_or_key_is_not_proven(self):
        cases = [([dict(ACTORS, form='array')], ()),                                   # not a string-keyed map
                 ([ACTORS, dict(name='worker', type='_int', form='single')], ()),      # the key is a variable
                 ([ACTORS], [dict(name='t_actors', type='_int', form='array')]),       # the tree declares it itself
                 ([], ())]                                                             # nobody declares it
        for entry, own in cases:
            prepared, report = contracts.prepare([model(node('Send', target='$t_actors[worker]'), entry, own)])
            self.assertEqual(report['scope_resolutions'], [])
        conflicting = model(node('Send', target='t_actors[worker]'), [ACTORS])
        conflicting['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['other'] = dict(
            variables=[dict(ACTORS, form='array')], root=node('Root'))
        self.assertEqual(contracts.prepare([conflicting])[1]['scope_resolutions'], [])

    def test_a_renamed_operation_maps_every_attribute_or_is_left_blocked(self):
        prepared, report = contracts.prepare([model(node('TurnBody', destinationSpecification='"__player"', alignWith='false'), [])])
        turned = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]
        self.assertEqual((turned['op'], turned['source_op'], turned['attributes']),
                         ('Turn', 'TurnBody', dict(target='"__player"', align='false')))
        prepared, report = contracts.prepare([model(node('TurnBody', somethingNew='1'), [])])
        self.assertEqual(report['rename_blocked'][0]['unmapped'], ['somethingNew'])
        self.assertEqual(prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]['op'], 'TurnBody')

    def test_register_never_replaces_an_existing_contract(self):
        import campaign_behavior
        before = dict(campaign_behavior.CONTRACTS['Parallel'])
        contracts.register()
        self.assertEqual(campaign_behavior.CONTRACTS['Parallel'], before)
        self.assertEqual(campaign_behavior.CONTRACTS['GameOver'], dict(Reason='value'))


class LedgerTests(unittest.TestCase):
    def run_(self, unresolved, emitted_root):
        source = model(node('Success'), [])
        document = 'libs/ai/quests/q_example.xml'
        del source['behavior_documents'][document]['trees']['entry']
        tree = E.Element('BehaviorTree', name='callback'); E.SubElement(tree, 'Variables'); tree.append(emitted_root)
        record = dict(document=document, tree='callback', unresolved=unresolved, native_emitted=not unresolved)
        return dict(model=source, prepared=dict(scope_resolutions=[], renamed=[], rename_blocked=[]),
                    behaviors={} if unresolved else {'AI/x.xml': E.tostring(tree)}, conversion=dict(trees=[record]))

    def test_an_emitted_tree_must_keep_the_source_shape(self):
        good = E.Element('Root'); E.SubElement(good, 'Success')
        led = c2.ledger(self.run_([], good))
        self.assertEqual(led['layers']['source_equivalence']['summary'],
                         dict(checked=1, passed=1, failed=0, residue=0, nodes_compared=2))
        for broken in (E.Element('Root'), E.fromstring('<Root><Fail/></Root>')):
            self.assertEqual(c2.ledger(self.run_([], broken))['layers']['source_equivalence']['verdict'], 'FAIL')

    def test_blockers_are_counted_by_reason_and_family(self):
        sites = [dict(reason='Behavior operation needs an adapter: X')] * 2 + [dict(reason='Referenced buff conversion did not complete: g')]
        led = c2.ledger(self.run_(sites, E.Element('Root')))
        self.assertEqual(led['trees'], dict(total=1, blocked=1))
        self.assertEqual([(b['family'], b['sites'], b['status']) for b in led['blockers']],
                         [('op_no_contract', 2, 'open'), ('buff', 1, 'needs_importer')])
        self.assertIn('| Behavior operation needs an adapter: X | op_no_contract | 2 | 1 | open |', c2.markdown(led))


@unittest.skipUnless(RETAIL, 'requires installed retail KCD1 and KCD2 scripts')
class RetailTests(unittest.TestCase):
    def test_q_skalitz_matches_its_golden_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = c2.ledger(c2.convert(KCD1, KCD2, 'q_skalitz', Path(tmp) / 'work',
                                       ['q_tutorials', 'q_tutorial_swordOne', 'q_escapeToTalmberk']))
        self.assertEqual(led['layers']['source_equivalence']['failures'], [])
        self.assertEqual(json.loads(json.dumps(c2.golden(led), sort_keys=True)),
                         json.loads((FIXTURES / 'q_skalitz.c2.golden.json').read_text(encoding='utf-8')))


if __name__ == '__main__': unittest.main()
