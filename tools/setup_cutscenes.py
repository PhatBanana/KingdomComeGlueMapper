"""Optional, real KCD1 opening conversion in the private setup package."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import RetailSourceReader
from cinematic_media import demux, probe, validate_bink, package_cinematic
from region_travel_dialogue import merge_localization
from setup_campaign import RECEIPT, digest, verify_package
from upgrade_map import read

SOURCE_ARCHIVE = 'ipl_videosb.pak'
SOURCE_ENTRY = 'Videos/q_skalitz/cin_7805_stribrna_skalice.usm'
TARGET_ROOT = 'Videos/gluemapper/opening'


def check_tools(encoder):
    path=Path(encoder)
    if path.name.lower() not in ('radvideo64.exe','radvideo32.exe','radvideo.exe') or not path.is_file():
        raise ValueError('Select the installed RAD Video Tools executable for opening-movie conversion.')
    with path.open('rb') as f:
        if f.read(2)!=b'MZ':raise ValueError('RAD converter is not a Windows executable.')
    for name in ('ffmpeg','ffprobe'):
        if not shutil.which(name):raise ValueError(f'Opening-movie conversion requires {name} on PATH. Install FFmpeg, then restart setup.')
    return path.resolve()


def run(command, log, notify, cancelled, label):
    """Drain output to disk; cancellation terminates only this worker's child."""
    if cancelled():raise InterruptedError('Cutscene conversion cancelled.')
    with Path(log).open('wb') as stream:
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        start=time.monotonic();last=0
        while process.poll() is None:
            if cancelled():
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                else:process.terminate()
                process.wait()
                raise InterruptedError('Cutscene conversion cancelled; partial files retained in the build folder.')
            elapsed=int(time.monotonic()-start)
            if elapsed-last>=5:
                notify(label,0,0,f'{elapsed}s elapsed. Encoder duration varies; no reliable ETA yet.')
                last=elapsed
            time.sleep(.2)
    if process.returncode:
        raise ValueError(f'{label} failed (exit {process.returncode}). See {log}')


def install_media(package, encoded, native_xml, cues, localization, work):
    """Merge subtitles and receipt; never modify shared hard-linked files."""
    package,work=Path(package),Path(work)
    receipt=verify_package(package,hashes=False)
    staged=work/'gluemapper_opening.pak'
    package_cinematic(encoded,native_xml,'intro_new_game',TARGET_ROOT,staged,cues,localization)
    additions=staged.with_suffix('.localization.xml').read_bytes()
    language=package/'Localization/English_xml.pak'
    with zipfile.ZipFile(language) as z:entries=[(i,read(z,i.filename)) for i in z.infolist()]
    key=next((i.filename for i,b in entries if i.filename.lower()=='text_ui_dialog.xml'),None)
    if key is None:raise ValueError('Map package is missing English dialogue localization.')
    pending=work/'English_xml.pak'
    with zipfile.ZipFile(pending,'x',zipfile.ZIP_STORED) as z:
        for i,b in entries:z.writestr(i,merge_localization(b,additions) if i.filename==key else b)
    dest=package/'Data/gluemapper_opening.pak'
    # Same-volume private build replacements preserve linked source packages.
    shutil.copy2(staged,dest.with_suffix('.pending'))
    dest.with_suffix('.pending').replace(dest)
    shutil.copy2(pending,language.with_suffix('.pending'))
    language.with_suffix('.pending').replace(language)
    for p in (dest,language):receipt['files'][p.relative_to(package).as_posix()]=digest(p)
    receipt['opening_movie']=dict(source=SOURCE_ENTRY,cutscene='intro_new_game',language='English',
        replaces_shared_new_game_intro=True,runtime_verified=False)
    pending_receipt=package/(RECEIPT+'.pending')
    pending_receipt.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    pending_receipt.replace(package/RECEIPT)


def build(package, source, target, encoder, work, notify, cancelled):
    encoder=check_tools(encoder);source,target,work=map(Path,(source,target,work))
    work.mkdir(parents=True,exist_ok=False)
    notify('Extract KCD1 opening',0,5,SOURCE_ENTRY)
    if cancelled():raise InterruptedError('Cancelled before movie extraction.')
    with RetailSourceReader(source) as reader:
        movie=reader(source,{'movie':(SOURCE_ARCHIVE,SOURCE_ENTRY)})['movie']
        mapping=reader(source,{'mapping':('Tables.pak','Libs/Tables/ui/video_language2audio_track.xml')})['mapping']['data']
    rows=[r for r in ET.fromstring(mapping).iter() if r.get('language_id')=='1']
    if len(rows)!=1:raise ValueError('Missing source English movie audio mapping.')
    demux(movie['data'],work,int(rows[0].get('audio_track_id')))
    original=work/'source.usm';original.write_bytes(movie['data'])
    expected=next(s for s in probe(original) if s['codec_type']=='video')
    decoded=next(s for s in probe(work/'source.m1v',count_frames=True) if s['codec_type']=='video')
    expected['nb_frames']=decoded['nb_read_frames'];frames=int(expected['nb_frames'])
    notify('Prepare movie for RAD',1,5,f'{expected["width"]} × {expected["height"]}; {frames} frames; source frame rate preserved.')
    avi=work/'cinematic.avi';encoded=work/'cinematic.bik'
    run([shutil.which('ffmpeg'),'-v','error','-y','-r',expected['r_frame_rate'],'-i',str(work/'source.m1v'),'-i',str(work/'source.adx'),
        '-map','0:v:0','-map','1:a:0','-vf','tpad=stop_mode=clone:stop=1','-r',expected['r_frame_rate'],
        '-fps_mode','cfr','-frames:v',str(frames+1),'-c:v','mjpeg','-q:v','2','-c:a','pcm_s16le',str(avi)],
        work/'ffmpeg.log',notify,cancelled,'Prepare movie for RAD')
    notify('Encode KCD1 opening',2,5,'Encoding with the selected RAD Video Tools installation.')
    # English KCD2 routing uses six tracks starting at 10. The terminal guard
    # compensates for the validated RAD AVI endpoint; output must match exactly.
    run([str(encoder),'binkc',str(avi.resolve()),str(encoded.resolve()),'/V100','/D3000000','/O','/U8',
         '/{0','/:0','/}0','/E'+str(frames),'/T10','/#'],work/'rad.log',notify,cancelled,'Encode KCD1 opening')
    notify('Validate converted opening',3,5,'Checking dimensions, frame rate, duration and audio.')
    streams=validate_bink(encoded,expected)
    cues=json.loads((work/'source-subtitles.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:native_xml=read(z,'Libs/Tables/ui/cutscene.xml')
    if cancelled():raise InterruptedError('Cancelled before packaging converted opening.')
    notify('Package opening and subtitles',4,5,'Adding movie and merging English subtitles into the map package.')
    install_media(package,encoded,native_xml,cues,source/'Localization/English_xml.pak',work)
    report=dict(source=movie['candidates'],streams=streams,encoded_sha256=digest(encoded),
                encoder_sha256=digest(encoder),packaged=True,runtime_verified=False)
    (work/'conversion.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    notify('KCD1 opening packaged',5,5,'Movie and English subtitles will be installed with KCD1 Map.')
    return report
