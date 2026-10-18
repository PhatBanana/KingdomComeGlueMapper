"""Reusable source work conversion, without named people or quest branches."""
import copy
import unittest
import xml.etree.ElementTree as E

from test_campaign_behavior import catalog, source
from campaign_behavior import convert_behaviors, reference, associative_indexes
from campaign_quest_bridge import UnsupportedOperation


class WorkPrimitiveTests(unittest.TestCase):
    def test_engine_behavior_map_requires_native_evidence(self):
        expression = '$__behaviors[ArbitraryWork].count > 0'
        with self.assertRaises(UnsupportedOperation):
            associative_indexes(expression, {})
        self.assertEqual(associative_indexes(expression, {}, True),
                         "$__behaviors['ArbitraryWork'].count > 0")
        for declarations in ({'ArbitraryWork': {'type': 'string'}},
                             {'__behaviors': {'form': 'array'}}):
            with self.assertRaises(UnsupportedOperation):
                associative_indexes(expression, declarations, True)
        self.assertEqual(associative_indexes('$__behaviors[$job].count', {}, True),
                         '$__behaviors[$job].count')
        self.assertEqual(associative_indexes("'$__behaviors[ArbitraryWork]'", {}, True),
                         "'$__behaviors[ArbitraryWork]'")

    def test_nested_runtime_map_index_is_preserved(self):
        self.assertEqual(reference('orders[$tables[$i]]'), '$orders[$tables[$i]]')
        self.assertEqual(reference("orders[$tables[$i]].value['name']"),
                         "$orders[$tables[$i]].value['name']")
        for value in ('orders[$tables[$i]', 'orders[$i+1]', 'orders[actor]',
                      'orders[$i]junk', 'orders[$i];call()', 'orders[]'):
            with self.subTest(value=value), self.assertRaises(UnsupportedOperation):
                reference(value)

    def test_work_queries_and_timer_keep_runtime_arguments_and_children(self):
        model = source('''<Root><TimerBox startTime='"opens"' endTime='"closes"'
          variation='""' duration='""'><Sequence>
          <GetBehaviorHolders area='"workArea"' behaviors='"Customer"' targetVar='"customers"'/>
          <GetLockParticipants OutArray='"group"' IncludeSelf='"false"'/>
          <GetHelperData smartObjectName='"table"' helperID='"helper"'
            positionTargetVar='"position"' orientationTargetVar='"orientation"'
            transformTargetVar='""' fragmentTargetVar='""' tagsTargetVar='""'/>
          </Sequence></TimerBox></Root>''')
        original = copy.deepcopy(model)
        files, _, report = convert_behaviors([model], 'Work', catalog())
        self.assertEqual(report['whole_trees_emitted'], 1)
        tree = E.fromstring(next(iter(files.values())))
        self.assertEqual(tree.find('.//GetBehaviorHolders').get('area'), '$workArea')
        self.assertEqual(tree.find('.//GetBehaviorHolders').get('behaviors'), "'Customer'")
        self.assertEqual(tree.find('.//GetLockParticipants').get('OutArray'), '$group')
        self.assertEqual(tree.find('.//GetHelperData').get('positionTargetVar'), '$position')
        self.assertIsNotNone(tree.find('.//TimerBox/Sequence/GetHelperData'))
        self.assertEqual(model, original)
        native = catalog()
        del native['nodes']['GetHelperData']
        self.assertFalse(convert_behaviors([model], 'Work', native)[0])

    def test_vector_requires_native_engine_type(self):
        model = source('<Root><Success/></Root>')
        tree = model['behavior_documents']['libs/ai/quests/q_test.xml']['trees']['onUpdate']
        tree['variables'].append(dict(name='location', type='common:vec3', form='single', values=''))
        native = catalog()
        self.assertFalse(convert_behaviors([model], 'Work', native)[0])
        native['variable_types'].append('vec3')
        files, _, _ = convert_behaviors([model], 'Work', native)
        self.assertEqual(E.fromstring(next(iter(files.values()))).find(
            ".//Variable[@name='location']").get('type'), 'vec3')

    def test_numerical_operations_need_reviewed_abi_and_installed_evidence(self):
        for operation in ('round', 'float2int', 'distance2dSq'):
            model = source('<Root><NumericalOperation Operation="'+operation+'" '
                'In1VariableName="position" In2VariableName="" In3VariableName="" '
                'OutVariableName="result"/></Root>')
            native = catalog()
            self.assertFalse(convert_behaviors([model], 'Work', native)[0])
            native['numerical_operations'] = [operation]
            files, _, _ = convert_behaviors([model], 'Work', native)
            self.assertEqual(E.fromstring(next(iter(files.values()))).find(
                './/NumericalOperation').get('Operation'), operation)
        native['numerical_operations'] = ['invented']
        model = source('<Root><NumericalOperation Operation="invented"/></Root>')
        self.assertFalse(convert_behaviors([model], 'Work', native)[0])


if __name__ == '__main__':
    unittest.main()
