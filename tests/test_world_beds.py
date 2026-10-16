from pathlib import Path
import copy
from contextlib import contextmanager
import tempfile
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from world_beds import convert, frame, FAMILIES, SCHEDULER, HELPERS, ANIMATIONS, PREFIX
from region_travel import guid
from campaign_entity_links import guid_value
from cooking_pots import rotate


@contextmanager
def archive(files):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'test.pak'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        with zipfile.ZipFile(path) as z:
            yield z


def fixtures():
    source = ET.Element('Objects')
    visual = ET.Element('Objects')
    old_helpers = ET.Element('SmartObjects')
    new_helpers = ET.Element('SmartObjects')
    for f in FAMILIES:
        sid = str(100 + list(FAMILIES).index(f))
        e = ET.SubElement(source, 'Entity', EntityId=sid, EntityClass='Bed',
                          Pos=f'{sid},0,0', Rotate='1,0,0,0')
        p = ET.SubElement(e, 'Properties', soclasses_SmartObjectHelpers=f, object_Model='source.cgf')
        ET.SubElement(p, 'Bed', esSleepQuality='low', esReadingQuality='none')
        # Imported static visuals deliberately have no EntityId.
        ET.SubElement(visual, 'Entity', Name='glue_item_'+sid, Geometry='converted.cgf')
    ET.SubElement(visual, 'Entity', EntityId='1', Name='unrelated', EntityClass='Other')
    for family, name, pos, rot in [
        ('Bed','sittingLeft','0,-0.48,0','1,0,0,0'),
        ('Bed','sittingRight','0,0.48,0','0,0,0,1'),
        ('CampBed','lieSideRight','0,0,0','1,0,0,0'),
        ('Bed_StrictLeft','lieSideLeft','0,0,0','1,0,0,0'),
        ('ShelterBed','Entry','0,0,0','0,0,0,1'),
        ('TentBed','Entry','-0.25,0,0','1,0,0,0'),
        *[(f,'sitting','0,0,0','1,0,0,0') for f in FAMILIES if f.startswith('SleepingBench')]]:
        ET.SubElement(old_helpers,'Helper',className=family,name=name,pos=pos,rot=rot)
    for family, name, pos, rot in [
        ('Bed_1Place_High','sittingLeft','0.48,0,0','0.7071068,0,0,0.7071068'),
        ('Bed_1Place_High','sittingRight','-0.48,0,0','0.7071068,0,0,-0.7071068'),
        ('Bed_1Place_Bench','sitting','0,0,0','1,0,0,0'),
        ('Bed_1Place_Tent','Place0','0,0,0','1,0,0,0')]:
        ET.SubElement(new_helpers,'Helper',className=family,name=name,pos=pos,rot=rot)
    native = ET.Element('Objects'); hubs = ET.Element('database'); rows=ET.SubElement(hubs,'Schedulers')
    collections = ET.Element('SmartObjectAnimationCollections')
    for i, f in enumerate(sorted(set(FAMILIES.values()))):
        key = str(10+i*2); trigger=str(11+i*2)
        e=ET.SubElement(native,'Entity',EntityId=key,EntityGuid=guid('donor/'+key),
                        EntityClass='StanceSmartObject',Pos='10,20,30',Rotate='1,0,0,0')
        p=ET.SubElement(e,'Properties',soclass_SmartObjectHelpers=f,sWH_AI_EntityCategory='Bed',bOwnedByHome='1')
        ET.SubElement(p,'Bed',esSleepQuality='high',esReadingQuality='bed')
        ET.SubElement(p,'Script',esBedTypes='NormalBed')
        links=ET.SubElement(e,'EntityLinks')
        ET.SubElement(links,'Link',Name='mTrigger',TargetId=trigger)
        ET.SubElement(links,'Link',Name='+Heal[sleeper,25]',TargetId=key)
        t=ET.SubElement(native,'Entity',EntityId=trigger,EntityGuid=guid('donor/'+trigger),
                        EntityClass='BedTrigger',Pos='10,20,30.4',Scale='0.39,0.39,0.39')
        ET.SubElement(ET.SubElement(t,'EntityLinks'),'Link',Name='',TargetId=key)
        p=ET.SubElement(t,'Properties')
        ET.SubElement(p,'Click',sAction='lying',bCheckOwner='1',bAllowNoOwner='0')
        h=ET.SubElement(rows,'C_SmartHub',EntityGuid=str(guid_value(e.get('EntityGuid'))))
        ET.SubElement(h,'EffectHeal',Role='sleeper',HealRate='25')
        ET.SubElement(collections,'Collection',HelperSetName=f)
    files={'objects_mission0.xml':ET.tostring(visual), SCHEDULER:b'<database><Schedulers><Other EntityGuid="42"/></Schedulers></database>',
           'waitinglinks.xml':None, HELPERS:b'<SmartObjectAnimationCollections/>',
           ANIMATIONS:b'<database><SmartObjectAnimationss/></database>'}
    native_files={'objects_mission0.xml':ET.tostring(native),SCHEDULER:ET.tostring(hubs),HELPERS:ET.tostring(collections)}
    return source, files, native_files, ET.tostring(old_helpers), ET.tostring(new_helpers)


class WorldBedTests(unittest.TestCase):
    def test_selected_incremental_bed_preserves_existing_contracts(self):
        fixture = fixtures()
        src, files, native, old, new = fixture
        with archive({'objects_mission0.xml': ET.tostring(src)}) as a, archive(native) as b:
            first, _ = convert(files, a, b, old, new, guid, source_ids={'100'})
            second, report = convert(first, a, b, old, new, guid, source_ids={'100', '101'})
            self.assertEqual(report['converted'], 1)
            self.assertEqual(report['preserved_existing'][0]['source_id'], '100')
            before = ET.fromstring(first['objects_mission0.xml'])
            after = ET.fromstring(second['objects_mission0.xml'])
            for node in before:
                self.assertEqual(ET.tostring(node), ET.tostring(next(e for e in after if e.get('Name') == node.get('Name'))))
            with self.assertRaisesRegex(ValueError, 'not in the selected initial world'):
                convert(first, a, b, old, new, guid, source_ids={'999'})

    def test_talburg_exception_does_not_enable_other_quest_beds(self):
        from entity_visuals import initial_entity
        e = ET.Element('Entity', EntityId='123716', EntityClass='Bed',
                       Layer='conquest_destroyed_closed_unload{B60D7842-CCE2-431A-A50B-97073F5692BB}')
        self.assertTrue(initial_entity(e))
        e.set('EntityId', '123717')
        self.assertFalse(initial_entity(e))
        e.set('EntityId', '123716'); e.set('EntityClass', 'Chair')
        self.assertFalse(initial_entity(e))

    def run_conversion(self, fixture):
        src,files,native,old,new=fixture
        with archive({'objects_mission0.xml':ET.tostring(src)}) as a, archive(native) as b:
            return convert(files,a,b,old,new,guid)

    def test_every_family_has_closed_links_native_hub_and_unowned_trigger(self):
        fixture=fixtures(); result,report=self.run_conversion(fixture)
        self.assertEqual(report['converted'],8)
        root=ET.fromstring(result['objects_mission0.xml'])
        entities={e.get('EntityId'):e for e in root if e.get('EntityId')}
        hubs=ET.fromstring(result[SCHEDULER]).find('Schedulers')
        self.assertEqual(len(hubs),9); self.assertEqual(hubs[0].get('EntityGuid'),'42')
        for record in report['records']:
            bed=next(e for e in root if e.get('EntityGuid')==record['bed_guid'])
            hub=next(h for h in hubs if h.get('EntityGuid')==str(guid_value(record['bed_guid'])))
            self.assertEqual(hub.find('EffectHeal').get('HealRate'),'25')
            self.assertEqual(bed.find('Properties/Bed').get('esSleepQuality'),'low')
            self.assertEqual(bed.find('Properties').get('bOwnedByHome'),'0')
        for e in root:
            if not e.get('Name','').startswith(PREFIX):continue
            for link in e.findall('EntityLinks/Link'):
                self.assertEqual(entities[link.get('TargetId')].get('EntityGuid'),link.get('TargetGuid'))
            if e.get('EntityClass')=='BedTrigger':
                self.assertEqual(e.find('Properties/Click').get('bCheckOwner'),'0')
                self.assertEqual(e.find('Properties/Click').get('bAllowNoOwner'),'1')
        before=ET.fromstring(fixture[1]['objects_mission0.xml'])
        for e in before:
            self.assertEqual(ET.tostring(next(x for x in root if x.get('Name')==e.get('Name'))),ET.tostring(e))
        self.assertEqual(len(ET.fromstring(result[ANIMATIONS]).find('SmartObjectAnimationss')),8)

    def test_inactive_beds_not_activated(self):
        fixture=fixtures();fixture[0][0].set('Layer','later_state1{test}')
        result,report=self.run_conversion(fixture)
        self.assertEqual(report['converted'],7)
        self.assertEqual(report['inactive_layers'][0]['source_id'],'100')

    def test_missing_visual_fails_and_does_not_mutate_input(self):
        fixture=fixtures();root=ET.fromstring(fixture[1]['objects_mission0.xml']);root.remove(root[0])
        fixture[1]['objects_mission0.xml']=ET.tostring(root);before=copy.deepcopy(fixture[1])
        with self.assertRaisesRegex(ValueError,'Missing converted bed furniture'):self.run_conversion(fixture)
        self.assertEqual(fixture[1],before)

    def test_scaled_bed_and_duplicate_install_rejected(self):
        fixture=fixtures();fixture[0][0].set('Scale','2,1,1')
        with self.assertRaisesRegex(ValueError,'Scaled bed'):self.run_conversion(fixture)
        fixture=fixtures();result,_=self.run_conversion(fixture)
        fixture=(fixture[0],result,*fixture[2:])
        with self.assertRaisesRegex(ValueError,'already converted'):self.run_conversion(fixture)

    def test_preserves_existing_owned_contract(self):
        fixture=fixtures();result,_=self.run_conversion(fixture)
        root=ET.fromstring(result['objects_mission0.xml'])
        # Keep one complete existing contract and its hub; change its name/ownership.
        bed=next(e for e in root if e.get('Name')==PREFIX+'100_bed')
        trigger=next(e for e in root if e.get('Name')==PREFIX+'100_trigger')
        bed.set('Name','existing_rental');bed.find('Properties').set('bOwnedByHome','1')
        trigger.set('Name','existing_rental_trigger')
        original=ET.tostring(bed)
        fixture[1]['objects_mission0.xml']=ET.tostring(ET.fromstring(fixture[1]['objects_mission0.xml']))
        base=ET.fromstring(fixture[1]['objects_mission0.xml']);base.extend([bed,trigger]);fixture[1]['objects_mission0.xml']=ET.tostring(base)
        hs=ET.fromstring(fixture[1][SCHEDULER]); hs.find('Schedulers').append(next(h for h in ET.fromstring(result[SCHEDULER]).find('Schedulers') if h.get('EntityGuid')==str(guid_value(bed.get('EntityGuid')))))
        fixture[1][SCHEDULER]=ET.tostring(hs)
        updated,report=self.run_conversion(fixture)
        self.assertEqual(report['converted'],7)
        self.assertEqual(report['preserved_existing'],[{'source_id':'100','name':'existing_rental'}])
        self.assertEqual(ET.tostring(next(e for e in ET.fromstring(updated['objects_mission0.xml']) if e.get('Name')=='existing_rental')),original)

    def test_axis_and_tent_entry_mapping(self):
        *_,old,new=fixtures()
        _,q=frame(old,new,'CampBed')
        p=rotate(q,(0,1,0));self.assertAlmostEqual(p[0],1)
        offset,q=frame(old,new,'TentBed');self.assertEqual(offset,(-.25,0,0))
        offset,q=frame(old,new,'ShelterBed');self.assertAlmostEqual(abs(q[3]),1)


if __name__ == '__main__':unittest.main()
