import unittest,copy,tempfile,zipfile,json,hashlib,xml.etree.ElementTree as E
from pathlib import Path
from campaign_market_speech import retarget_market
from campaign_work_metaroles import adapt_hearing

class WorkSpeechNativeTests(unittest.TestCase):
 def test_native_worker_changes_only_selector_and_retains_all_gates(self):
  root=E.fromstring('''<BehaviorTree name="seller_market"><Root><Sequence><ExactMove/><EntityContextCheck context="seller_disableMarketCries"><Else><RandomGate opensWithChance="0.5"><Then><SuppressFailure><Function_speech_schedulerMonolog alias="" metarole="'NPC_VYVOLAVANI_NA_TRHU'" animationApproach="$enum:animationApproach.dontPlayDialogAnimations" skipInLod="true"/></SuppressFailure></Then></RandomGate></Else></EntityContextCheck><Wait duration="15s"/></Sequence></Root></BehaviorTree>''')
  fixed,report=retarget_market(root,'gm_imported_work')
  call=fixed.find('.//Function_speech_schedulerMonolog')
  self.assertEqual(call.get('metarole'),"'gm_imported_work'")
  call.set('metarole',"'NPC_VYVOLAVANI_NA_TRHU'")
  self.assertEqual(E.tostring(root),E.tostring(fixed))
  root.find('.//EntityContextCheck').set('context','other')
  with self.assertRaisesRegex(ValueError,'silence guard'):retarget_market(root,'gm_imported_work')
 def test_hearing_preserves_source_range_and_rejects_unknown_commands(self):
  command=dict(dialogue_command_type='8',int_param='5',who='9',target='0',char_param='',delay='')
  model=dict(topics={'one':dict(sequences=[dict(lines=[dict(commands=[command],response=None),dict(commands=[],response=dict(role_id='9',string_name='spoken'))])])})
  blob=b'<Root><Response><Text StringName="spoken"/></Response></Root>'
  rows=[dict(dialogue_hearing_id='5',dialogue_hearing_name='bark50')]
  native=E.fromstring('<Dialogue Hearing="50"/>')
  fixed,report=adapt_hearing(blob,model,rows,native)
  self.assertEqual(E.fromstring(fixed).find('Response').get('HearingOverride'),'50')
  command['delay']='1'
  with self.assertRaisesRegex(ValueError,'delayed'):adapt_hearing(blob,model,rows,native)

 def test_empty_entry_binds_verified_speaker_without_changing_spoken_content(self):
  from campaign_work_metaroles import bind_entry_speaker
  native=E.fromstring('<Root><Dialogue><Decision><Sequences><Sequence><Elements><Response Role="native_role"/></Elements></Sequence></Sequences></Decision></Dialogue></Root>')
  source=b'<Root><Dialogue><SelectedSouls><SelectedSoul Role="imported_actor"/></SelectedSouls><Decision><Sequences><Sequence EndType="Decision"><Elements/><Decision/></Sequence></Sequences></Decision></Dialogue></Root>'
  fixed=E.fromstring(bind_entry_speaker(source,native))
  response=fixed.find('.//Sequence/Elements/Response')
  self.assertEqual(response.get('Role'),'imported_actor');self.assertIsNone(response.find('Text'))
  with self.assertRaisesRegex(ValueError,'contract is unavailable'):bind_entry_speaker(source,E.Element('Root'))

class OwnedWorkSpeechTests(unittest.TestCase):
 def test_resume_accepts_unrelated_mission_edits_but_rejects_changed_worker(self):
  from setup_work_speech import validate_owned
  from setup_gameplay import ENTRY
  report=dict(conversations=[dict(name='gm_call',definition='Quests/GlueTravel/entry/speech/gm_call.xml',active_port='active')],
              actors=[dict(soul='a',jobs=['job'],worker=dict(template='private'))])
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder);(p/'Data/Levels/kcd1_travel').mkdir(parents=True)
   with zipfile.ZipFile(p/'Data/gluemappertravel.pak','w') as z:
    z.writestr(ENTRY,'<Document><Skald><Level><Definitions><Definition File="speech/gm_call.xml"/></Definitions><Nodes><gm_call Name="gm_call"><Edge From="entry_ready.State" To="active"/></gm_call></Nodes></Level></Skald></Document>')
    z.writestr('Libs/Storm/storm.xml','<storm><tasks><task name="roles"><source path="roles/gm_work_a.xml"/></task></tasks></storm>')
   def level(template):
    with zipfile.ZipFile(p/'Data/Levels/kcd1_travel/level.pak','w') as z:
     z.writestr('objects_mission0.xml','<Objects><Entity Name="unrelated"/><Entity Name="job" EntityGuid="00000001-0000-0000"><Properties guidSmartObjectType="'+template+'"/></Entity></Objects>')
     z.writestr('tables/ai/scheduler.xml','<Schedulers><S_ActivityLink TargetGuid="1"><Parameters BehaviorName="seller_market"/></S_ActivityLink></Schedulers>')
   level('private');validate_owned(p,report)
   from setup_work_speech import upgrade,RECORD
   with zipfile.ZipFile(p/'Data/gluemappertravel.pak','a') as z:z.writestr('AI/gm_work_a.xml',b'<Worker/>')
   report['resources']={'Data/gluemappertravel.pak':{'AI/gm_work_a.xml':hashlib.sha256(b'<Worker/>').hexdigest()}}
   (p/RECORD).write_text(json.dumps(report))
   self.assertEqual(upgrade(p,None,None)[0],{})
   # A private leaf mismatch must fail before mutating any archive or receipt.
   report['resources']['Data/gluemappertravel.pak']['AI/gm_work_a.xml']='bad'
   (p/RECORD).write_text(json.dumps(report))
   before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()}
   with self.assertRaisesRegex(ValueError,'Changed work speech resource'):upgrade(p,None,None)
   self.assertEqual(before,{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()})
   level('wrong')
   with self.assertRaisesRegex(ValueError,'seller binding'):validate_owned(p,report)

if __name__=='__main__':unittest.main()
