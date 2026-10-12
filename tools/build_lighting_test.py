"""Stage native interior lighting for an existing combined test mod."""
import argparse
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from lighting_cubemaps import pack_assets, standard_cube, TARGET_TIMES, stamp
from region_travel import guid
from upgrade_map import read
from world_lighting import build as convert
import world_voxels
from voxel_lighting import validate_pair


def audit(package):
    index={};archives=[]
    try:
        for path in sorted((package/'Data').glob('gluemapper_lighting_*.pak')):
            if path.stat().st_size>=1024**3:raise ValueError('Lighting shard too large')
            archive=zipfile.ZipFile(path);archives.append(archive)
            if archive.testzip() is not None:raise ValueError('Lighting CRC failure')
            for info in archive.infolist():
                if info.compress_type!=zipfile.ZIP_STORED:raise ValueError('Lighting must use stored entries')
                if info.filename in index:raise ValueError('Duplicate lighting asset')
                index[info.filename]=archive
        with zipfile.ZipFile(package/'Data/Levels/kcd1_travel/level.pak') as level:
            if level.testzip() is not None:raise ValueError('Level CRC failure')
            root=ET.fromstring(read(level,'objects_mission0.xml'))
            mission=ET.fromstring(read(level,'mission_mission0.xml'))
            gi=mission.find('Environment/Total_Illumination_v2')
            voxel_tiles=0
            if gi.get('Active')=='1':
                if gi.get('IntegrationMode')!='0' or gi.get('UseLightProbes')!='1':
                    raise ValueError('Opacity-only bake requires basic GI with probes')
                for path in sorted((package/'Data/Levels/kcd1_travel').glob('svo-part*.pak')):
                    with zipfile.ZipFile(path) as voxel_archive:
                        if voxel_archive.testzip() is not None:raise ValueError('Voxel CRC failure')
                        for name in voxel_archive.namelist():
                            if name.endswith('.idx'):
                                result=validate_pair(read(voxel_archive,name),read(voxel_archive,name[:-4]+'.vox'))
                                if result['channel_masks']!=[1]:raise ValueError('Unexpected converted voxel channels')
                                voxel_tiles+=1
                if voxel_tiles!=256:raise ValueError('Incomplete world voxel bake')
            nodes=[e for e in root.iter('Entity') if e.get('Name','').startswith('gm_lighting_')]
            ids={e.get('EntityId'):e for e in nodes};guids={e.get('EntityGuid') for e in nodes}
            if len(ids)!=len(nodes) or len(guids)!=len(nodes):raise ValueError('Duplicate lighting identity')
            referenced=set();enabled=0
            for e in nodes:
                for link in e.findall('EntityLinks/Link'):
                    if ids[link.get('TargetId')].get('EntityGuid')!=link.get('TargetGuid'):raise ValueError('Broken lighting link')
                if e.get('EntityClass')=='ClipVolume':
                    read(level,e.find('ClipVolume').get('GeometryFileName').replace('%level%/',''))
                if e.get('EntityClass')!='EnvironmentLight':continue
                props=e.find('Properties')
                options=props.find('Options')
                if options.get('bIgnoresVisAreas')!='0' or options.get('bAffectsThisAreaOnly')!='0':
                    raise ValueError('Probe retains a legacy visibility-area override: '+e.get('Name'))
                expected_clip='1' if e.findall('EntityLinks/Link') else '0'
                if options.get('bDeferredClipBounds')!=expected_clip:
                    raise ValueError('Probe clipping flag does not match its explicit dependencies: '+e.get('Name'))
                if props.get('bActive')!='1':continue
                enabled+=1;advanced=props.find('OptionsAdvanced')
                if advanced.get('bDynamic')=='1':
                    paths=['textures/cubemaps/kcd1_travel/'+e.get('Name')+'/'+stamp(t)+'_cm.dds' for t in TARGET_TIMES]
                else:paths=[advanced.get('texture_deferred_cubemap')]
                for name in paths:
                    referenced.add(name);referenced.add(name.removesuffix('_cm.dds')+'_cm_diff.dds')
            for name in referenced:
                base=read(index[name],name)
                if struct.unpack_from('<I',base,36)[0]!=0x200011:raise ValueError('Missing native probe texture flags')
                chunks=[];i=1
                while name+'.'+str(i) in index:
                    member=name+'.'+str(i);chunks.append(read(index[member],member));i+=1
                standard_cube(base,chunks)
                if struct.unpack_from('<II',base,12)!=(128,128):raise ValueError('Incorrect probe atlas size')
        return {'entities':len(nodes),'enabled_probes':enabled,'referenced_cubemaps':len(referenced),
                'packed_asset_entries':len(index),'shards':len(archives),'voxel_tiles':voxel_tiles,'crc_checked':True,'links_resolved':True}
    finally:
        for archive in archives:archive.close()


def build(source,target,mod,output,cache=None):
    if output.exists():raise FileExistsError('Choose a fresh lighting staging directory')
    output.mkdir(parents=True)
    path='Data/Levels/kcd1_travel/level.pak'
    baseline=digest(mod/path)
    with zipfile.ZipFile(mod/path) as archive:
        files={name:read(archive,name) for name in ('objects_mission0.xml','mission_mission0.xml')}
    files,assets,report=convert(files,source,target,'kcd1_travel',guid,cache or output/'conversion')
    package=output/'package'
    report['voxels']=world_voxels.build(source,package/'Data/Levels/kcd1_travel')
    files['mission_mission0.xml']=world_voxels.configure_environment(files['mission_mission0.xml'])
    report['indirect_lighting']='Native basic GI with converted KCD1 opacity voxels and environment probes'
    rewrite(mod/path,package/path,files)
    pack_assets(package/'Data',assets)
    report['package_audit']=audit(package)
    report.update(source_mod=str(mod),baseline={path:baseline},
                  files={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()})
    (output/'lighting-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--cache',type=Path,help='Reuse a previous lighting conversion cache')
    build(**vars(parser.parse_args()))
