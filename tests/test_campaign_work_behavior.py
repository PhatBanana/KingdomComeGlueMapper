import copy
import unittest
import xml.etree.ElementTree as E

from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors
from campaign_dependencies import DependencyImporter, ImportPlan


class Inbox:
    def name(self, identity):
        return 'converted_' + identity

    def plan(self, identity):
        return ImportPlan()

    def convert(self, identity, plan, registered):
        return self.name(identity), {}, {}


class WorkBehaviorTests(unittest.TestCase):
    def test_tool_search_preserves_categories_helpers_and_literal_concat_patterns(self):
        model=source('''<Root><Sequence>
          <GraphSearch Origin="&quot;workplace&quot;">
            <CategoryFilter categories="&quot;Anvil&quot;" Source="&quot;Child&quot;" Child="&quot;station&quot;"/>
          </GraphSearch>
          <GetHelper smartObjectName="&quot;station&quot;" helperName="&quot;stand&quot;" categoryName="&quot;&quot;"
            targetVar="&quot;point&quot;" policy="&quot;Name&quot;"/>
          <Concatenation OutString="&quot;alias&quot;" Pattern="&quot;$prefix;$index;&quot;"/>
          <ForceLook LookTarget="&quot;partner&quot;" DisableVariations="&quot;false&quot;">
            <DoDialog DialogId="&quot;$dialogId&quot;"/></ForceLook>
          </Sequence></Root>''')
        files,_,report=convert_behaviors([model],'Converted',catalog())
        self.assertEqual(report['whole_trees_emitted'],1)
        root=E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//CategoryFilter').get('categories'),"'Anvil'")
        self.assertEqual(root.find('.//GetHelper').get('smartObjectName'),'$station')
        self.assertEqual(root.find('.//Concatenation').get('Pattern'),"'$prefix;$index;'")
        self.assertEqual(root.find('.//ForceLook/DoDialog').get('DialogId'),'$dialogId')

    def test_random_job_selection_preserves_operand_and_proximity_reference_formats(self):
        model = source('''<Root><Sequence>
          <NumericalOperation In1VariableName="&quot;0&quot;" In2VariableName="&quot;jobCount&quot;"
            In3VariableName="&quot;&quot;" OutVariableName="&quot;jobIndex&quot;" Operation="&quot;randRange&quot;"/>
          <NotNearPlayer target="&quot;this.id&quot;" result="&quot;visibleCheck&quot;"/>
          </Sequence></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//NumericalOperation').attrib, dict(In1VariableName='0',
            In2VariableName='jobCount', In3VariableName='', OutVariableName='$jobIndex', Operation='randRange'))
        self.assertEqual(root.find('.//NotNearPlayer').attrib, dict(target='$this.id',result='$visibleCheck'))
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_unverified_numeric_operation_and_expression_operand_are_rejected(self):
        for operand, operation in [('jobCount + 1','randRange'), ('jobCount','inventedOp')]:
            model = source(f'''<Root><NumericalOperation In1VariableName="&quot;{operand}&quot;"
              OutVariableName="&quot;result&quot;" Operation="&quot;{operation}&quot;"/></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog())
            self.assertFalse(files)
            self.assertEqual(report['blocked_trees'], 1)

    def test_exclusive_area_and_object_jobs_keep_target_and_request_policy(self):
        for operation, target in [('SmartAreaBehaviorTag','smartArea'), ('SmartObjectBehaviorTag','smartObject')]:
            model = source(f'''<Root><{operation} {target}="&quot;workplace&quot;"
              preferredBehaviors="&quot;AnyImportedJob&quot;" forbiddenBehaviors="&quot;&quot;"
              preferredBehaviorsOnly="&quot;true&quot;" stopAfterFirstFound="&quot;false&quot;"
              ignoreDropUnloading="&quot;true&quot;"/></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog())
            self.assertEqual(report['whole_trees_emitted'], 1)
            call = E.fromstring(next(iter(files.values()))).find('.//CallBehavior')
            self.assertEqual(call.attrib, dict(Target='$workplace', BehaviorName="'AnyImportedJob'",
                stopAfterFirstFound='false', ignoreDropUnloading='true'))

    def test_work_request_selection_policy_is_not_silently_discarded(self):
        for extra in ['preferredBehaviorsOnly="&quot;false&quot;"',
                      'preferredBehaviorsOnly="&quot;true&quot;" forbiddenBehaviors="&quot;OtherJob&quot;"']:
            model = source(f'''<Root><SmartAreaBehaviorTag smartArea="&quot;workplace&quot;"
              preferredBehaviors="&quot;AnyImportedJob&quot;" {extra}/></Root>''')
            files, _, report = convert_behaviors([model], 'Converted', catalog())
            self.assertFalse(files)
            self.assertEqual(report['blocked_trees'], 1)

    def test_object_quest_scope_requires_a_registered_controller_callback(self):
        model = source('''<Root><QuestObjectiveCondition quest="&quot;$__object.name&quot;"
          objective="&quot;first&quot;" function="&quot;IsObjectiveStarted&quot;">
          <Then><Success/></Then></QuestObjectiveCondition></Root>''')
        files, _, _ = convert_behaviors([model], 'Converted', catalog())
        self.assertFalse(files)
        model['controller_registration'] = dict(entry_points=[dict(kind='behavior_callback',
            file='quests/q_test.xml', tree='onUpdate')])
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertEqual(report['whole_trees_emitted'], 1)
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('.//GameContextCheck/Then/Success').tag, 'Success')

    def test_job_loop_preserves_interrupt_gates_reservation_and_iteration(self):
        model = source('''<Root><Behavior><ForEach array="&quot;stations&quot;"
          value="&quot;station&quot;" startIndex="&quot;0&quot;" step="&quot;1&quot;" break="&quot;$stop&quot;">
          <DialogGate Who="&quot;this.id&quot;" Negation="&quot;true&quot;"
            Condition="&quot;InDialog&quot;" RunLogic="&quot;Halt&quot;">
            <Semaphore atomic="&quot;true&quot;" LockManagerType="&quot;Intellect&quot;"
              SemaphoreName="&quot;workTool&quot;" SemaphoreCount="&quot;1&quot;">
              <LoopUntil until="&quot;Success&quot;" attemptCount="&quot;3&quot;">
                <CallBehavior Target="&quot;station&quot;" BehaviorName="&quot;use&quot;"
                  ignoreDropUnloading="&quot;false&quot;" stopAfterFirstFound="&quot;true&quot;"/>
              </LoopUntil>
            </Semaphore>
          </DialogGate></ForEach></Behavior></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        root = E.fromstring(next(iter(files.values())))
        loop = root.find('.//ForEach')
        self.assertEqual(loop.get('array'), '$stations')
        self.assertEqual(loop.get('value'), '$station')
        self.assertEqual(loop.get('break'), '$stop')
        gate = loop.find('DialogGate')
        self.assertEqual(gate.get('RunLogic'), 'Halt')
        reservation = gate.find('Semaphore')
        self.assertEqual(reservation.get('SemaphoreName'), "'workTool'")
        call = reservation.find('LoopUntil/CallBehavior')
        self.assertEqual(call.get('Target'), '$station')
        self.assertEqual(call.get('BehaviorName'), "'use'")
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_mailbox_clear_and_read_use_the_same_imported_inbox(self):
        model = source('''<Root><Sequence>
          <ClearInbox inbox="&quot;work&quot;" type="&quot;&quot;" condition="&quot;&quot;"/>
          <ReadMessage inbox="&quot;work&quot;" variable="&quot;request&quot;"
            timeout="&quot;-1&quot;" timeType="&quot;GameTime&quot;" condition="&quot;$request.enabled&quot;"/>
          </Sequence></Root>''')
        importer = DependencyImporter({'mailboxes': Inbox()})
        files, _, _ = convert_behaviors([model], 'Converted', catalog(), importer=importer)
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//ClearInbox').get('type'), '')
        for operation in ('ClearInbox', 'ReadMessage'):
            self.assertEqual(root.find('.//' + operation).get('inbox'), "'converted_work'")
        self.assertEqual(root.find('.//ReadMessage').get('condition'), '$request.enabled')
        self.assertEqual(len(importer.jobs), 1)
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)

    def test_work_reservation_keeps_save_branch_search_and_execution(self):
        model = source('''<Root><OnInit><IsLoadedGate saveVersion="2">
          <Then><Success/></Then><Else><Expression expressions="&quot;$phase = 0&quot;"/></Else>
          </IsLoadedGate></OnInit><Behavior><ReserveBehavior reserveFrom="&quot;found&quot;"
          behaviorName="&quot;$jobs[$index].name&quot;" saveVersion="2">
          <Search><ReserveBehaviorSearch><GraphSearch>
            <HasBehaviorFilter BehaviorList="&quot;$jobs[$index].name&quot;" FilterChoice="&quot;Requestable&quot;"/>
            <Nodalyzer Quantifiers="&quot;Exists&quot;" Child="&quot;found&quot;"/>
          </GraphSearch></ReserveBehaviorSearch></Search>
          <Exec><CallBehavior Target="&quot;found&quot;" BehaviorName="&quot;$jobs[$index].name&quot;"/></Exec>
          </ReserveBehavior></Behavior></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        root = E.fromstring(next(iter(files.values())))
        self.assertIsNotNone(root.find('.//OnInit/IsLoadedGate/Then/Success'))
        self.assertEqual(root.find('.//IsLoadedGate/Else/Expression').get('expressions'), '$phase = 0')
        reservation = root.find('.//ReserveBehavior')
        self.assertEqual(reservation.get('reserveFrom'), '$found')
        self.assertIsNotNone(reservation.find('Search/ReserveBehaviorSearch/GraphSearch/HasBehaviorFilter'))
        self.assertEqual(reservation.find('Exec/CallBehavior').get('BehaviorName'), reservation.get('behaviorName'))
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_request_events_keep_handlers_and_cleanup_order(self):
        model = source('''<Root><TryCatch atomicCatch="&quot;true&quot;">
          <BehaviorTagCatch Reason="&quot;RequestOK&quot;" ConsumeInnerEvents="&quot;true&quot;">
            <Expression expressions="&quot;$working = true&quot;"/></BehaviorTagCatch>
          <BehaviorTagCatch Reason="&quot;BehSucces&quot;" ConsumeInnerEvents="&quot;true&quot;"><Success/></BehaviorTagCatch>
          <BehaviorTagCatch Reason="&quot;BehFail&quot;" ConsumeInnerEvents="&quot;true&quot;"><Fail/></BehaviorTagCatch>
          <Subtree><CallBehavior Target="&quot;station&quot;" BehaviorName="&quot;use&quot;"/></Subtree>
          </TryCatch></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        catch = E.fromstring(next(iter(files.values()))).find('.//TryCatch')
        self.assertEqual([n.get('Reason') for n in catch.findall('BehaviorTagCatch')], ['RequestOK','BehSucces','BehFail'])
        self.assertEqual(catch[0].find('Expression').get('expressions'), '$working = true')
        self.assertEqual(catch[-1].tag, 'Subtree')
        self.assertEqual(report['whole_trees_emitted'], 1)
        model = source('<Root><BehaviorTagCatch Reason="&quot;TypoEvent&quot;"/></Root>')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertFalse(files)
        self.assertIn('Unknown behavior request event', report['trees'][0]['unresolved'][0]['reason'])

    def test_nonempty_variable_script_blocks_the_whole_caller(self):
        model = source('''<Root><Sequence><SetVariable variable="&quot;parameters&quot;"
          script="&quot;legacyFunction()&quot;" values="&quot;enabled(true)&quot;"/>
          <CallBehavior Target="&quot;station&quot;" BehaviorName="&quot;use&quot;"/></Sequence></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertFalse(files)
        self.assertIn('semantic adapter', report['trees'][0]['unresolved'][0]['reason'])

    def test_absent_native_field_blocks_instead_of_dropping_job_policy(self):
        model = source('<Root><CallBehavior Target="&quot;station&quot;" BehaviorName="&quot;use&quot;" stopAfterFirstFound="&quot;true&quot;"/></Root>')
        native = copy.deepcopy(catalog())
        native['nodes']['CallBehavior']['attributes'].remove('stopAfterFirstFound')
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)


if __name__ == '__main__':
    unittest.main()
