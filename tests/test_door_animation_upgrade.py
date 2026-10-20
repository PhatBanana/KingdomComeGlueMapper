from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from door_animation_upgrade import refresh, plan
from seating_animations import install, HELPERS, ANIMATIONS
from test_cooking_pots import archive


def fixture():
    return {
        'objects_mission0.xml': b'''<Objects>
        <Entity Name="gm_door_anywhere" EntityClass="AnimDoor" EntityGuid="00000001-0000-0000" Pos="10,20,30" Rotate="0,0,0,1">
        <Properties soclass_SmartObjectHelpers="nativeDoor"><Lock bLocked="1"/></Properties></Entity>
        <Entity Name="gm_rental_door" EntityClass="AnimDoor" EntityGuid="00000002-0000-0000" Pos="40,50,60">
        <Properties soclass_SmartObjectHelpers="nativeDoor"/></Entity>
        <Entity Name="nativeDoor" EntityClass="AnimDoor" EntityGuid="00000003-0000-0000" Pos="1,2,3"/>
        </Objects>''',
        HELPERS: b'''<SmartObjectAnimationCollections><Collection HelperSetName="nativeDoor">
        <SmartObjectHelperSetAnimationCollection HashValue="12345"><AnimationsMap/></SmartObjectHelperSetAnimationCollection>
        </Collection></SmartObjectAnimationCollections>''',
        ANIMATIONS: b'''<database><SmartObjectAnimationss version="1">
        <SmartObjectAnimations EntityGuid="1" Hash="0" AllowRuntimeAnimValidationFallback="true">
        <SmartObjectTransform Position="10,20,30" Rotation="0,0,0,1"/></SmartObjectAnimations>
        <SmartObjectAnimations EntityGuid="99" Hash="321"><Animations/></SmartObjectAnimations>
        </SmartObjectAnimationss></database>''',
        'other': b'unchanged',
    }


class DoorAnimationTests(unittest.TestCase):
    def test_packages_without_converted_doors_need_no_animation_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'Data/Levels/kcd1_travel/level.pak'
            path.parent.mkdir(parents=True)
            with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml',b'<Objects/>')
            changes,report=plan(root)
            self.assertEqual(changes,{})
            self.assertEqual(report['doors'],0)

    def test_repairs_zero_and_missing_rental_rows_without_changing_world(self):
        files=fixture(); result,report=refresh(files)
        self.assertEqual(report['repaired'],2)
        self.assertFalse(report['runtime_verified'])
        self.assertEqual({n:b for n,b in result.items() if n!=ANIMATIONS},
                         {n:b for n,b in files.items() if n!=ANIMATIONS})
        rows=E.fromstring(result[ANIMATIONS]).find('SmartObjectAnimationss')
        self.assertEqual(len(rows),3)
        for identity,position in [('1','10,20,30'),('2','40,50,60')]:
            row=rows.find(f"SmartObjectAnimations[@EntityGuid='{identity}']")
            self.assertEqual(row.get('Hash'),'12345')
            self.assertEqual(row.find('SmartObjectTransform').get('Position'),position)
            self.assertIsNone(row.find('Animations'))
        self.assertEqual(rows.find("SmartObjectAnimations[@EntityGuid='99']").get('Hash'),'321')
        again,report=refresh(result)
        self.assertEqual(again,result);self.assertEqual(report['repaired'],0)

    def test_clean_setup_and_migration_register_identical_door_contracts(self):
        files=fixture()
        with archive({HELPERS:files[HELPERS]}) as native:
            built,_=install(files,native)
        migrated,_=refresh(files)
        select=lambda blob:{r.get('EntityGuid'):E.tostring(r) for r in E.fromstring(blob).iter('SmartObjectAnimations')}
        # Attribute ordering is not semantic; compare parsed fields and children.
        a,b=select(built[ANIMATIONS]),select(migrated[ANIMATIONS])
        for key in ('1','2'):
            x,y=E.fromstring(a[key]),E.fromstring(b[key])
            self.assertEqual(x.attrib,y.attrib)
            self.assertEqual(x[0].attrib,y[0].attrib)

    def test_preserves_valid_native_profile_checks(self):
        files=fixture(); files[ANIMATIONS]=files[ANIMATIONS].replace(b'Hash="0"',b'Hash="12345"').replace(b'<SmartObjectTransform',b'<Animations><Pair/></Animations><SmartObjectTransform')
        result,_=refresh(files)
        row=E.fromstring(result[ANIMATIONS]).find(".//SmartObjectAnimations[@EntityGuid='1']")
        self.assertIsNotNone(row.find('Animations/Pair'))

    def test_invalid_collection_hash_and_variants_fail_before_mutation(self):
        for value in ('0','',str(2**64),'bad'):
            files=fixture();files[HELPERS]=files[HELPERS].replace(b'12345',value.encode())
            original=dict(files)
            with self.assertRaisesRegex(ValueError,'collection hash'):refresh(files)
            self.assertEqual(files,original)
        files=fixture();files[HELPERS]=files[HELPERS].replace(b'</Collection>',b'<SmartObjectHelperSetAnimationCollection HashValue="456"/></Collection>')
        with self.assertRaisesRegex(ValueError,'Ambiguous'):refresh(files)

    def test_missing_family_duplicate_rows_and_stale_transforms_are_rejected(self):
        for before,after,message in [
            (b'HelperSetName="nativeDoor"',b'HelperSetName="missing"','family'),
            (b'Position="10,20,30"',b'Position="99,99,99"','transform'),
            (b'Hash="0"',b'Hash="987"','different animation'),
            (b'<SmartObjectTransform',b'<Animations/><SmartObjectTransform','baked animation'),
            (b'</SmartObjectAnimationss>',b'<SmartObjectAnimations EntityGuid="1" Hash="0"/></SmartObjectAnimationss>','Duplicate'),
        ]:
            files=fixture();files={n:b.replace(before,after) for n,b in files.items()}
            with self.assertRaisesRegex(ValueError,message):refresh(files)

    def test_mount_alias_and_level_table_are_updated_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lp='Data/Levels/kcd1_travel/level.pak';tp='Data/gluemappertravel.pak'
            (root/lp).parent.mkdir(parents=True)
            (root/'mod.manifest').write_text('<mod><info><modid>testmod</modid></info></mod>')
            files=fixture();alias='Mods/testmod/Data/Levels/kcd1_travel/'+ANIMATIONS
            with zipfile.ZipFile(root/lp,'w') as z:
                for n,b in files.items():z.writestr(n,b)
            with zipfile.ZipFile(root/tp,'w') as z:z.writestr(alias,b'stale table')
            changes,report=plan(root)
            self.assertEqual(changes[lp][ANIMATIONS],changes[tp][alias])
            self.assertTrue(report['mounted_table_repaired'])
            # A previously repaired level still repairs an out-of-date mount.
            files[ANIMATIONS]=changes[lp][ANIMATIONS]
            with zipfile.ZipFile(root/lp,'w') as z:
                for n,b in files.items():z.writestr(n,b)
            changes,_=plan(root)
            self.assertEqual(set(changes),{tp})


if __name__=='__main__': unittest.main()
