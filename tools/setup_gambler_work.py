"""Install source-selected gambler ownership and its authored money decision."""
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from upgrade_map import read, digest


def upgrade(package, source, target):
    if source is None or target is None:raise ValueError('Both games are required for source dice work')
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from profile_population_upgrade import discover
    from setup_gameplay import STATIC_WORLD_PROFILES, LEVEL
    from setup_package_upgrade import rewrite
    from character_gambler_work import extend_people
    from campaign_combat_work import validate
    package,source,target=map(Path,(package,source,target))
    lp='Data/Levels/'+LEVEL+'/level.pak'
    if not (package/lp).exists():return {},dict(status='not_applicable')
    with zipfile.ZipFile(package/lp) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml','tables/ai/scheduler.xml','waitinglinks.xml')}
    with RetailSourceReader(source) as reader:
        tables=SourceTables(source,reader)
        _,people,_=discover(source,'rataje',STATIC_WORLD_PROFILES,tables)
        with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
            updated,definitions,reports=extend_people(files,people,tables,z,source,target)
    if not reports:return {},dict(status='not_applicable')
    from gambler_dialogue_registration import prepare as prepare_dialogue
    updated,dialogue_definitions,dialogue_report=prepare_dialogue(package,target,updated)
    definitions.update(dialogue_definitions)
    from gambler_schedule_activation import prepare
    updated,definitions=prepare(package,target,updated,reports,definitions)
    validate(definitions,target)
    modid=E.parse(package/'mod.manifest').findtext('info/modid')
    if not modid:raise ValueError('Package has no mounted scheduler identity')
    definitions['Mods/'+modid+'/Data/Levels/'+LEVEL+'/tables/ai/scheduler.xml']=updated['tables/ai/scheduler.xml']
    travel='Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/travel) as z:
        definitions={k:v for k,v in definitions.items() if k not in z.namelist() or read(z,k)!=v}
    replacements={k:v for k,v in updated.items() if v!=files[k]}
    changes={}
    if replacements:rewrite(package,lp,replacements);changes[lp]=digest(package/lp)
    if definitions:rewrite(package,travel,definitions);changes[travel]=digest(package/travel)
    return changes,dict(status='upgraded' if changes else 'present',jobs=reports,dialogue=dialogue_report,runtime_verified=False)
