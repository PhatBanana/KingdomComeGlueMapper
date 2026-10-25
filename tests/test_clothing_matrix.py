from itertools import product
from pathlib import Path
import sys
import tempfile
import json
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from clothing_lab.matrix import count_layer_space, signature, contract_passed, run_matrix, run_full_layers, load_resume
from clothing_lab.checklist import write_checklist
from clothing_lab.validation import validate
from test_clothing_lab import FakeCatalog, part, mesh


class ClothingMatrixTests(unittest.TestCase):
    def test_symbolic_native_exclusivity_matches_validator_for_every_stack(self):
        from test_clothing_equipment import equipment
        c=FakeCatalog();c.equipment=equipment()
        # These are different declared mesh regions and different archetypes,
        # but the native inventory reserves the same exclusive body subpart.
        parts=[part('inner'),part('inner_variant'),part('sleeves'),part('outer',layer='6')]
        for p,archetype in zip(parts,('51','51','99','72')):
            p['attributes']['ArmorArchetypeId']=archetype
            c.parts[p['id']]=p
        parts[2]['elements'][0]['EquipmentPart']='arms'
        c.equipment.layers['99']={('arms','5')}
        groups={}
        for p in parts:groups.setdefault(signature(p),[None]).append(p)
        accepted=0
        for selection in product(*groups.values()):
            selected=['body']+[p['id'] for p in selection if p]
            accepted+=contract_passed(validate(c,selected,inspect_assets=False))
        result=count_layer_space(parts,{p['id'] for p in parts},c.equipment)
        self.assertEqual(result['cartesian_total'],12)
        self.assertEqual(result['registration_constraints_pass'],accepted)
        self.assertEqual(accepted,6)  # Also exclude lower meshes discarded by native region selection.
        self.assertTrue(result['native_exclusive_slots_checked'])
        # Legacy evidence would incorrectly accept all twelve. Absence of the
        # native rules is explicit and must not claim the exclusive-slot check.
        legacy=count_layer_space(parts,{p['id'] for p in parts})
        self.assertEqual(legacy['registration_constraints_pass'],8)
        self.assertFalse(legacy['native_exclusive_slots_checked'])

    def test_checklist_requires_complete_matching_current_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);c=FakeCatalog();c.assets.root=folder;c.assets.overlay=None
            c.assets.signature=lambda:'fixture';c.rule_evidence=[];c.errors=[]
            c.parts['male_body']=part('male_body','Body','0',gender='Male')
            c.parts['male_dress']=part('male_dress',gender='Male')
            c.parts['male_dress']['attributes'].update(ArmorType='MaleDress',ArmorArchetypeId='28')
            c.native_roles['MaleDress']=dict(archetype='28',gender='Male',layers=[('torso','5')])
            c.meshes.update({'male_body.skin':mesh(),'male_dress.skin':mesh(.02)})
            c.presets['male']=dict(id='male',label='male',gender='Male',parts=['male_body','male_dress'])
            c.summary=lambda:dict(parts=list(c.parts.values()),presets=list(c.presets.values()))
            run_matrix(c,folder/'matrix',progress=lambda s:None)
            run_full_layers(c,'Female',folder/'full',progress=lambda s:None)
            (folder/'repair.json').write_text(json.dumps(dict(corrections=[],unresolved=[])))
            report=write_checklist(folder/'matrix',folder/'full',folder,folder/'report.md')
            self.assertGreater(report['confirmed_clothed'],0)
            self.assertIn('NOT VERIFIED',Path(report['confirmed_csv']).read_text())
            manifest=folder/'full/summary.json';data=json.loads(manifest.read_text())
            data['enumeration_complete']=False;manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'incomplete'):
                write_checklist(folder/'matrix',folder/'full',folder,folder/'report.md')
            data['enumeration_complete']=True;data['validation_contract']=1;manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'outdated'):
                write_checklist(folder/'matrix',folder/'full',folder,folder/'report.md')
            with self.assertRaisesRegex(ValueError,'exceed'):
                run_full_layers(c,'Female',folder/'too_large',maximum=1)
            self.assertFalse((folder/'too_large').exists())

    def test_symbolic_count_matches_every_cartesian_case(self):
        # Overlapping multi-part signatures and shared equipment archetypes
        # must both reject combinations; aggregate equal alternatives exactly.
        parts=[part('inner'),part('inner2'),part('outer',layer='9'),part('shoes',layer='2')]
        parts[2]['elements'].append(dict(EquipmentPart='feet',BodyLayerId='2'))
        parts[2]['attributes']['ArmorArchetypeId']='83'
        parts[3]['elements'][0]['EquipmentPart']='feet'
        parts[3]['attributes']['ArmorArchetypeId']='97'
        groups={}
        for p in parts:groups.setdefault(signature(p),[None]).append(p)
        count=0;total=0
        for group in product(*groups.values()):
            total+=1;slots=set();roles=set();draws=set();valid=True
            for p in filter(None,group):
                used=set(signature(p));role=p['attributes']['ArmorArchetypeId']
                draw={(e.get('EquipmentPart'), e.get('element_type','SkinElement')) for e in p['elements']}
                if slots & used or role in roles or draws & draw:valid=False
                slots|=used;roles.add(role)
                draws|=draw
            count+=valid
        result=count_layer_space(parts,{p['id'] for p in parts})
        self.assertEqual(result['cartesian_total'],total)
        self.assertEqual(result['registration_constraints_pass'],count)
        self.assertFalse(result['geometry_verified'])
        rejected=count_layer_space(parts,set())
        self.assertEqual(rejected['registration_constraints_pass'],1) # empty only

    def test_rules_only_does_not_claim_asset_or_geometry_validation(self):
        c=FakeCatalog();c.mesh=lambda p:(_ for _ in ()).throw(AssertionError('No mesh reads'))
        result=validate(c,['body','dress'],inspect_assets=False)
        self.assertTrue(contract_passed(result))
        self.assertFalse(result['geometry_checked']);self.assertFalse(result['assets_checked'])
        self.assertFalse(result['runtime_verified'])

    def test_resume_preserves_results_and_refuses_changed_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            c=FakeCatalog();c.assets.root=Path(folder);c.assets.overlay=None
            c.assets.signature=lambda:'same';c.rule_evidence=[];c.errors=[];c.summary=lambda:{}
            c.parts['male_body']=part('male_body','Body','0',gender='Male')
            c.parts['male_dress']=part('male_dress',gender='Male')
            c.meshes.update({'male_body.skin':mesh(),'male_dress.skin':mesh(.02)})
            c.presets['male']=dict(id='male',label='male',gender='Male',parts=['male_body','male_dress'])
            before=run_matrix(c,Path(folder)/'before',geometry=False,progress=lambda s:None)
            # Simulate an interrupted final write. Previously completed rows survive.
            with (Path(folder)/'before/cases.jsonl').open('a') as f:f.write('{')
            after=run_matrix(c,Path(folder)/'after',geometry=False,progress=lambda s:None,resume_from=Path(folder)/'before')
            self.assertEqual(before['genders'],after['genders'])
            self.assertEqual(before['enumerated_cases'],after['enumerated_cases'])
            self.assertGreater(after['reusable_cases'],0)
            manifest=Path(folder)/'before/summary.json'
            data=json.loads(manifest.read_text());data['validation_contract']=2
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'validator contract'):load_resume(Path(folder)/'before',c)
            c.assets.signature=lambda:'changed'
            with self.assertRaisesRegex(ValueError,'different assets'):load_resume(Path(folder)/'before',c)


if __name__=='__main__':unittest.main()
