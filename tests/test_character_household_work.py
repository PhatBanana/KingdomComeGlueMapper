from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_household_work as work
from campaign_entity_links import native_guid


class HouseholdTests(unittest.TestCase):
    def source(self):
        return E.fromstring('''<BehaviorTrees><BehaviorTree name="Cooking"><Root>
            <GraphSearch Origin="__area.id" depth="1" EdgePruning="parent" includeOrigin="false"
              AllowedEdges="" SubGraph="" SetOperationChoice="Intersection|And">
              <UnionOp><CategoryFilter categories="Furnace" Source="Child"/>
                <CategoryFilter categories="fireplace" Source="Child"/></UnionOp>
              <HasBehaviorFilter BehaviorList="Cooking" FilterChoice="Requestable"/><Nodalyzer/>
            </GraphSearch><CallBehavior Target="furnace" BehaviorName="Cooking"/>
            </Root></BehaviorTree></BehaviorTrees>''')

    def test_source_search_is_checked_not_guessed_from_nearest_prop(self):
        work.cooking_source_contract(self.source())
        for field, value in [('depth', '2'), ('Origin', 'this.id'), ('EdgePruning', '')]:
            with self.subTest(field=field):
                source = self.source(); source.find('.//GraphSearch').set(field, value)
                with self.assertRaises(ValueError): work.cooking_source_contract(source)

    def fixtures(self):
        entry = dict(target_links=[dict(TargetId='10', Name=''), dict(TargetId='20', Name='parent')])
        mission = E.Element('Objects'); pots = []
        for i in (10, 20, 30):
            owner = E.Element('Entity', EntityId=str(i)); E.SubElement(owner, 'Properties', sWH_AI_EntityCategory='Furnace')
            pot = E.Element('Entity', EntityId=str(i+1))
            pots.append((pot, owner, 'home'))
            e = E.SubElement(mission, 'Entity', EntityId=str(i), EntityGuid=native_guid(i),
                Name='gm_cooking_'+str(i+1)+'_7', EntityClass='FireplaceSmartObject')
            E.SubElement(e, 'Properties', guidSmartObjectType='fireplace')
        leaf = E.fromstring('''<C_SmartHub EntityGuid="7" IgnoreDeadEnds="false" StupidHub="false">
            <PostSearchData><SmartHubPostSearchData><ElementInitializers>
              <ElementInitializerEnableBehaviorForNPC TargetGuid="7" Role="cooking" Behavior="takingHerbs"/>
            </ElementInitializers></SmartHubPostSearchData></PostSearchData></C_SmartHub>''')
        native = ('fireplace', E.Element('S_ActivityLink'), {'7': leaf})
        return entry, mission, pots, native

    def test_only_direct_source_fire_is_bound_and_effects_follow_shared_identity(self):
        args = self.fixtures()
        resources, _ = work.cooking_resources(*args)
        self.assertEqual([e.get('EntityGuid') for e, _ in resources], [native_guid(10)])
        self.assertEqual(resources[0][1].get('EntityGuid'), '10')
        self.assertEqual(resources[0][1].find('.//ElementInitializerEnableBehaviorForNPC').get('TargetGuid'), '10')
        self.assertEqual(args[3][2]['7'].get('EntityGuid'), '7')

    def test_missing_or_incompatible_fireplace_is_not_silently_replaced(self):
        for change in ('missing', 'template', 'effects', 'duplicate'):
            with self.subTest(change=change):
                entry, mission, pots, native = self.fixtures()
                if change == 'missing': mission.remove(mission[0])
                elif change == 'template': mission[0].find('Properties').set('guidSmartObjectType', 'other')
                elif change == 'effects': native[2].clear()
                else: mission.append(E.fromstring(E.tostring(mission[0])))
                with self.assertRaises(ValueError): work.cooking_resources(entry, mission, pots, native)

    def test_area_binding_must_refer_to_the_validated_source_program(self):
        entry = dict(area_template={'sa_smart_area_id': 'home'})
        tables = {'ai/sa_behaviour_tag': {'rows': [dict(sa_behaviour_tag_id='cook',
            sa_behaviour_tag_name='Cooking', tree_file='final/sa_home.xml', tree_name='Cooking')]},
            'ai/sa_smart_area2sa_behaviour_tag': {'rows': [dict(sa_smart_area_id='home', sa_behaviour_tag_id='cook')]}}
        self.assertEqual(work.binding(entry, 'Cooking', tables)['tree_name'], 'Cooking')
        tables['ai/sa_behaviour_tag']['rows'][0]['tree_name'] = 'OtherCooking'
        with self.assertRaises(ValueError): work.binding(entry, 'Cooking', tables)


if __name__ == '__main__': unittest.main()
