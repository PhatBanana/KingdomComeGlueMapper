import copy
import unittest
import xml.etree.ElementTree as E

from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors, reference, UnsupportedOperation
from campaign_dependencies import DependencyImporter, ImportPlan


class Inbox:
    def name(self, identity):
        return 'converted_' + identity

    def plan(self, identity):
        return ImportPlan()

    def convert(self, identity, plan, registered):
        return self.name(identity), {}, {}


class WorkBehaviorTests(unittest.TestCase):
    def test_work_route_selection_keeps_randomness_and_runtime_range(self):
        model = source('''<Root><Sequence>
          <RandomItem Array="&quot;points&quot;" Result="&quot;selected&quot;" Clamp="&quot;-1&quot;"/>
          <GraphSearch><RangeFilter min="&quot;0&quot;" max="&quot;$range&quot;"
            point="&quot;this.id&quot;" excludeRef="&quot;true&quot;" Source="&quot;Child&quot;"
            prune="&quot;true&quot;" negprune="&quot;unknown&quot;" Parent="&quot;&quot;"
            Child="&quot;candidate&quot;"/></GraphSearch></Sequence></Root>''')
        native = catalog()
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//RandomItem').attrib,
                         dict(Array='$points', Result='$selected', Clamp='-1'))
        node = root.find('.//RangeFilter')
        self.assertEqual(node.get('max'), '$range')
        self.assertEqual(node.get('point'), '$this.id')
        self.assertEqual(node.get('Child'), '$candidate')
        del native['nodes']['RandomItem']
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])

    def test_animation_helper_query_keeps_runtime_selection_and_outputs(self):
        model = source('''<Root><GetAnimationHelperData smartObject="&quot;__object.id&quot;"
          helperID="&quot;entryID&quot;" fragment="&quot;$animation&quot;" tags="&quot;$tags&quot;"
          positionTargetVar="&quot;AnimPos&quot;" orientationTargetVar="&quot;AnimRot&quot;"
          transformTargetVar="&quot;&quot;"/></Root>''')
        native = catalog()
        native['nodes']['GetAnimationHelperData']['attributes'] = ['smartObject','helperID','fragment',
            'tags','positionTargetVar','orientationTargetVar','transformTargetVar']
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        node = E.fromstring(next(iter(files.values()))).find('.//GetAnimationHelperData')
        self.assertEqual(node.attrib, dict(smartObject='$__object.id', helperID='$entryID', fragment='$animation',
            tags='$tags', positionTargetVar='$AnimPos', orientationTargetVar='$AnimRot', transformTargetVar=''))

    def test_crime_perception_query_preserves_observer_and_branches(self):
        model = source('''<Root><HasPerceivableState PerceivableState="&quot;trespass&quot;"
          PerceivedWUID="&quot;__player&quot;" PerceptorWUID="&quot;this.id&quot;"
          FailSubtMissing="&quot;false&quot;" saveVersion="2">
          <Then><Success/></Then><Else><Fail/></Else></HasPerceivableState></Root>''')
        native = catalog()
        native['nodes']['HasPerceivableState']['attributes'] = [
            'PerceivableState', 'PerceivedWUID', 'PerceptorWUID', 'FailSubtMissing', 'saveVersion']
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
        native['policy_values'] = {'perceivable_states': ["'trespass'"]}
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        node = E.fromstring(next(iter(files.values()))).find('.//HasPerceivableState')
        self.assertEqual(node.get('PerceivableState'), "'trespass'")
        self.assertEqual(node.get('PerceivedWUID'), '$__player')
        self.assertEqual(node.get('PerceptorWUID'), '$this.id')
        self.assertIsNotNone(node.find('Then/Success'))
        self.assertIsNotNone(node.find('Else/Fail'))

    def test_item_parameter_filter_preserves_ownership_and_search_policy(self):
        model = source('''<Root><GraphSearch><ItemParamFilter Param="&quot;Stolen&quot;"
          owner="&quot;__player&quot;" Source="&quot;Child&quot;" prune="&quot;true&quot;"
          negprune="&quot;unknown&quot;" Parent="&quot;&quot;" Child="&quot;candidate&quot;"/></GraphSearch></Root>''')
        native = catalog()
        native['nodes']['ItemParamFilter']['attributes'] = [
            'Param', 'owner', 'Source', 'prune', 'negprune', 'Parent', 'Child']
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
        native['policy_values'] = {'item_filter_parameters': ['Stolen']}
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        node = E.fromstring(next(iter(files.values()))).find('.//ItemParamFilter')
        self.assertEqual(node.attrib, dict(Param='Stolen', owner='$__player', Source='Child',
            prune='true', negprune='unknown', Parent='', Child='$candidate'))

    def test_entity_validity_death_and_type_queries_preserve_branches(self):
        model = source('''<Root><CheckWuidValid wuid="&quot;candidate&quot;" FailSubtMissing="&quot;false&quot;" saveVersion="2">
          <Then><IsDeadCheck SoulWUID="&quot;candidate&quot;" FailSubtMissing="&quot;false&quot;" saveVersion="2">
            <Then><Fail/></Then><Else><GetType WUID="&quot;candidate&quot;" OutString="&quot;kind&quot;"
              ShowTrueIdentity="&quot;false&quot;" TreatPlayerAsNPC="&quot;true&quot;"/></Else>
          </IsDeadCheck></Then><Else><Success/></Else></CheckWuidValid></Root>''')
        native = catalog()
        for name, fields in {
            'CheckWuidValid': ['wuid','FailSubtMissing','saveVersion'],
            'IsDeadCheck': ['SoulWUID','FailSubtMissing','saveVersion'],
            'GetType': ['WUID','OutString','ShowTrueIdentity','TreatPlayerAsNPC'],
        }.items():
            native['nodes'][name]['attributes'] = fields
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        query = E.fromstring(next(iter(files.values()))).find('.//Root/CheckWuidValid')
        self.assertEqual(query.get('wuid'), '$candidate')
        self.assertIsNotNone(query.find('Else/Success'))
        death = query.find('Then/IsDeadCheck')
        self.assertEqual(death.get('SoulWUID'), '$candidate')
        self.assertIsNotNone(death.find('Then/Fail'))
        self.assertEqual(death.find('Else/GetType').attrib, dict(WUID='$candidate', OutString='$kind',
            ShowTrueIdentity='false', TreatPlayerAsNPC='true'))

    def test_distance_condition_keeps_runtime_bounds_and_middle_policy(self):
        model = source('''<Root><DistanceCondition Origin="&quot;&quot;" ReferencePt="&quot;home&quot;"
          Low="&quot;$near&quot;" High="&quot;40&quot;" Negation="&quot;true&quot;"
          ValueOnMiddle="&quot;false&quot;" failOnCondition="&quot;false&quot;"><Success/></DistanceCondition></Root>''')
        native = catalog()
        native['nodes']['DistanceCondition']['attributes'] = ['Origin','ReferencePt','Low','High','Negation','ValueOnMiddle','failOnCondition']
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        query = E.fromstring(next(iter(files.values()))).find('.//DistanceCondition')
        self.assertEqual(query.attrib, dict(Origin='', ReferencePt='$home', Low='$near', High='40',
            Negation='true', ValueOnMiddle='false', failOnCondition='false'))
        self.assertIsNotNone(query.find('Success'))

    def test_area_checks_preserve_matching_output_and_both_branches(self):
        model = source('''<Root><IsInsideAreaWithLabel Position="&quot;this.id&quot;"
            Label="&quot;private&quot;" Area="&quot;homeArea&quot;" FailSubtMissing="&quot;false&quot;" saveVersion="2">
          <Then canSkip="1"><IsInsideArea Origin="&quot;__player&quot;" Area="&quot;homeArea&quot;"
              FailSubtMissing="&quot;false&quot;" saveVersion="2"><Then><Success/></Then><Else><Fail/></Else></IsInsideArea></Then>
          <Else canSkip="1"><Success/></Else>
        </IsInsideAreaWithLabel></Root>''')
        native = catalog()
        # Installed runtime contracts, independent of converter declarations.
        native['nodes']['IsInsideAreaWithLabel']['attributes'] = ['Position','Label','Area','FailSubtMissing','saveVersion']
        native['nodes']['IsInsideArea']['attributes'] = ['Origin','Area','FailSubtMissing','saveVersion']
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'],1)
        node = E.fromstring(next(iter(files.values()))).find('.//Root/IsInsideAreaWithLabel')
        self.assertEqual(node.attrib,dict(Position='$this.id',Label="'private'",Area='$homeArea',
                                         FailSubtMissing='false',saveVersion='2'))
        self.assertIsNotNone(node.find('Else/Success'))
        query=node.find('Then/IsInsideArea')
        self.assertEqual(query.get('Origin'),'$__player')
        self.assertEqual(query.get('Area'),'$homeArea')
        self.assertIsNotNone(query.find('Then/Success'))
        self.assertIsNotNone(query.find('Else/Fail'))

    def test_continuous_area_barrier_retains_negation_and_run_logic(self):
        model=source('''<Root><IsInsideAreaWithLabelBarrier Who="&quot;this.id&quot;"
            Label="&quot;private&quot;" Negation="&quot;true&quot;" RunLogic="&quot;Halt&quot;">
            <Wait duration="&quot;1&quot;"/></IsInsideAreaWithLabelBarrier></Root>''')
        native=catalog()
        native['nodes']['IsInsideAreaWithLabelBarrier']['attributes']=['Who','Label','Negation','RunLogic']
        files,_,_=convert_behaviors([model],'Converted',native)
        node=E.fromstring(next(iter(files.values()))).find('.//IsInsideAreaWithLabelBarrier')
        self.assertEqual(node.attrib,dict(Who='$this.id',Label="'private'",Negation='true',RunLogic='Halt'))
        self.assertIsNotNone(node.find('Wait'))

    def test_home_access_and_work_state_transitions_preserve_order_and_target(self):
        model = source('''<Root><Sequence>
          <AddAreaLabel Area="&quot;house&quot;" Label="&quot;private&quot;"/>
          <SetBehaviorState behaviors="&quot;work&quot;" state="&quot;NoRequests&quot;"/>
          <RemoveAreaLabel Area="&quot;house&quot;" Label="&quot;private&quot;"/>
          <SetBehaviorState behaviors="&quot;work&quot;" state="&quot;Enabled&quot;"/>
        </Sequence></Root>''')
        native = catalog()
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
        native['policy_values'] = dict(area_labels=["'private'"], behavior_states=['Enabled','NoRequests'])
        files, _, _ = convert_behaviors([model], 'Converted', native)
        sequence = E.fromstring(next(iter(files.values()))).find('.//Root/Sequence')
        self.assertEqual([n.tag for n in sequence],
            ['AddAreaLabel','SetBehaviorState','RemoveAreaLabel','SetBehaviorState'])
        self.assertEqual(sequence[0].attrib, dict(Area='$house', Label="'private'"))
        self.assertEqual(sequence[1].attrib, dict(behaviors="'work'", state='NoRequests'))
        native['policy_values']['behavior_states'].remove('NoRequests')
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])

    def test_lua_gate_preserves_native_save_version_and_conditional_child(self):
        model = source('''<Root><LuaGate code="&quot;return entity:IsReady()&quot;" saveVersion="2">
          <Wait duration="&quot;1&quot;"/></LuaGate></Root>''')
        native = catalog()
        native['lua_contracts'] = {'LuaGate': {'code': ['return entity:IsReady()']}}
        files, _, _ = convert_behaviors([model], 'Converted', native)
        gate = E.fromstring(next(iter(files.values()))).find('.//LuaGate')
        self.assertEqual(gate.get('saveVersion'), '2')
        self.assertIsNotNone(gate.find('Wait'))

    def test_native_lua_lifecycle_requires_exact_installed_contract(self):
        model = source('''<Root><LuaWrapper onEnter="&quot;entity:EnterJob()&quot;"
            onExit="&quot;entity:ExitJob()&quot;"><Wait duration="&quot;1&quot;"/></LuaWrapper></Root>''')
        native = catalog()
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
        native['lua_contracts'] = {'LuaWrapper': {'onEnter': ['entity:EnterJob()'],
                                                 'onExit': ['entity:ExitJob()']}}
        files, _, _ = convert_behaviors([model], 'Converted', native)
        wrapper = E.fromstring(next(iter(files.values()))).find('.//LuaWrapper')
        self.assertEqual(wrapper.get('onExit'), 'entity:ExitJob()')
        self.assertIsNotNone(wrapper.find('Wait'))
        native['lua_contracts']['LuaWrapper']['onExit'] = ['entity:DifferentExitJob()']
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])

    def test_item_state_reads_use_native_output_and_validated_property(self):
        model = source('''<Root><GetItemProperty itemId="&quot;tool&quot;"
            property="&quot;InInventory&quot;" targetVar="&quot;stored&quot;"/></Root>''')
        native = catalog()
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
        native['item_properties'] = {'GetItemProperty': ['InInventory']}
        files, _, _ = convert_behaviors([model], 'Converted', native)
        node = E.fromstring(next(iter(files.values()))).find('.//GetItemProperty')
        self.assertEqual(node.attrib, dict(itemId='$tool',property='InInventory',result='$stored'))

    def test_consumed_item_class_requires_import_but_placed_item_keeps_runtime_reference(self):
        for selector in ('Item="&quot;usedItem&quot;" ItemGUID="&quot;&quot;"',
                         'Item="&quot;&quot;" ItemGUID="&quot;source-food&quot;"'):
            model = source('<Root><RemoveItem '+selector+' Amount="&quot;1&quot;" NotifyUI="&quot;false&quot;"/></Root>')
            native = catalog()
            # Independent retail contract: AI/battles/battleGateController.xml.
            native['nodes']['RemoveItem']['attributes'] = ['Item','ItemGUID','Source',
                'Amount','FailOnDoesntExist','NotifyUI']
            files, _, _ = convert_behaviors([model], 'Converted', native,
                registered={'items': {'source-food': 'native-food'}})
            node = E.fromstring(next(iter(files.values()))).find('.//RemoveItem')
            if 'usedItem' in selector:
                self.assertEqual(node.get('Item'), '$usedItem')
            else:
                self.assertEqual(node.get('ItemGUID'), "'native-food'")
                self.assertFalse(convert_behaviors([model], 'Converted', catalog())[0])

    def test_source_serialization_ids_are_not_runtime_arguments(self):
        model = source('''<Root><Sequence id="12"><Wait id="13"
            duration="&quot;1&quot;"/></Sequence></Root>''')
        untouched = copy.deepcopy(model)
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertEqual(model, untouched)
        self.assertEqual(report['whole_trees_emitted'], 1)
        root = E.fromstring(next(iter(files.values())))
        self.assertNotIn('id', root.find('.//Sequence').attrib)
        self.assertNotIn('id', root.find('.//Wait').attrib)
        self.assertEqual([r['id'] for r in report['trees'][0]['source_serialization_ids']], ['12','13'])
        model = source('<Root><GraphSearch Origin="&quot;this.id&quot;" id="&quot;found&quot;"/></Root>')
        files, _, _ = convert_behaviors([model], 'Converted', catalog())
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('.//GraphSearch').get('id'), '$found')
        model = source('<Root><Sequence id="&quot;12&quot;"/></Root>')
        self.assertFalse(convert_behaviors([model], 'Converted', catalog())[0])

    def test_runtime_participant_lookup_is_preserved(self):
        self.assertEqual(reference('groups[$sender.id]'), '$groups[$sender.id]')
        self.assertEqual(reference('positions[$index].seat'), '$positions[$index].seat')
        self.assertEqual(reference("groups['workers'][0]"), "$groups['workers'][0]")
        for invalid in ('groups[$index + 1]', 'groups[call()]', 'groups[$]'):
            with self.assertRaises(UnsupportedOperation): reference(invalid)

    def test_message_sender_records_use_verified_native_engine_types(self):
        for old, new in [('common:senderInfo','senderInfo'),
                         ('common:senderInfo:senderInfoBehavior','senderInfo:senderInfoBehavior')]:
            model = source('<Root><Wait duration="&quot;1&quot;"/></Root>')
            tree = model['behavior_documents']['libs/ai/quests/q_test.xml']['trees']['onUpdate']
            tree['variables'].append(dict(name='sender',type=old,values='',form='single',isPersistent='0'))
            native = catalog()
            self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
            native['variable_types'].append(new)
            files, _, report = convert_behaviors([model], 'Converted', native)
            self.assertEqual(report['whole_trees_emitted'], 1)
            root = E.fromstring(next(iter(files.values())))
            self.assertEqual(root.find(".//Variable[@name='sender']").get('type'), new)

    def test_instant_lock_keeps_runtime_name_count_and_work_subtree(self):
        model = source('''<Root><InstantSemaphore LockManagerType="&quot;Global&quot;"
            SemaphoreName="&quot;$jobLock&quot;" SemaphoreCount="&quot;2&quot;">
            <Wait duration="&quot;3&quot;"/></InstantSemaphore></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', catalog())
        self.assertEqual(report['whole_trees_emitted'], 1)
        node = E.fromstring(next(iter(files.values()))).find('.//InstantSemaphore')
        self.assertEqual(node.attrib, dict(LockManagerType='Global',
            SemaphoreName='$jobLock', SemaphoreCount='2'))
        self.assertIsNotNone(node.find('Wait'))
        native = catalog()
        del native['nodes']['InstantSemaphore']
        self.assertFalse(convert_behaviors([model], 'Converted', native)[0])

    def test_work_graph_class_filters_use_native_logical_classes(self):
        for name in ('TagPoint', 'Slot', 'SmartObject'):
            model = source(f'''<Root><EntityClassFilter Class="&quot;{name}&quot;"
                Source="&quot;Child&quot;" prune="&quot;true&quot;" negprune="&quot;unknown&quot;"
                Child="&quot;station&quot;" Parent="&quot;&quot;"/></Root>''')
            native = catalog()
            self.assertFalse(convert_behaviors([model], 'Converted', native)[0])
            native['entity_classes'] = [name]
            files, _, report = convert_behaviors([model], 'Converted', native)
            self.assertEqual(report['whole_trees_emitted'], 1)
            node = E.fromstring(next(iter(files.values()))).find('.//EntityClassFilter')
            self.assertEqual(node.get('Class'), name)
            self.assertEqual(node.get('Child'), '$station')

    def test_station_distance_and_rain_gate_remain_runtime_decisions(self):
        model=source('''<Root><WeatherCondition failOnCondition="&quot;false&quot;"
            condition="&quot;$weather.rainIntensity &gt; 0.1&quot;">
            <GraphSearch Origin="&quot;workplace&quot;"><Nodalyzer Child="&quot;stations&quot;">
            <Child0><RangeSorter point="&quot;this.id&quot;" SortOrder="&quot;Ascending&quot;"
            Source="&quot;Child&quot;"/></Child0></Nodalyzer></GraphSearch>
            </WeatherCondition></Root>''')
        files,_,report=convert_behaviors([model],'Converted',catalog())
        self.assertEqual(report['whole_trees_emitted'],1)
        root=E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//WeatherCondition').get('condition'),'$weather.rainIntensity > 0.1')
        self.assertEqual(root.find('.//RangeSorter').get('point'),'$this.id')

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
