import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_work_helpers import WorkHelperAdapter, assemble
from campaign_dependencies import DependencyImporter


def library(pos='0,0,0', rotation='1,0,0,0', declaration="Animation('pick','');"):
    root = E.Element('SmartObjectsLibrary')
    E.SubElement(root, 'Class', name='Tool')
    E.SubElement(root, 'Helper', className='Tool', name='handle', pos=pos,
                 rot=rotation, description=declaration)
    return root


def adapter(source=None, native=None):
    collections = E.fromstring('<SmartObjectAnimationCollections><Family HelperSetName="Tool">'
        '<SmartObjectHelperSetAnimationCollection HashValue="123"/>'
        '</Family></SmartObjectAnimationCollections>')
    return WorkHelperAdapter(source if source is not None else library(),
                             native if native is not None else library(), collections)


class WorkHelpersTests(unittest.TestCase):
    def test_native_animation_and_new_placement_are_both_emitted(self):
        importer = DependencyImporter({'work_helpers':adapter(native=library(rotation='-1,0,0,0'))})
        self.assertEqual(importer.ensure('work_helpers','tool'), 'Tool')
        objects = E.fromstring('<Objects><Entity EntityClass="SmartObjectHolder" '
            'EntityGuid="00000001-0000-0000" Pos="100,200,30">'
            '<Properties soclass_SmartObjectHelpers="Tool"/></Entity></Objects>')
        output = assemble(objects, importer.files)
        table = E.fromstring(output['world/registration/tables/ai/smartobjectanimations.xml'])
        row = table.find('./SmartObjectAnimationss/SmartObjectAnimations')
        self.assertEqual(row.get('EntityGuid'),'1')
        self.assertEqual(row.get('Hash'),'123')
        self.assertEqual(row.find('SmartObjectTransform').get('Position'),'100,200,30')

    def test_same_name_different_geometry_or_animation_cannot_register(self):
        for native in [library(pos='1,0,0'),library(declaration="Animation('other','');")]:
            importer = DependencyImporter({'work_helpers':adapter(native=native)})
            self.assertIsNone(importer.ensure('work_helpers','tool'))
            self.assertFalse(importer.files)

    def test_missing_collection_and_point_are_rejected(self):
        a = adapter()
        a.collections.clear()
        with self.assertRaisesRegex(ValueError,'collection'): a.plan('tool')
        b = adapter()
        b.native.remove(b.native.find('Helper'))
        with self.assertRaisesRegex(ValueError,'point sets'): b.plan('tool')

    def test_emission_requires_animation_dependency(self):
        objects = E.fromstring('<Objects><Entity EntityClass="SmartObjectHolder">'
            '<Properties soclass_SmartObjectHelpers="Tool"/></Entity></Objects>')
        with self.assertRaisesRegex(ValueError,'no converted'): assemble(objects,{})

    def test_scaled_station_is_not_written_with_unscaled_animation_targets(self):
        importer = DependencyImporter({'work_helpers':adapter()})
        importer.ensure('work_helpers','tool')
        objects = E.fromstring('<Objects><Entity EntityClass="SmartObjectHolder" '
            'EntityGuid="00000001-0000-0000" Pos="1,2,3" Scale="2,2,2">'
            '<Properties soclass_SmartObjectHelpers="Tool"/></Entity></Objects>')
        with self.assertRaisesRegex(ValueError,'Scaled work helper'): assemble(objects,importer.files)


if __name__ == '__main__': unittest.main()
