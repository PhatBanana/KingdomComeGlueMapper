"""Render and interact with the standalone developer UI; no game assets required."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import struct
import unittest


def packed(values,kind):return base64.b64encode(struct.pack('<'+kind*len(values),*values)).decode()


@unittest.skipUnless(os.name=='nt' and importlib.util.find_spec('playwright'),'Optional Edge / Playwright renderer test')
class ClothingLabUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime=sync_playwright().start();cls.browser=cls.runtime.chromium.launch(channel='msedge',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.runtime.stop()

    def setUp(self):
        self.page=self.browser.new_page(viewport={'width':1280,'height':950});self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        parts=[dict(id=g+'_body',label=g+' body',family=g,kind='Body',gender=g,attributes={},elements=[dict(EquipmentPart='torso',BodyLayerId='0')]) for g in ('Female','Male')]
        parts.append(dict(id='dress',label='Test dress',family='Female',kind='Clothing',gender='Female',attributes=dict(HidingGroups='cover'),elements=[dict(EquipmentPart='torso',BodyLayerId='5')]))
        catalog=dict(parts=parts,presets=[dict(id=g,label=g,gender=g,parts=[g+'_body']+(['dress'] if g=='Female' else [])) for g in ('Female','Male')],groups=dict(cover=dict(index=4,region='torso')),native_rules=True,errors=[])
        row=dict(id='Female_body',kind='Body',element=dict(EquipmentPart='torso'),positions=packed([-.5,0,.1,.5,0,.1,0,0,1.5],'f'),normals=packed([0,1,0]*3,'f'),uv=packed([0,0,1,0,.5,1],'f'),indices=packed([0,1,2],'I'),alpha=packed([239]*3,'B'),subsets=[dict(first_index=0,num_indices=3,material_id=0)],materials=[dict(name='skin',threshold=0,opacity=1,shader='HumanSkin')],bones=[dict(name='leftForeArm',parent_index=None,bind=[1,0,0,0,0,1,0,0,0,0,1,0])],joints=packed([0]*12,'H'),weights=packed([1,0,0,0]*3,'f'),influences=4)
        self.page.add_init_script('''window.savedView=null;window.pywebview={api:{
        clothing_locations:async()=>({source:'source',target:'target',package:'package'}),
        clothing_open:async()=>('''+json.dumps(catalog)+'''),
        clothing_scene:async()=>({scene:{meshes:['''+json.dumps(row)+'''],errors:[]},validation:{status:'checked',findings:[]}}),
        clothing_capture:async(...args)=>{window.savedView=args;return 'report.png';},
        clothing_run:async options=>{window.auditOptions=options;return {started:true};},
        clothing_poll:async offset=>({running:false,done:1,total:1,results:offset?[]:[{id:'Female',label:'Female',status:'review',selected:['Female_body','dress'],findings:[{code:'fixture',message:'Inspect this case',severity:'review'}]}],counts:{review:1},report:'report.json',enumeration:{total:1,next_offset:1}})
        }};''')
        self.page.goto((Path(__file__).resolve().parents[1]/'tools/clothing_lab/ui/index.html').as_uri())
        self.page.locator('#lab-open').click();self.page.wait_for_function("document.querySelector('#lab-status').textContent.includes('presets')")
        self.page.wait_for_timeout(250)

    def tearDown(self):self.page.close();self.assertEqual(self.errors,[])

    def pixels(self):
        self.page.wait_for_timeout(180)
        return self.page.locator('canvas').evaluate("c=>c.toDataURL('image/png')")

    def test_rendered_masks_comparison_pose_and_capture(self):
        masked=self.pixels();self.page.uncheck('#lab-masks');visible=self.pixels();self.assertNotEqual(masked,visible)
        self.page.locator('#lab-pose').evaluate("e=>e.value='60'");self.page.locator('#lab-pose').dispatch_event('input');self.assertNotEqual(visible,self.pixels())
        self.page.check('#lab-compare');self.assertTrue(self.page.locator('#lab-legend').is_visible())
        self.page.locator('#lab-capture').click();self.page.wait_for_function('window.savedView!==null')
        self.assertEqual(self.page.evaluate('window.savedView[3].pose'),60)
        self.assertTrue(self.page.evaluate("window.savedView[2].startsWith('data:image/png;base64,')"))

    def test_gender_filter_batch_findings_and_small_window(self):
        self.page.select_option('#lab-gender','Male');self.assertEqual(self.page.locator('#lab-garment option').count(),0)
        self.page.select_option('#lab-gender','Female');self.page.select_option('#lab-mode','souls');self.page.locator('#lab-run').click()
        self.page.wait_for_function("document.querySelector('#lab-progress').textContent.includes('Batch finished')")
        self.assertEqual(self.page.evaluate('window.auditOptions.mode'),'souls')
        self.page.locator('.lab-result button').click();self.page.wait_for_function("document.querySelector('#lab-findings').textContent.includes('fixture')")
        for width in (1280,980):
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>window.innerWidth'))
        self.assertEqual(self.page.locator('.install-bar').count(),0)


if __name__=='__main__':unittest.main()
