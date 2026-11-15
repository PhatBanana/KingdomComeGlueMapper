from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_quest_people_test import write_actor_paks, pack_shared_textures, shared_texture_stage
from character_shared_textures import PREFIX, Store, family_name, pack, packaged, references, rewrite
from texture_streaming import split_generated, validate_family
from test_texture_streaming import texture


def baked(seed):
    """A complete 512x512 float texture; seed changes its full-resolution pixels."""
    blob = bytearray(texture(512, 512, 10))
    blob[148 + seed] ^= 0xff
    return bytes(blob)


def folder(namespace):
    return 'objects/characters/gluetravel/' + namespace + '/'


def material(*files):
    return ('<Material Name="m"><Textures>' + ''.join('<Texture Map="Diffuse" File="%s" />' % f for f in files)
            + '</Textures><PublicParams Gloss="0.5" /></Material>').encode()


def person(root, namespace, textures, extra=None):
    """Stage an appearance whose one material names every texture: {leaf: bytes}."""
    appearance = root / 'people' / namespace
    files = {folder(namespace) + leaf: blob for leaf, blob in textures.items()}
    files[folder(namespace) + 'body.mtl'] = material(*(folder(namespace) + leaf for leaf in textures))
    files[folder(namespace) + 'body.skin'] = b'skin ' + namespace.encode()
    files.update(extra or {})
    for name, blob in files.items():
        path = appearance / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    return appearance


def members(paks):
    entries = {}
    for pak in paks:
        with zipfile.ZipFile(pak) as archive:
            assert archive.testzip() is None
            for name in archive.namelist():
                assert name not in entries, name
                entries[name] = archive.read(name)
    return entries


def resolved(entries, namespace):
    """Texture families each material reference of a person resolves to: {(material, index): {suffix: bytes}}."""
    result = {}
    for name, blob in entries.items():
        if name.startswith(folder(namespace)) and name.endswith('.mtl'):
            for index, path in enumerate(references(blob, name)):
                family = {k[len(path):]: v for k, v in entries.items() if k == path or k.startswith(path + '.')}
                validate_family(family[''], {k: v for k, v in family.items() if k})
                result[name, index] = family
    return result


class SharedTextureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'Data'; self.data.mkdir()
        environment = patch.dict(os.environ, {}, clear=True)  # no native compiler: the built-in splitter
        environment.start(); self.addCleanup(environment.stop)

    def build(self, people, data=None, stage=None):
        """Pack {namespace: textures} the way a build does; return every archive's members."""
        data = data or self.data
        store = Store(shared_texture_stage(stage or self.root))
        paks = []
        for namespace, textures in people.items():
            paks += write_actor_paks(person(stage or self.root, namespace, textures), data, namespace, textures=store)[0]
        return paks, pack_shared_textures(stage or self.root, data)

    def test_name_follows_content_and_kind_not_the_owner(self):
        family = split_generated(baked(1))
        name = family_name(folder('gm_person_a') + 'native_outfit_arms_0_diff.dds', family)
        self.assertEqual(name, family_name(folder('gm_person_b') + 'Native_Outfit_Torso_3_DIFF.dds', family))
        self.assertRegex(name, r'^[0-9a-f]{32}_diff$')
        self.assertNotEqual(name, family_name('x/a_spec.dds', family))
        self.assertNotEqual(name, family_name('x/a_diff.dds', split_generated(baked(2))))
        self.assertNotEqual(name, family_name('x/a_diff.dds', {k: v for k, v in family.items() if k != '.1'}))
        self.assertTrue(family_name('x/plain.dds', family).endswith('_tex'))

    def test_material_rewrite_changes_only_mapped_texture_paths(self):
        blob = ('<Material><Textures>\n<Texture Map="Diffuse" File="Objects\\A\\one_diff.dds" />'
                "<Texture File='./two_ddna.dds' Map='Bumpmap'/><Texture Map=\"Spec\" File=\"objects/a/kept_spec.dds\"/>"
                '</Textures><PublicParams File="objects/a/one_diff.dds" />\xc3\xa9</Material>').encode('latin-1')
        self.assertEqual(references(blob, 'Objects/A/m.mtl'),
                         ['objects/a/one_diff.dds', 'objects/a/two_ddna.dds', 'objects/a/kept_spec.dds'])
        changed = rewrite(blob, 'Objects/A/m.mtl', {'objects/a/one_diff.dds': PREFIX + 'h_diff.dds',
                                                    'objects/a/two_ddna.dds': PREFIX + 'h_ddna.dds'})
        expected = (blob.replace(b'File="Objects\\A\\one_diff.dds" />', b'File="' + PREFIX.encode() + b'h_diff.dds" />')
                    .replace(b"'./two_ddna.dds'", b"'" + PREFIX.encode() + b"h_ddna.dds'"))
        self.assertEqual(changed, expected)
        self.assertEqual(rewrite(blob, 'Objects/A/m.mtl', {}), blob)

    def test_people_in_the_same_clothes_store_the_texture_once(self):
        shared, own = baked(1), baked(2)
        before = {}
        for namespace, textures in (('gm_person_a', {'native_outfit_arms_0_diff.dds': shared, 'native_part0_0_bgs.dds': own}),
                                    ('gm_person_b', {'native_outfit_torso_3_diff.dds': shared})):
            plain = self.root / 'plain' / namespace; plain.mkdir(parents=True)
            before[namespace] = resolved(members(write_actor_paks(
                person(self.root / 'plain-stage', namespace, textures), plain, namespace)[0]), namespace)
        people, shards = self.build({'gm_person_a': {'native_outfit_arms_0_diff.dds': shared, 'native_part0_0_bgs.dds': own},
                                     'gm_person_b': {'native_outfit_torso_3_diff.dds': shared}})
        entries = members(people + shards)
        self.assertEqual(sorted(p.name for p in people), ['gm_person_a.pak', 'gm_person_b.pak'])
        for pak in people:
            with zipfile.ZipFile(pak) as archive:
                self.assertEqual(sorted(n.rsplit('/', 1)[1] for n in archive.namelist()), ['body.mtl', 'body.skin'])
        self.assertEqual(len(shards), 1)
        self.assertEqual(len(packaged(self.data)), 2)  # the shared family and a's own
        self.assertTrue(all(n.startswith(PREFIX) for n in members(shards)))
        self.assertFalse(shared_texture_stage(self.root).exists())
        # Every material reference resolves to the same family bytes as the per-person layout.
        for namespace in before:
            after = resolved(entries, namespace)
            self.assertEqual(after, before[namespace])
            self.assertTrue(after)
        self.assertEqual(references(entries[folder('gm_person_a') + 'body.mtl'], 'm')[0],
                         references(entries[folder('gm_person_b') + 'body.mtl'], 'm')[0])
        self.assertEqual(entries[folder('gm_person_b') + 'body.skin'], b'skin gm_person_b')

    def test_unreferenced_and_foreign_textures_stay_where_they_were(self):
        loose = split_generated(baked(3))
        extra = {folder('gm_person_a') + 'loose_diff.dds' + k: v for k, v in loose.items()}
        extra['objects/gluecampaign/gm_person_a_weapons/sword_diff.dds'] = baked(4)
        extra['objects/gluecampaign/gm_person_a_weapons/sword.mtl'] = material(
            'objects/gluecampaign/gm_person_a_weapons/sword_diff.dds', 'objects/characters/humans/native_diff.dds')
        appearance = person(self.root, 'gm_person_a', {'worn_diff.dds': baked(1)}, extra)
        store = Store(shared_texture_stage(self.root))
        paks, _ = write_actor_paks(appearance, self.data, 'gm_person_a', textures=store)
        entries = members(paks)
        self.assertEqual(len(store.names()), 1)
        for name, blob in extra.items():
            if not name.endswith('sword_diff.dds'): self.assertEqual(entries[name], blob)
        self.assertIn('objects/gluecampaign/gm_person_a_weapons/sword_diff.dds.1', entries)
        self.assertNotIn(folder('gm_person_a') + 'worn_diff.dds', entries)

    def test_a_broken_family_is_refused_and_never_staged(self):
        family = split_generated(baked(1)); del family['.1']
        appearance = person(self.root, 'gm_person_a', {}, {
            **{folder('gm_person_a') + 'worn_diff.dds' + k: v for k, v in family.items()},
            folder('gm_person_a') + 'body.mtl': material(folder('gm_person_a') + 'worn_diff.dds')})
        store = Store(shared_texture_stage(self.root))
        with self.assertRaisesRegex(ValueError, 'Missing texture mip'):
            write_actor_paks(appearance, self.data, 'gm_person_a', textures=store)
        self.assertEqual(store.names(), [])
        self.assertEqual(list(self.data.glob('*.pak')), [])

    def test_same_people_always_make_the_same_archives(self):
        cast = {'gm_person_a': {'a_diff.dds': baked(1), 'b_spec.dds': baked(2)}, 'gm_person_b': {'c_diff.dds': baked(1)}}
        first = self.build(cast)
        other = self.root / 'again'; (other / 'Data').mkdir(parents=True)
        second = self.build(dict(reversed(cast.items())), other / 'Data', other)
        self.assertEqual({p.name: p.read_bytes() for p in first[0] + first[1]},
                         {p.name: p.read_bytes() for p in second[0] + second[1]})

    def test_later_people_reuse_archives_and_never_rewrite_them(self):
        _, shards = self.build({'gm_person_a': {'a_diff.dds': baked(1), 'b_spec.dds': baked(2)}})
        kept = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in shards}
        later = self.root / 'later'; (later / 'Data').mkdir(parents=True)
        # A later stage built against the installed mod: only the new family is written.
        store = Store(shared_texture_stage(later))
        people, _ = write_actor_paks(person(later, 'gm_person_b', {'x_diff.dds': baked(1), 'y_diff.dds': baked(5)}),
                                     later / 'Data', 'gm_person_b', textures=store)
        added = pack_shared_textures(later, later / 'Data', existing=(self.data,))
        self.assertEqual(len(added), 1)
        self.assertEqual(len(packaged(later / 'Data')), 1)
        self.assertNotIn(added[0].name, {p.name for p in shards})
        for path in added: path.replace(self.data / path.name)  # the overlay
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in shards}, kept)
        self.assertTrue(resolved(members(people + sorted(self.data.glob('*.pak'))), 'gm_person_b'))
        # The same people again, into the package itself: nothing left to write.
        store = Store(self.root / 'resume')
        write_actor_paks(person(self.root / 'resume-stage', 'gm_person_b', {'x_diff.dds': baked(1), 'y_diff.dds': baked(5)}),
                         later, 'gm_person_c', textures=store)
        self.assertEqual(pack(store, self.data), [])
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in shards}, kept)

    def test_archives_respect_the_shard_limit_with_whole_families(self):
        store = Store(self.root / 'store')
        families = {}
        for seed in range(4):
            family = split_generated(baked(seed))
            families[family_name('x_diff.dds', family)] = family
            store.put(family_name('x_diff.dds', family), family)
        size = sum(map(len, next(iter(families.values())).values()))
        paks = pack(store, self.data, limit=2 * size + 4096)
        self.assertEqual(len(paks), 2)
        seen = set()
        for pak in paks:
            self.assertLessEqual(pak.stat().st_size, 2 * size + 4096)
            with zipfile.ZipFile(pak) as archive:
                self.assertTrue(all(i.header_offset < 2**32 and i.extra == b'' for i in archive.infolist()))
            entries = members([pak])
            names = {n[len(PREFIX):].split('.dds')[0] for n in entries}
            self.assertFalse(names & seen); seen |= names
            for name in names:  # every family is complete inside its one archive
                self.assertEqual({k[len(PREFIX + name + '.dds'):]: v for k, v in entries.items()
                                  if k.startswith(PREFIX + name + '.dds')}, families[name])
        self.assertEqual(seen, set(families))
        self.assertEqual(list(self.data.glob('*.partial')), [])
        with self.assertRaisesRegex(ValueError, 'shard limit'):
            pack(store, self.root, limit=size // 2)

    def test_racing_workers_stage_one_complete_family(self):
        family = split_generated(baked(1))
        name = family_name('x_diff.dds', family)
        stores = [Store(self.root / 'store') for _ in range(16)]
        with ThreadPoolExecutor(16) as pool:
            wrote = list(pool.map(lambda store: store.put(name, family), stores))
        self.assertGreaterEqual(wrote.count(True), 1)
        self.assertEqual([p.name for p in (self.root / 'store').iterdir()], [name])
        self.assertEqual({p.name[len(name) + 4:]: p.read_bytes() for p in (self.root / 'store' / name).iterdir()}, family)
        self.assertTrue(all(store.used == {name} for store in stores))
        stamp = {p: p.stat().st_mtime_ns for p in (self.root / 'store' / name).iterdir()}
        self.assertFalse(Store(self.root / 'store').put(name, family))
        self.assertEqual({p: p.stat().st_mtime_ns for p in (self.root / 'store' / name).iterdir()}, stamp)

    def test_unfinished_staging_is_never_packed(self):
        store = Store(self.root / 'store')
        family = split_generated(baked(1))
        store.put(family_name('x_diff.dds', family), family)
        abandoned = store.folder / '.0123_diff.deadbeef'; abandoned.mkdir()
        (abandoned / '0123_diff.dds').write_bytes(b'half')
        self.assertEqual(store.names(), [family_name('x_diff.dds', family)])
        self.assertEqual(len(members(pack(store, self.data))), len(family))

    def test_cached_character_restores_its_families(self):
        store = Store(self.root / 'first')
        write_actor_paks(person(self.root, 'gm_person_a', {'a_diff.dds': baked(1), 'b_spec.dds': baked(2)}),
                         self.data, 'gm_person_a', textures=store)
        payload = self.root / 'payload'
        for relative, source in store.files().items():
            (payload / relative).parent.mkdir(parents=True, exist_ok=True)
            (payload / relative).write_bytes(source.read_bytes())
        fresh = Store(self.root / 'second')
        other = split_generated(baked(1))
        fresh.put(family_name('a_diff.dds', other), other)  # another worker staged this one already
        fresh.adopt(payload)
        self.assertEqual(fresh.names(), store.names())
        self.assertEqual({k: p.read_bytes() for k, p in fresh.files().items()},
                         {k: p.read_bytes() for k, p in store.files().items()})

    def test_without_a_store_the_person_keeps_its_own_textures(self):
        appearance = person(self.root, 'gm_person_a', {'a_diff.dds': baked(1)})
        entries = members(write_actor_paks(appearance, self.data, 'gm_person_a')[0])
        self.assertIn(folder('gm_person_a') + 'a_diff.dds.1', entries)
        self.assertEqual(entries[folder('gm_person_a') + 'body.mtl'], material(folder('gm_person_a') + 'a_diff.dds'))


if __name__ == '__main__':
    unittest.main()
