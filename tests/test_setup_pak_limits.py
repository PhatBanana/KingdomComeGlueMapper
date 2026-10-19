import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import setup_pak_limits as limits


class PakLimitTests(unittest.TestCase):
    def test_split_preserves_all_payloads_and_tables_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            files={'objects/a.cgf': b'a'*200, 'Objects/b.dds': b'b'*200,
                   'objects/c.mtl': b'c'*200, 'Libs/Tables/item.xml': b'<items/>',
                   'Quests/project.xml': b'<quest/>'}
            with zipfile.ZipFile(root/limits.TRAVEL, 'w') as z:
                for n,b in files.items(): z.writestr(n,b)
            changed=limits.split_assets(root,max_bytes=450)
            self.assertEqual(len(changed),4)
            actual={}
            for p in (root/'Data').glob('*.pak'):
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        self.assertNotIn(n,actual); actual[n]=z.read(n)
                self.assertLess(p.stat().st_size,450)
            self.assertEqual(files,actual)
            with zipfile.ZipFile(root/limits.TRAVEL) as z:
                self.assertEqual(set(z.namelist()),{'Libs/Tables/item.xml','Quests/project.xml'})
            self.assertEqual(limits.split_assets(root,max_bytes=450),{})

    def test_oversized_member_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            with zipfile.ZipFile(root/limits.TRAVEL,'w') as z:z.writestr('objects/a',b'a'*1000)
            before=(root/limits.TRAVEL).read_bytes()
            with self.assertRaisesRegex(ValueError,'Individual travel asset'):
                limits.split_assets(root,max_bytes=450)
            self.assertEqual((root/limits.TRAVEL).read_bytes(),before)
            self.assertEqual(len(list((root/'Data').iterdir())),1)

    def test_reject_mount_size_even_when_zip_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with zipfile.ZipFile(root/'large.pak','w') as z:z.writestr('a',b'a'*500)
            with patch.object(limits,'RETAIL_BYTES',500):
                with self.assertRaisesRegex(ValueError,'retail size limit'):limits.validate(root)

    def test_existing_shards_preserved_and_new_assets_sort_after_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            old=root/'Data/gluemappertravel_assets_0000.pak';old.write_bytes(b'unchanged')
            with zipfile.ZipFile(root/limits.TRAVEL,'w') as z:
                z.writestr('objects/a',b'a'*200); z.writestr('objects/b',b'b'*200)
            changed=limits.split_assets(root,max_bytes=450)
            self.assertIn('Data/gluemappertravel_assets_0001.pak',changed)
            self.assertEqual(old.read_bytes(),b'unchanged')


if __name__=='__main__':unittest.main()
