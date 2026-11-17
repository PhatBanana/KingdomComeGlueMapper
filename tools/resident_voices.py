"""Give imported town residents their KCD1 voice, as the keepers have.

The actor stage gives a resident the native character world_actor_contracts
picks. Where that voice differs from the resident's KCD1 voice, the character
row is copied as gm_voice_<person> with only voice_id changed (the keepers'
kcd1_shop_install.switch_voices), so barks and ambient lines play in KCD1's
voice. A KCD1 voice that is not exactly one KCD2 or imported voice keeps the
native voice and is reported as residue.
"""
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from upgrade_map import read, xml

TRAVEL = 'Data/gluemappertravel.pak'
MARKER = 'Libs/GlueMapper/resident_population.json'
RESIDENT_TABLE = 'Libs/Tables/skald/skald_character__gm_kcd1_residents.xml'


def plan(package, source, target):
    """(travel replacements, report) without writing."""
    import kcd1_shop_install as shop
    package = Path(package)
    with zipfile.ZipFile(package/TRAVEL) as travel:
        names = set(travel.namelist())
        if MARKER not in names:
            return {}, dict(switched=[], kept=[], residue=[])
        people = [r['person'] for r in json.loads(read(travel, MARKER)).get('residents', [])]
        soul_tables = {n: ET.fromstring(read(travel, n)) for n in names if n.startswith('Libs/Tables/rpg/soul__')}
        table_blob = read(travel, RESIDENT_TABLE) if RESIDENT_TABLE in names else None
        pinned, _ = shop.pin_characters(soul_tables, target, people)
        read_souls = lambda n: xml(soul_tables[n]) if n in pinned else read(travel, n)
        voice_rows, characters, _ = shop.voice_tables(names, read_souls, target)
        current, residue = {}, []
        for person in people:
            try:
                current.update(shop.keeper_voices(names, read_souls, target, [person])[0])
            except ValueError as error:
                residue.append(dict(person=person, reason=str(error)))
    available = {}
    for voice_id, (abbreviation, _) in voice_rows.items():
        available.setdefault(abbreviation, []).append(voice_id)
    wanted = {}
    for person in current:
        try:
            abbreviation = shop.source_voices(source, [person])[person]
        except ValueError as error:
            residue.append(dict(person=person, reason=str(error)))
            continue
        if len(available.get(abbreviation, [])) != 1:
            residue.append(dict(person=person, reason=f'KCD1 voice {abbreviation} is not a single KCD2 or imported voice'))
            continue
        wanted[person] = abbreviation
    switches = {p: a for p, a in wanted.items() if current[p] != a}
    changes, report = shop.switch_voices(soul_tables, table_blob, voice_rows, characters, switches)
    if shop.CHARACTER_TABLE in changes:
        changes[RESIDENT_TABLE] = changes.pop(shop.CHARACTER_TABLE)
    for path in pinned:
        changes.setdefault(path, xml(soul_tables[path]))
    return changes, dict(switched=report, kept=sorted(p for p in wanted if p not in switches),
                         residue=sorted(residue, key=lambda r: r['person']))


def upgrade(package, source, target):
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    if source is None or target is None:
        return {}, None
    changes, report = plan(package, source, target)
    if not changes:
        return {}, report
    rewrite(Path(package), TRAVEL, changes)
    return {TRAVEL: digest(Path(package)/TRAVEL)}, report
