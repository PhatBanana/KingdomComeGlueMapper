import copy
import math
import unittest
import xml.etree.ElementTree as E

from character_dice_resources import (EXACT, REQUIRED, SEAT_TEMPLATE, TABLE_TEMPLATE,
                                     build, relative_pose, source_roles)

HELPERS=E.fromstring('<SmartObjects><Helper className="Bench_1Place" description="Category(Sit)" pos="0,0,0" rot="1,0,0,0"/></SmartObjects>')


def fixture():
    names = ['table'] + sorted(REQUIRED - {'table'})
    entities = {name:E.Element('Entity', EntityId=str(i+1), EntityGuid=str(i+100),
        EntityClass='SmartObjectHolder', Pos=f'{i},0,0', Rotate='1,0,0,0') for i,name in enumerate(names)}
    for name, entity in entities.items():
        E.SubElement(entity, 'Properties', guidSmartObjectType=TABLE_TEMPLATE if name == 'table' else SEAT_TEMPLATE)
        E.SubElement(entity, 'EntityLinks')
    def link(a, tag, b):
        target=entities[b]
        E.SubElement(entities[a].find('EntityLinks'), 'Link', Name=tag,
                     TargetId=target.get('EntityId'), TargetGuid=target.get('EntityGuid'))
    for name in names[1:]: link('table',name,name)
    link('table','_opponent|,use','seat1_SO'); link('table','_challenger|,use','seat2_SO')
    for side in ('1','2'):
        for tag,role in [('cupStash','hiddenSlot'),('cupOnTable','cupSlot'),('cupSlot','cupSlot'),
                         ('hiddenSlot','hiddenSlot'),('hiddenDiceOnTable','hiddenDiceOnTable'),('diceOnTable','diceOnTable')]:
            link('seat'+side+'_SO',tag,role+side)
    native={e.get('EntityId'):e for e in entities.values()}
    source=copy.deepcopy(native)
    for e in source.values():e.set('Pos',str(float(e.get('Pos').split(',')[0])+100)+',5,0')
    for name in ('seat1_SO','seat2_SO'):
        source[entities[name].get('EntityId')].find('Properties').set('soclasses_SmartObjectHelpers','Bench_1Place')
    source_table=source[entities['table'].get('EntityId')]
    for side in ('1','2'):
        source_table.find(f"EntityLinks/Link[@Name='seat{side}']").set('TargetId',entities['seat'+side+'_SO'].get('EntityId'))
    return source_table,source,entities['table'],native


class DiceResourcesTests(unittest.TestCase):
    def test_source_owned_contacts_and_closed_remapped_graph(self):
        table,source,donor,native=fixture()
        result=build(table,source,donor,native,500,HELPERS)
        ids={e.get('EntityId') for e in result}
        guids={e.get('EntityId'):e.get('EntityGuid') for e in result}
        self.assertEqual(len(result),len(REQUIRED))
        for entity in result:
            for link in entity.findall('EntityLinks/Link'):
                self.assertIn(link.get('TargetId'),ids)
                self.assertEqual(link.get('TargetGuid'),guids[link.get('TargetId')])
        roles=source_roles(table,source)
        for name in EXACT:
            actual=next(e for e in result if e.get('Name').endswith('_'+name))
            self.assertEqual(tuple(map(float,actual.get('Pos').split(','))),
                             tuple(map(float,roles[name].get('Pos').split(','))))
        self.assertEqual([E.tostring(e) for e in result],[E.tostring(e) for e in build(table,source,donor,native,500,HELPERS)])

    def test_external_ownership_rejected(self):
        table,source,donor,native=fixture()
        E.SubElement(donor.find('EntityLinks'),'Link',Name='owner',TargetId='999999')
        with self.assertRaisesRegex(ValueError,'external ownership'):build(table,source,donor,native,500,HELPERS)

    def test_donor_quest_disable_link_is_not_inherited(self):
        table,source,donor,native=fixture()
        E.SubElement(donor.find('EntityLinks'),'Link',Name='dice_disabledMinigame',TargetId=donor.get('EntityId'))
        result=build(table,source,donor,native,500,HELPERS)
        self.assertFalse(any(e.find("EntityLinks/Link[@Name='dice_disabledMinigame']") is not None for e in result))

    def test_rotated_contact_preserves_local_offset(self):
        point=E.Element('Entity',EntityId='p',Pos='11,0,0')
        old=E.Element('Entity',EntityId='o',Pos='10,0,0')
        new=E.Element('Entity',EntityId='n',Pos='100,200,0',Rotate=f'{math.sqrt(.5)},0,0,{math.sqrt(.5)}')
        pos,_=relative_pose(point,old,new,{'p':point,'o':old},{'n':new})
        for actual,expected in zip(pos,(100,201,0)):self.assertAlmostEqual(actual,expected)


if __name__ == '__main__':unittest.main()
