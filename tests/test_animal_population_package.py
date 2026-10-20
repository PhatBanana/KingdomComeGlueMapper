import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from animal_population import LEVEL_FILES, MANIFEST, owned_state
from build_animal_population_upgrade import build, plan, LEVEL, TRAVEL
from campaign_trigger_areas import write_areas


def fixture(mod):
    mod.mkdir(parents=True)
    (mod/'mod.manifest').write_text('<Mod><info><modid>example</modid></info></Mod>')
    files={'objects_mission0.xml':b'<Objects><Entity EntityId="1" EntityGuid="00000001-0000-0000" Name="untouched"/></Objects>',
        'tables/ai/scheduler.xml':b'<Table><Schedulers/></Table>',
        'triggerareas.fubar':write_areas([],1),
        'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
        'whdata_0':b'<WHLevelData><SoulList><Souls/></SoulList></WHLevelData>'}
    for rel in (LEVEL,TRAVEL):(mod/rel).parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(mod/LEVEL,'w') as z:
        for k,b in files.items():z.writestr(k,b)
        z.writestr('terrain/keep.bin',b'geometry unchanged')
    with zipfile.ZipFile(mod/TRAVEL,'w') as z:
        z.writestr('Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml',files['tables/ai/scheduler.xml'])
        z.writestr('Quests/existing.xml',b'quest unchanged')
    return files


class AnimalPackage(unittest.TestCase):
    def test_overlay_preserves_unrelated_files_and_is_resume_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mod=root/'mod';files=fixture(mod)
            changed=dict(files)
            changed['tables/ai/scheduler.xml']=b'<Table><Schedulers/><metadata animal="1"/></Table>'
            report=dict(version=1,pending=[],owned_guids=[],owned_state=owned_state(changed,set()),runtime_verified=False)
            changed[MANIFEST]=json.dumps(report).encode()
            before={p:p.read_bytes() for p in mod.rglob('*') if p.is_file()}
            with patch('build_animal_population_upgrade.convert',return_value=(changed,report)):
                result=build(root,root,mod,root/'stage')
            self.assertTrue(result['source_package_unchanged'])
            self.assertEqual({p:p.read_bytes() for p in before},before)
            staged=root/'stage/package'
            with zipfile.ZipFile(staged/TRAVEL) as z:
                self.assertEqual(z.read('Quests/existing.xml'),b'quest unchanged')
                self.assertEqual(z.read('Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml'),changed['tables/ai/scheduler.xml'])
            (staged/'mod.manifest').write_bytes((mod/'mod.manifest').read_bytes())
            with patch('build_animal_population_upgrade.convert',return_value=(changed,report)):
                replacements,_=plan(root,root,staged)
            self.assertFalse(any(replacements.values()))

    def test_partial_stage_requires_explicit_option_and_records_omissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mod=root/'mod';files=fixture(mod)
            report=dict(pending=[dict(reason='unresolved master')])
            with patch('build_animal_population_upgrade.convert',return_value=(files,report)):
                with self.assertRaisesRegex(ValueError,'require adapters'):build(root,root,mod,root/'stage')
            self.assertEqual(json.loads((root/'stage/report.json').read_text()),report)
            self.assertFalse((root/'stage/package').exists())

    def test_disagreeing_mounted_scheduler_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mod=root/'mod';files=fixture(mod)
            with zipfile.ZipFile(mod/TRAVEL,'w') as z:
                z.writestr('Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml',b'stale')
            with patch('build_animal_population_upgrade.convert',return_value=(files,{})):
                with self.assertRaisesRegex(ValueError,'differs from the level'):plan(root,root,mod)


if __name__=='__main__': unittest.main()
