import sys, unittest, xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_quest_holders import lower, chain, MANIFEST

P='Quests/project.xml'; L='Quests/level.xml'; D='Quests/dialog.xml'
def fixture():
    files={P:b'<Database><Skald><Project Name="host"><Assets/><Nodes><Region Name="region"/></Nodes><Definitions><Definition File="level.xml"/></Definitions></Project></Skald></Database>',
      L:b'<Database><Skald><Level Name="Region"><Ports/><Nodes><Talk Name="talk"/></Nodes><Definitions><Definition File="dialog.xml"/></Definitions></Level></Skald></Database>',
      D:b'''<Database><Skald><ForcedDialog Name="Talk"><Ports/><Sequences><Sequence Name="first" ExitScript="ItemUtils.GiveItem(dc.seller,player,'reward',1)&#10;KeepNormalWork()"/><Sequence Name="second" ExitScript="ItemUtils.GiveItem(player,dc.recipient,'reward',1)"/></Sequences></ForcedDialog></Skald></Database>'''}
    source=E.fromstring('''<Objects><Entity EntityGuid="AB" EntityId="91" EntityClass="Stash"/><Entity><EntityLinks><Link Name="worldStash[kind($enum:worldStashKind.lostQuestibleItems)]" TargetGuid="AB"/></EntityLinks></Entity></Objects>''')
    objects=b'<Objects><Entity Name="host" EntityGuid="00000001-0000-0000" EntityId="1"/><Entity Name="gm_container_91" EntityClass="Stash" EntityGuid="00000002-0000-0000" EntityId="2"/></Objects>'
    actors=[dict(soul='seller-id',items=[dict(item_id='reward',amount='1',amount_random_add='0',health='1')])]
    return files,actors,source,objects
class HolderTests(unittest.TestCase):
    def run_lower(self,files=None,objects=None,waiting=None):
        f,a,s,o=fixture()
        return lower(files or f,P,'new_game_started.State',a,{'dc.seller':'seller-id','player':'player-id','dc.recipient':'recipient-id'},s,objects or o,waiting)
    def test_native_ownership_and_source_script_preservation(self):
        c,l,r=self.run_lower(); root=E.fromstring(c[P])
        self.assertEqual(r['items'][0]['holders'],['seller-id','player-id','recipient-id'])
        self.assertEqual(len(root.findall('.//AddQuestItem')),3)
        self.assertNotIn(b'CreateItems',c[P]); self.assertNotIn(b'GiveItem',c[D])
        self.assertIn(b'KeepNormalWork()',c[D]);self.assertIn(b'StashAsset',c[P])
        self.assertIn(b'new_game_started.State',c[P]);self.assertIn(b'WaitingLink',l['waitinglinks.xml'])
        self.assertEqual(len(E.fromstring(c[D]).findall('.//Triggers/Port')),2)
        self.assertEqual(len(E.fromstring(c[L]).findall('.//Output/Edge')),2)
        self.assertFalse(r['runtime_verified'])
    def test_idempotent_upgrade(self):
        f,*_=fixture();c,l,r=self.run_lower();f.update(c)
        c2,l2,r2=self.run_lower(f,l['objects_mission0.xml'],l['waitinglinks.xml'])
        f2=dict(f);f2.update(c2)
        self.assertEqual(f,f2);self.assertEqual(l,l2);self.assertEqual(r,r2)
    def test_missing_backup_rejected(self):
        with self.assertRaisesRegex(ValueError,'converted Stash missing'):
            self.run_lower(objects=b'<Objects/>')
    def test_missing_role_rejected(self):
        f,*_=fixture();f[D]=f[D].replace(b'dc.seller',b'dc.unknown')
        with self.assertRaisesRegex(ValueError,'Unresolved.*role'):self.run_lower(f)
    def test_conditional_handover_rejected(self):
        f,*_=fixture();f[D]=f[D].replace(b'ItemUtils.GiveItem(dc.seller',b'if ok then ItemUtils.GiveItem(dc.seller')
        with self.assertRaisesRegex(ValueError,'control flow'):self.run_lower(f)
    def test_non_linear_ownership_rejected(self):
        for rows in ([dict(source='a',target='b'),dict(source='a',target='c')],
                     [dict(source='a',target='b'),dict(source='b',target='a')],
                     [dict(source='z',target='b')]):
            with self.assertRaises(ValueError):chain('a',rows)
if __name__=='__main__':unittest.main()
