import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from vegetation_gi import upgrade_group,eligible_instance,GI_ENABLED


class VegetationGITests(unittest.TestCase):
    def test_upgrade_preserves_every_byte_except_gi_bit(self):
        for flags in (0,0xffffffff,0xa5a50000,GI_ENABLED):
            record=bytearray((i*37)%256 for i in range(360))
            struct.pack_into('<I',record,332,flags)
            upgraded=upgrade_group(record)
            self.assertEqual(upgraded[:332],record[:332])
            self.assertEqual(upgraded[336:],record[336:])
            self.assertEqual(struct.unpack_from('<I',upgraded,332)[0],flags|GI_ENABLED)
            self.assertEqual(upgrade_group(upgraded),upgraded)

    def test_hidden_and_proxy_render_nodes_still_excluded(self):
        self.assertTrue(eligible_instance(0))
        self.assertTrue(eligible_instance((1<<10)|(1<<16)|(1<<23)))
        for bit in (8,22,27):self.assertFalse(eligible_instance(1<<bit))

    def test_truncated_record_refused(self):
        with self.assertRaises(ValueError):upgrade_group(bytes(359))


if __name__=='__main__':unittest.main()
