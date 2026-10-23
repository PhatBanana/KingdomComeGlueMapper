from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile
from gambler_schedule_activation import prepare
from setup_gameplay import PROJECT, ENTRY

GAME=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2')


@unittest.skipUnless((GAME/'Data/Scripts.pak').exists(),'requires native scheduler/money contracts')
class FundsActivationTests(unittest.TestCase):
    def test_native_money_gate_actor_binding_and_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder);(package/'Data').mkdir()
            host=b'<Database><Skald><Project Name="test"><Assets/></Project></Skald></Database>'
            entry=b'<Database><Skald><Level Name="test"><Definitions/><Nodes/></Level></Skald></Database>'
            path=package/'Data/gluemappertravel.pak'
            with zipfile.ZipFile(path,'w') as z:z.writestr(PROJECT,host);z.writestr(ENTRY,entry)
            files={'objects_mission0.xml':b'<Objects><Entity Name="test" EntityId="1" EntityGuid="00000000-0000-0001"/><Entity Name="person" EntityId="2" EntityGuid="00000000-0000-0002"/></Objects>',
                   'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
            reports=[dict(actor_guid='00000000-0000-0002',funded_tag='test_funds',policy={'minimum_groschen':17})]
            before=path.read_bytes();updated,defs=prepare(package,GAME,files,reports,{})
            self.assertEqual(path.read_bytes(),before)
            node=E.fromstring(defs[ENTRY]).find('.//Nodes/gmDiceFunds')
            self.assertEqual(node.find("Constant[@Name='minimum']").get('Value'),'17')
            self.assertEqual(node.find("Constant[@Name='tag']").get('Value'),'test_funds')
            wrapper=E.fromstring(defs['Quests/GlueTravel/entry/dice_work/gmDiceFunds.xml'])
            gate=wrapper.find('.//SchedulerLinkActivation')
            self.assertEqual({(e.get('From'),e.get('To')) for e in gate},{('tag','LinkTag'),('eligible.hasmoney','IsActive')})
            self.assertFalse(any('Timer' in n.tag for n in wrapper.iter()))
            self.assertEqual(prepare(package,GAME,updated,reports,defs),(updated,defs))
            conflict=dict(reports[0],policy={'minimum_groschen':18})
            with self.assertRaisesRegex(ValueError,'activation collision'):prepare(package,GAME,updated,[conflict],defs)


if __name__=='__main__':unittest.main()
