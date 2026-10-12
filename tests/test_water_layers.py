import struct
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_water_volumes import source_water, tree
from water_volumes import convert_water, read_water
from water_layers import select_water, repair_terrain


class WaterLayerTests(unittest.TestCase):
    def test_preserves_shared_initial_and_unclassified_layers(self):
        for layer, name, expected in [(0,'',1),(17,'sv_state0{x}',1),
                (17,'sv_state1{x}',0),(17,'infirmarium_state2{x}',0),
                (17,'setup{x}',1),(17,'part2{x}',1),(17,'unknown',1)]:
            data=bytearray(source_water());struct.pack_into('<H',data,28,layer)
            kept, excluded=select_water(tree(data,28),{17:name})
            self.assertEqual(len(kept),expected)
            self.assertEqual(len(excluded),1-expected)

    def test_removes_later_state_preserves_other_records_and_is_idempotent(self):
        old=source_water()
        active=bytearray(old);struct.pack_into('<H',active,28,0)
        struct.pack_into('<Q',active,44,444)
        source=tree(old+active,28)
        a=convert_water(old,{'offset':0,'size':len(old)},0,struct.pack('<2f',1000,1000))
        b=convert_water(active,{'offset':0,'size':len(active)},0,struct.pack('<2f',1000,1000))
        road=struct.pack('<I',7)+bytes(116)
        raw=tree(a+road+b,29).data
        target=SimpleNamespace(data=bytes(16)+raw,tree_offset=16,version=29)
        parse=lambda d:SimpleNamespace(data=d,tree_offset=16,version=29)
        with patch('water_layers.parse',side_effect=parse):
            out,removed=repair_terrain(target,source,{17:'sv_state1{x}'})
            self.assertEqual(len(removed),1)
            self.assertEqual(out[48:],road+b)
            again,removed=repair_terrain(parse(out),source,{17:'sv_state1{x}'})
            self.assertEqual(again,out);self.assertEqual(removed,[])
            self.assertEqual(read_water(parse(out))[1],{7:1,9:1})
