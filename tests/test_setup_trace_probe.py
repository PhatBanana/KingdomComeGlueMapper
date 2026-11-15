import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import setup_trace_probe as probe

TOOLING_LUA = ('local g=GlueTraceProbe if not g then g={n=0,first_t=Calendar.GetWorldTime()} GlueTraceProbe=g end '
               'g.ticked=true g.n=g.n+1 g.t=Calendar.GetWorldTime()')
PROJECT = b'''<Database Name="brambora"><Skald><Project Name="GlueTravel_kcd1">
<Definitions><Definition File="entry/kcd1_travel.xml" /></Definitions><Nodes><kcd1_travel Name="kcd1_travel" /></Nodes>
<Assets><SoulAsset Name="travel_player" SharedSoulGuids="x" /></Assets></Project></Skald></Database>'''
ENTRY = b'''<Database Name="brambora"><Skald><Level Name="kcd1_travel" HibernateMode="Auto">
<Ports><Port Name="arrived" Direction="Out" Type="trigger" /></Ports><Definitions />
<Nodes><Output Name="Output"><Edge From="OnWake" To="arrived" /><Edge From="OnLevelSwitched" To="arrived" /></Output></Nodes>
</Level></Skald></Database>'''
OBJECTS = b'''<Objects><Entity Name="GlueTravel_kcd1" EntityClass="SmartObjectHolder" EntityId="7" EntityGuid="27288a09-b45f-0d5c" Pos="1,2,3">
<Properties bSaved_by_game="0" /><EntityLinks><Link Name="module" TargetId="6" TargetGuid="bf9f12b9-718c-335b" /></EntityLinks></Entity>
<Entity Name="other" EntityClass="X" EntityId="41" EntityGuid="00000001-0001-0001" Pos="9,9,9" /></Objects>'''
WAITING = b'''<StaticLinksInfo version="1"><WaitingLinks><WaitingLink SourceId="27288a09-b45f-0d5c" TargetId="bf9f12b9-718c-335b">
<LinkDefinition>module</LinkDefinition></WaitingLink></WaitingLinks></StaticLinksInfo>'''
DEFINITIONS = b'''<Root><Nodes>
<Definition TypeName="EnableBehavior" Name="EnableBehavior"><Ports><CompileTimePort Name="IsActive" /><CompileTimePort Name="Behavior" /><CompileTimePort Name="SmartEntity" /></Ports></Definition>
<Definition TypeName="EnableBehavior" Name="EnableBehavior_Stag"><Ports /></Definition>
<Definition TypeName="InstantSendMessage" Name="InstantSendMessage__string"><Properties><Property Name="MessageType" Value="_string" /></Properties><Ports><CompileTimePort Name="Exec" /><CompileTimePort Name="Receiver" /><RunTimePort Name="Content" /></Ports></Definition>
<Definition TypeName="Trace" Name="Trace"><Ports><CompileTimePort Name="Exec" /><CompileTimePort Name="Value" /></Ports></Definition>
<Definition TypeName="Timer" Name="Timer"><Ports><CompileTimePort Name="Duration" /><CompileTimePort Name="TimeType" /><RunTimePort Name="SetRunning" /><RunTimePort Name="OnFinished" /></Ports></Definition>
</Nodes></Root>'''


def package(root, travel=None, level=None):
    travel = {probe.PROJECT: PROJECT, probe.ENTRY: ENTRY} if travel is None else travel
    level = {probe.OBJECTS: OBJECTS, probe.WAITING: WAITING} if level is None else level
    for relative, members_ in ((probe.TRAVEL, travel), (probe.LEVEL_PAK, level)):
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, blob in members_.items():
                archive.writestr(name, blob)
    return Path(root)


def members(root, relative):
    with zipfile.ZipFile(Path(root) / relative) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def mutate(root, relative, name, change):
    from setup_package_upgrade import rewrite
    rewrite(Path(root), relative, {name: change(members(root, relative)[name])})


def shape(blob):
    return probe._shape(E.fromstring(blob))


class Emitted(unittest.TestCase):
    def test_lua_is_toolings_snippet_and_runs_once_per_start(self):
        self.assertEqual(probe.LUA, TOOLING_LUA)
        trees = {t.get('name'): t for t in E.fromstring(probe.trees()).iter('BehaviorTree')}
        sequence = trees[probe.NAME].find('Root/Behavior/Sequence')
        self.assertEqual([n.tag for n in sequence], ['ExecuteLua', 'Wait'])
        self.assertEqual(sequence[0].get('code'), TOOLING_LUA)
        self.assertEqual(sequence[1].get('duration'), "'-1'")
        self.assertIsNone(trees[probe.NAME].find('.//Loop'))
        brain = trees[probe.BRAIN_TREE].find('Root/Behavior/Sequence')
        self.assertEqual([n.tag for n in brain], ['ExecuteLua', 'Loop'])
        self.assertEqual(brain.find('Loop/ProcessMessage').get('inbox'), "'" + probe.MAILBOX_NAME + "'")
        self.assertEqual(brain.find('Loop/ProcessMessage/ExecuteLua').get('code'), probe.LUA_MESSAGE)

    def test_module_latches_off_then_on_and_traces(self):
        module = E.fromstring(probe.module()).find('Skald/Module')
        self.assertEqual(module.get('Name'), 'gm_trace_probe')
        nodes = {n.get('Name'): n for n in module.find('Nodes')}
        edges = lambda n: {(e.get('From'), e.get('To')) for e in nodes[n].findall('Edge')}
        self.assertEqual(edges('active'), {('arrive', 'SetTrue'), ('off.OnFinished', 'SetFalse'), ('on.OnFinished', 'SetTrue')})
        self.assertEqual(edges('enable'), {('host', 'SmartEntity'), ('active.State', 'IsActive')})
        self.assertEqual(nodes['enable'].find("Constant[@Name='Behavior']").get('Value'), 'gm_trace_probe')
        self.assertIsNone(nodes['enable'].find("*[@Name='NPC']"))
        self.assertEqual(nodes['off'].find("Constant[@Name='Duration']").get('Value'), '5s')
        self.assertEqual(edges('on'), {('off.OnFinished', 'SetRunning')})
        self.assertIn('GlueTraceProbe skald trace', nodes['trace'].find("Constant[@Name='Value']").get('Value'))
        self.assertEqual(edges('trace'), {('arrive', 'Exec')})
        self.assertEqual(edges('send'), {('arrive', 'Exec'), ('brain_host', 'Receiver'), ('message', 'Content')})

    def test_tables_join_template_brain_subbrain_and_tree(self):
        files = probe.emitted()
        row = lambda name: E.fromstring(files['Libs/Tables/ai/' + name + '__gm_trace_probe.xml'])[0][0].attrib
        templates = {t.get('Name'): t for p, b in files.items() if '/smartEntity/' in p
                     for t in E.fromstring(b).iter('SmartEntityTemplate')}
        plain, brained = templates[probe.NAME], templates[probe.BRAIN]
        self.assertIsNone(plain.get('BrainId'))
        behavior = plain.find('BehaviorTemplates/SmartBehaviorTemplate')
        self.assertEqual((behavior.get('Name'), behavior.get('InitialState')), (probe.NAME, 'Disabled'))
        self.assertEqual(behavior.find('TreeLocation').attrib, dict(FileName='gm_trace_probe.xml', TreeName=probe.NAME))
        self.assertEqual('AI/' + behavior.find('TreeLocation').get('FileName'), probe.TREES)
        self.assertEqual(brained.get('BrainId'), row('brain')['brain_id'])
        self.assertEqual(row('brain2subbrain')['brain_id'], row('brain')['brain_id'])
        self.assertEqual(row('brain2subbrain')['subbrain_id'], row('subbrain')['subbrain_id'])
        self.assertEqual(row('subbrain_smart_object'), dict(file_name='gm_trace_probe.xml', on_update_tree='onUpdate',
                                                            subbrain_id=row('subbrain')['subbrain_id']))
        self.assertEqual(row('brain2mailbox')['mailbox_id'], probe.MAILBOX_ID)
        self.assertEqual(len({plain.get('DatabaseId'), brained.get('DatabaseId')}), 2)

    def test_definition_contract(self):
        self.assertEqual(probe.verify_definitions(DEFINITIONS), [])
        self.assertTrue(probe.verify_definitions(DEFINITIONS.replace(b'Name="SmartEntity"', b'Name="Entity"')))
        self.assertTrue(probe.verify_definitions(DEFINITIONS.replace(b'Value="_string"', b'Value="_bool"')))
        self.assertTrue(probe.verify_definitions(DEFINITIONS.replace(b'TypeName="Trace"', b'TypeName="Tracer"')))


class Package(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = package(self.directory.name)

    def test_install_is_idempotent_and_audits_clean(self):
        self.assertEqual(probe.audit(self.root), ['trace probe is not installed (no ' + probe.MARKER + ')'])
        changed, report = probe.upgrade(self.root)
        self.assertEqual(set(changed), {probe.TRAVEL, probe.LEVEL_PAK})
        self.assertFalse(report['runtime_verified'])
        self.assertEqual(probe.audit(self.root), [])
        travel, level = members(self.root, probe.TRAVEL), members(self.root, probe.LEVEL_PAK)
        for path, blob in probe.emitted().items():
            self.assertEqual(travel[path], blob)
        entry = E.fromstring(travel[probe.ENTRY]).find('Skald/Level')
        instance = entry.find('Nodes/gm_trace_probe')
        self.assertEqual({(e.get('From'), e.get('To')) for e in instance.findall('Edge')},
                         {('OnWake', 'arrive'), ('OnLevelSwitched', 'arrive')})
        self.assertEqual({a.get('Name'): a.get('Alias') for a in instance.findall('Asset')},
                         dict(host='gm_trace_probe_host', brain_host='gm_trace_probe_brain_host'))
        objects = E.fromstring(level[probe.OBJECTS])
        hosts = {e.get('Name'): e for e in objects if e.get('Name') in probe.HOST_GUIDS}
        self.assertEqual(sorted(e.get('EntityId') for e in hosts.values()), ['42', '43'])
        self.assertEqual(hosts['gm_trace_probe_host'].get('EntityClass'), 'SmartObjectHolder')
        self.assertEqual(hosts['gm_trace_probe_host'].get('Pos'), '1,2,3')
        self.assertEqual(len(E.fromstring(level[probe.WAITING]).findall('WaitingLinks/WaitingLink')), 3)
        again, same = probe.upgrade(self.root)
        self.assertEqual(again, {})
        self.assertEqual(same, json.loads(travel[probe.MARKER]))
        self.assertEqual(members(self.root, probe.TRAVEL), travel)
        self.assertEqual(probe.main([str(self.root), '--check']), 0)

    def test_remove_restores_the_documents(self):
        probe.upgrade(self.root)
        self.assertEqual(set(probe.remove(self.root)), {probe.TRAVEL, probe.LEVEL_PAK})
        travel, level = members(self.root, probe.TRAVEL), members(self.root, probe.LEVEL_PAK)
        self.assertEqual(set(travel), {probe.PROJECT, probe.ENTRY})
        for blob, original in ((travel[probe.PROJECT], PROJECT), (travel[probe.ENTRY], ENTRY),
                               (level[probe.OBJECTS], OBJECTS), (level[probe.WAITING], WAITING)):
            self.assertEqual(shape(blob), shape(probe.xml(E.fromstring(original))))
        self.assertEqual(probe.remove(self.root), {})
        self.assertEqual(probe.main([str(self.root), '--check']), 1)
        probe.upgrade(self.root)
        self.assertEqual(probe.audit(self.root), [])

    def test_mutations_fail_the_check(self):
        cases = [
            (probe.TRAVEL, probe.TREES, lambda b: b.replace(b'g.n=g.n+1', b'g.n=g.n+2'), 'ExecuteLua bodies'),
            (probe.TRAVEL, probe.TREES, lambda b: b.replace(b'<Wait ', b'<Wait x="1" '), 'file missing or changed'),
            (probe.TRAVEL, probe.MODULE, lambda b: b.replace(b'5s', b'0s'), 'file missing or changed'),
            (probe.TRAVEL, probe.ENTRY, lambda b: b.replace(b'From="OnWake" To="arrive"', b'From="OnSleep" To="arrive"'), 'entry instance'),
            (probe.TRAVEL, probe.ENTRY, lambda b: b.replace(b'Alias="gm_trace_probe_host"', b'Alias="other"'), 'entry instance'),
            (probe.TRAVEL, probe.ENTRY, lambda b: b.replace(b'../gm_trace_probe/gm_trace_probe.xml', b'../x.xml'), 'does not declare'),
            (probe.TRAVEL, probe.PROJECT, lambda b: b.replace(b'<SmartObjectAsset Name="gm_trace_probe_host"', b'<SoulAsset Name="gm_trace_probe_host"'), 'project asset'),
            (probe.LEVEL_PAK, probe.OBJECTS, lambda b: b.replace(b'Name="gm_trace_probe_host"', b'Name="gm_trace_probe_hos"'), 'level host'),
            (probe.LEVEL_PAK, probe.OBJECTS, lambda b: b.replace(probe.TEMPLATE_ID.encode(), b'0'), 'level host'),
            (probe.LEVEL_PAK, probe.OBJECTS, lambda b: b.replace(b"asset['gm_trace_probe_brain_host']", b'x'), 'does not link'),
            (probe.LEVEL_PAK, probe.WAITING, lambda b: b.replace(b"asset['gm_trace_probe_host']", b'x'), 'link network'),
            (probe.TRAVEL, probe.MARKER, lambda b: b.replace(b'"version": 1', b'"version": 2'), 'unsupported probe version'),
        ]
        for relative, name, change, expected in cases:
            with self.subTest(expected=expected, name=name), tempfile.TemporaryDirectory() as directory:
                root = package(directory)
                probe.upgrade(root)
                before = members(root, relative)[name]
                mutate(root, relative, name, change)
                self.assertNotEqual(members(root, relative)[name], before)
                problems = probe.audit(root)
                self.assertTrue(any(expected in p for p in problems), problems)
                self.assertEqual(probe.main([str(root), '--check']), 1)
                with self.assertRaises(ValueError):
                    probe.upgrade(root)

    def test_refuses_collisions_and_skips_foreign_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = package(directory, travel={'Quests/other.xml': b'<x />'})
            self.assertEqual(probe.upgrade(root), ({}, {}))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(probe.upgrade(Path(directory)), ({}, {}))
        with tempfile.TemporaryDirectory() as directory:
            root = package(directory, travel={probe.PROJECT: PROJECT, probe.ENTRY: ENTRY, probe.TREES: b'<BehaviorTrees />'})
            with self.assertRaises(ValueError):
                probe.upgrade(root)
        with tempfile.TemporaryDirectory() as directory:
            root = package(directory, level={probe.OBJECTS: OBJECTS.replace(b'Name="other"', b'Name="gm_trace_probe_host"'),
                                             probe.WAITING: WAITING})
            with self.assertRaises(ValueError):
                probe.upgrade(root)
            self.assertEqual(set(members(root, probe.TRAVEL)), {probe.PROJECT, probe.ENTRY})

    def test_not_part_of_the_normal_finalize(self):
        tools = Path(probe.__file__).parent
        for name in ('setup_package_upgrade.py', 'build_recipe.py', 'setup_kcd1_quests.py', 'setup_campaign.py'):
            self.assertNotIn('setup_trace_probe', (tools / name).read_text(encoding='utf-8'), name)


if __name__ == '__main__':
    unittest.main()
