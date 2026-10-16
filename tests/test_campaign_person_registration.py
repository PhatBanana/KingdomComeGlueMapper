import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_person_registration import PersonRegistration
from campaign_dependencies import ImportPlan
from quest_import import ast


class PersonRegistrationTests(unittest.TestCase):
    def test_two_people_accumulate_shared_resources_and_keep_individual_inventory(self):
        actors = [E.fromstring(f'<Entity EntityGuid="{n:016X}" EntityClass="NPC" Name="person{n}"/>') for n in (1,2)]
        def appearance(source,target,person,namespace,destination):
            self.assertFalse(destination.exists(), 'Real appearance builder requires a fresh destination')
            destination.mkdir()
            return dict(inventory=namespace+'_outfit',appearance={},archetype='human')
        def resources(target,person,character,namespace,**kwargs):
            files=dict(kwargs['resources'])
            previous=files.get('Libs/Storm/storm.xml',b'')
            files['Libs/Storm/storm.xml']=previous+person['name'].encode()
            files['Libs/Tables/rpg/soul__'+namespace+'.xml']=b'<soul/>'
            return files
        with tempfile.TemporaryDirectory() as temp, patch('character_person_ai.capture_person_ai',return_value={}):
            converter=PersonRegistration('source','target',None,actors,temp,'campaign',appearance,resources,
                item_name=lambda identity: {'native-arrows':'arrow_hunting'}[identity])
            all_outputs={}
            for n in (1,2):
                instance=E.fromstring(f'<Soul><EntityGuid>{n}</EntityGuid><StaticData><InventoryId>bag{n}</InventoryId></StaticData></Soul>')
                plan=ImportPlan(source=dict(instances=[ast(instance)],row={'soul_name':f'person{n}'},
                    provenance=[],loadouts=[{'items':[
                        {'item':'sword','kind':'weapon','amount':1,'equipped':True},
                        {'item':'arrows','kind':'weapon','amount':12,'equipped':False}]}]))
                identity,files,_=converter.convert(str(n),plan,{'inventories':{f'bag{n}':f'nativebag{n}'},
                    'items':{'sword':'native-sword','arrows':'native-arrows'}})
                self.assertEqual(identity,str(n))
                self.assertNotIn('Libs/Storm/storm.xml',files)
                self.assertFalse(all_outputs.keys() & files.keys())
                all_outputs.update(files)
                data=next(b for p,b in files.items() if p.endswith('_combined.xml'))
                refs=E.fromstring(data).findall('.//InventoryPresetRef')
                self.assertEqual(refs[-1].get('Name'),f'nativebag{n}')
                carried=E.fromstring(data).find('.//PresetItem')
                self.assertEqual(carried.attrib, dict(Name='arrow_hunting',ItemClassId='native-arrows',
                    Amount='12',Health='1',HealthVariation='0'))
                weapon=E.fromstring(next(b for p,b in files.items() if '/weapon_preset__' in p))
                self.assertEqual(weapon.find('.//weapon_preset_item').get('item_class_id'),'native-sword')
                self.assertEqual(len(weapon.findall('.//weapon_preset_item')),1)
            self.assertEqual(converter.finalize()['Libs/Storm/storm.xml'],b'person1person2')

    def test_shared_soul_variants_not_silently_collapsed(self):
        converter=PersonRegistration('s','t',None,[],'.','test')
        with self.assertRaisesRegex(ValueError,'one source instance'):
            converter.convert('id',ImportPlan(source={'instances':[{},{}]}),{})


if __name__=='__main__':unittest.main()
