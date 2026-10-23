"""Apply the source-selected pub cleaning adapter to a saved package."""
from pathlib import Path
import zipfile
from upgrade_map import read, digest


def upgrade(package, source, target):
    if source is None or target is None:
        raise ValueError('Both games are required to validate source pub work')
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from profile_population_upgrade import discover
    from setup_gameplay import STATIC_WORLD_PROFILES, LEVEL
    from setup_package_upgrade import rewrite
    from character_pub_cleaning import extend_people, resources
    package, source, target = map(Path, (package, source, target))
    lp = 'Data/Levels/'+LEVEL+'/level.pak'
    if not (package/lp).exists(): return {}, dict(status='not_applicable')
    with zipfile.ZipFile(package/lp) as z:
        files = {n: read(z, n) for n in ('objects_mission0.xml', 'tables/ai/scheduler.xml', 'waitinglinks.xml')}
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        _, people, _ = discover(source, 'rataje', STATIC_WORLD_PROFILES, tables)
        with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
            updated, reports = extend_people(files, people, tables, z, target, source, reader)
    if not reports: return {}, dict(status='not_applicable')
    replacements = {k:v for k,v in updated.items() if v != files[k]}
    changes = {}
    if replacements:
        rewrite(package, lp, replacements); changes[lp] = digest(package/lp)
    if any(r['job'] in ('source_pub_table_cleaning', 'source_pub_rest') for r in reports):
        import xml.etree.ElementTree as E
        modid = E.parse(package/'mod.manifest').findtext('info/modid')
        definitions = resources(target) if any(r['job'] == 'source_pub_table_cleaning' for r in reports) else {}
        from campaign_combat_work import validate
        validate(definitions, target)
        definitions['Mods/'+modid+'/Data/Levels/'+LEVEL+'/tables/ai/scheduler.xml'] = updated['tables/ai/scheduler.xml']
        travel = 'Data/gluemappertravel.pak'
        with zipfile.ZipFile(package/travel) as z:
            definitions = {k:v for k,v in definitions.items() if k not in z.namelist() or read(z,k) != v}
        if definitions:
            rewrite(package, travel, definitions); changes[travel] = digest(package/travel)
    return changes, dict(status='upgraded' if changes else 'present', jobs=reports, runtime_verified=False)
