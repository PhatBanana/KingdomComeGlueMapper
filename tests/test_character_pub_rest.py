from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_pub_rest as work


class PubRestTests(unittest.TestCase):
    def fixture(self):
        pub=E.fromstring('''<BehaviorTrees><BehaviorTree name="resting"><Root>
          <GraphSearch Origin="__area.id" depth="1" EdgePruning="parent"><CategoryFilter categories="pubTable"/>
          <NegationOp><LinkTagFilter tag="reserved"/></NegationOp></GraphSearch>
          <CallBehavior BehaviorName="getBench"/></Root></BehaviorTree></BehaviorTrees>''')
        table=E.fromstring('''<BehaviorTrees><BehaviorTree name="getBench"><Root>
          <GraphSearch Origin="__object.id" depth="1" EdgePruning="parent"><CategoryFilter categories="Seat"/></GraphSearch>
          <GraphSearch Origin="__object.id" depth="1" EdgePruning="parent"><CategoryFilter categories="Seat"/></GraphSearch>
          </Root></BehaviorTree></BehaviorTrees>''')
        return pub,table

    def test_source_selection_cannot_expand_to_unrelated_or_reserved_resources(self):
        work.source_contract(*self.fixture())
        for index,tag,key,value in ((0,'GraphSearch','depth','2'),(0,'LinkTagFilter','tag','other'),
                (1,'CategoryFilter','categories','TagPoint'),(1,'GraphSearch','Origin','this.id')):
            with self.subTest(tag=tag,index=index):
                roots=self.fixture();roots[index].find('.//'+tag).set(key,value)
                with self.assertRaises(ValueError):work.source_contract(*roots)

    def test_reserved_and_parent_edges_are_not_public(self):
        entity=E.fromstring('''<Entity><EntityLinks><Link Name="parent" TargetId="1"/>
          <Link Name="reserved" TargetId="2"/><Link Name="seat,reserved" TargetId="3"/>
          <Link Name="" TargetId="4"/><Link Name="bench_front" TargetId="5"/>
          </EntityLinks></Entity>''')
        self.assertEqual([l.get('TargetId') for l in work.public_edges(entity)],['4','5'])


if __name__=='__main__':unittest.main()
