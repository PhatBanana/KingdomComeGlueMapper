"""Convert a source USM cinematic using a user-supplied RAD encoder.

Builds local assets only. The development override is deliberately separate from
the production campaign: it replaces an explicitly selected native movie entry.
"""
import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import RetailSourceReader
from cinematic_subtitles import convert as convert_subtitles



def chunks(blob):
    """Read bounded USM packets; payload offsets are relative to the first 8 bytes."""
    offset = 0
    while offset < len(blob):
        if len(blob) - offset < 32:
            raise ValueError('Truncated USM packet header')
        size = struct.unpack_from('>I', blob, offset + 4)[0]
        start = blob[offset + 9]
        padding = struct.unpack_from('>H', blob, offset + 10)[0]
        end = offset + 8 + size
        if size < 24 or end > len(blob) or start < 24 or start + padding > size:
            raise ValueError('Invalid USM packet bounds')
        yield (blob[offset:offset + 4], blob[offset + 12], blob[offset + 15],
               blob[offset + 8 + start:end - padding])
        offset = end


def demux(blob, output, audio_channel):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frames, audio_packets, cues = 0, 0, []
    with (output / 'source.m1v').open('wb') as video, (output / 'source.adx').open('wb') as audio:
        for tag, channel, kind, payload in chunks(blob):
            if kind != 0:
                continue
            if tag == b'@SFV':
                if channel != 0:
                    raise ValueError('Multiple video tracks are not supported')
                video.write(payload)
                frames += 1
            elif tag == b'@SFA' and channel == audio_channel:
                audio.write(payload)
                audio_packets += 1
            elif tag == b'@SBT':
                if len(payload) < 20:
                    raise ValueError('Truncated subtitle cue')
                language, scale, start, duration, length = struct.unpack_from('<5I', payload)
                if not scale or not duration or length > len(payload) - 20:
                    raise ValueError('Invalid subtitle cue')
                key = payload[20:20 + length].rstrip(b'\0').decode('utf-8')
                cues.append(dict(language=language, scale=scale, start=start,
                                 duration=duration, key=key))
    if not frames or not audio_packets:
        raise ValueError('Required video or selected audio track is missing')
    (output / 'source-subtitles.json').write_text(json.dumps(cues, indent=2), encoding='utf-8')
    return dict(video_packets=frames, audio_packets=audio_packets, subtitle_cues=len(cues))


def probe(path, count_frames=False):
    result = subprocess.run(['ffprobe', '-v', 'error', *(['-count_frames'] if count_frames else []),
                             '-show_streams', '-of', 'json', str(path)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)['streams']


def movie_override(native_xml, cutscene, root_path, filename):
    root = ET.fromstring(native_xml)
    matches = [e for e in root.findall('./Cutscenes/RenderedCutscene') if e.get('Name') == cutscene]
    if len(matches) != 1:
        raise ValueError('Expected one native cutscene entry: ' + cutscene)
    entry = matches[0]
    # KCD2's original subtitle/events/skip markers belong to a different movie.
    entry.clear()
    entry.attrib.update(Name=cutscene, Root=root_path)
    ET.SubElement(ET.SubElement(entry, 'Profiles'), 'Profile', Type='Default', FileName=filename)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def validate_bink(path, expected_video):
    streams = probe(path)
    video = next((s for s in streams if s['codec_type'] == 'video'), {})
    frames = int(expected_video['nb_frames'])
    rate = Fraction(expected_video['r_frame_rate'])
    if (video.get('codec_name') != 'binkvideo' or video.get('width') != expected_video['width']
            or video.get('height') != expected_video['height'] or Fraction(video.get('r_frame_rate', '0')) != rate
            or abs(float(video.get('duration', 0)) - float(frames / rate)) > 0.002
            or not any(s['codec_type'] == 'audio' for s in streams)):
        raise ValueError('Encoded cinematic does not match the source dimensions, timing and audio contract')
    return streams


def package_cinematic(encoded, native_xml, cutscene, root_path, output, cues=None, localization=None):
    """Stage a test override and optional localization additions, never install."""
    definition = movie_override(native_xml, cutscene, root_path, 'cinematic')
    srt = None
    if cues is not None:
        if localization is None:
            raise ValueError('Subtitle cues require a source localization archive')
        srt, strings, _ = convert_subtitles(cues, localization)
        tree = ET.fromstring(definition)
        for movie in tree.findall('./Cutscenes/RenderedCutscene'):
            if movie.get('Name') == cutscene:
                movie.set('Subtitles', 'cinematic')
        definition = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
        Path(output).with_suffix('.localization.xml').write_bytes(strings)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('Libs/Tables/ui/cutscene.xml', definition)
        archive.write(encoded, root_path + '/cinematic.bk2')
        if srt is not None:
            archive.writestr(root_path + '/cinematic.srt', srt)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kcd1', type=Path, required=True)
    p.add_argument('--source-archive', required=True, help='Source Data archive containing the USM')
    p.add_argument('--source-entry', required=True, help='Exact source movie entry; resolved against retail patches')
    p.add_argument('--language-id', required=True, help='Source video_language2audio_track language_id')
    p.add_argument('--target-audio-track-base', type=int, required=True, help='First Bink track ID expected by the target cinematic language routing')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--encoder', type=Path, help='Separately installed radvideo64.exe')
    p.add_argument('--native-cutscenes', type=Path, help='Native cutscene.xml, for a development-only test pak')
    p.add_argument('--replace-cutscene', help='Explicit native entry to replace in the isolated test package')
    p.add_argument('--subtitle-localization', type=Path, help='Source language XML archive for subtitle conversion; emits localization additions for merging')
    p.add_argument('--target-root', default='Videos/gluemapper/converted_cinematic')
    p.add_argument('--rad-avi-end-guard', action='store_true', help='Append one terminal AVI guard frame for RAD builds that omit the last AVI frame; output still must match the original frame count')
    args = p.parse_args()
    if args.output.exists():
        p.error('Choose a new output directory; existing conversions are not overwritten')
    if args.encoder and not args.encoder.is_file():
        p.error('Encoder executable is missing')
    if args.target_audio_track_base < 0:
        p.error('Target audio track IDs must be nonnegative')
    if bool(args.native_cutscenes) != bool(args.replace_cutscene):
        p.error('--native-cutscenes and --replace-cutscene must be supplied together')
    if any(s in args.target_root for s in ('..', ':', '\\')) or args.target_root.startswith('/'):
        p.error('Use a relative forward-slash target root')
    with RetailSourceReader(args.kcd1) as reader:
        source = reader(args.kcd1, {'movie': (args.source_archive, args.source_entry)})['movie']
        language = reader(args.kcd1, {'languages': ('Tables.pak', 'Libs/Tables/ui/video_language2audio_track.xml')})['languages']
    language_root = ET.fromstring(language['data'])
    selected = [row for row in language_root.iter() if row.get('language_id') == args.language_id]
    if len(selected) != 1:
        raise ValueError('Expected one source language audio mapping')
    channel = int(selected[0].attrib['audio_track_id'])
    counts = demux(source['data'], args.output, channel)
    receipt = dict(source=source['candidates'][-1], entry=source['entry'],
                   language_id=args.language_id, audio_channel=channel,
                   target_audio_track_base=args.target_audio_track_base, **counts,
                   encoded=False, installed=False, campaign_ready=False,
                   limitations=['Subtitle cues extracted but not installed',
                                'Media conversion does not initialize actors or campaign logic'])
    report = args.output / 'conversion.json'
    report.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if not args.encoder:
        print(f'Extracted original movie and audio: {report}', flush=True)
        return
    original = args.output / 'source.usm'
    original.write_bytes(source['data'])
    # Raw MPEG probing can report field rate (60) instead of the USM presentation
    # rate (30). Take presentation timing from the container, frame count from
    # decoding the elementary stream; packet counts are not frame counts.
    expected = next(s for s in probe(original) if s['codec_type'] == 'video')
    decoded = next(s for s in probe(args.output / 'source.m1v', count_frames=True) if s['codec_type'] == 'video')
    expected['nb_frames'] = decoded['nb_read_frames']
    source_frames = int(expected['nb_frames'])
    # Demuxed MPEG avoids the USM footer timestamp that duplicated a frame in
    # the first probe. Preserve source frame count and original six audio channels.
    intermediate = args.output / 'cinematic.avi'
    extra = ['-vf', 'tpad=stop_mode=clone:stop=1'] if args.rad_avi_end_guard else []
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(args.output / 'source.m1v'),
                    '-i', str(args.output / 'source.adx'), '-map', '0:v:0', '-map', '1:a:0',
                    *extra, '-r', expected['r_frame_rate'], '-fps_mode', 'passthrough', '-frames:v', str(source_frames + int(args.rad_avi_end_guard)),
                    '-c:v', 'mjpeg', '-q:v', '2', '-c:a', 'pcm_s16le', str(intermediate)], check=True)
    encoded = args.output / 'cinematic.bik'
    command = [str(args.encoder.resolve()), 'binkc', str(intermediate.resolve()),
               str(encoded.resolve()), '/V100', '/D3000000', '/O', '/U8', '/{0', '/:0', '/}0',
               '/E' + str(source_frames), '/T' + str(args.target_audio_track_base), '/#']
    print('Encoding complete source cinematic; waiting for RAD to finish.', flush=True)
    startup = None
    if hasattr(subprocess, 'STARTUPINFO'):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    subprocess.run(command, check=True, startupinfo=startup)
    receipt.update(encoded=True, streams=validate_bink(encoded, expected),
                   rad_avi_end_guard=args.rad_avi_end_guard,
                   encoder_sha256=hashlib.sha256(args.encoder.read_bytes()).hexdigest(),
                   encoder_arguments=command[1:], output_sha256=hashlib.sha256(encoded.read_bytes()).hexdigest())
    if args.native_cutscenes:
        pak = args.output / 'gluemapper_cinematic_dev_test.pak'
        cues = json.loads((args.output / 'source-subtitles.json').read_text(encoding='utf-8')) if args.subtitle_localization else None
        package_cinematic(encoded, args.native_cutscenes.read_bytes(), args.replace_cutscene,
                          args.target_root, pak, cues, args.subtitle_localization)
        receipt.update(development_package=str(pak),
                       scope='Explicit cutscene override for an isolated development test only')
    report.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(f'Conversion ready for runtime testing: {report}', flush=True)


if __name__ == '__main__':
    main()
