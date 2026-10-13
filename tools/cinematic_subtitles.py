"""Translate extracted USM cue timing and localization into native SRT keys."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read


def timestamp(value):
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, millis = divmod(value, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def convert(cues, localization_archive):
    keys = {c['key'].lstrip('@') for c in cues}
    strings, provenance = {}, {}
    with zipfile.ZipFile(localization_archive) as archive:
        for path in archive.namelist():
            if not path.lower().endswith('.xml'):
                continue
            blob = read(archive, path)
            if not any(key.encode() in blob for key in keys):
                continue
            for row in ET.fromstring(blob).iter('Row'):
                cells = [c.text or '' for c in row.findall('Cell')]
                if not cells or cells[0] not in keys:
                    continue
                if len(cells) != 3:
                    raise ValueError('Unexpected source subtitle localization row')
                if cells[0] in strings and cells != strings[cells[0]]:
                    raise ValueError('Conflicting source subtitle localization')
                strings[cells[0]] = cells
                provenance[cells[0]] = path
    if keys - strings.keys():
        raise ValueError('Missing localized subtitles: ' + ', '.join(sorted(keys - strings.keys())))
    table, srt = ET.Element('Table'), []
    mapping = {}
    for key in sorted(keys):
        target = 'gm_cin_' + hashlib.sha256(key.encode()).hexdigest()[:24]
        mapping[key] = target
        row = ET.SubElement(table, 'Row')
        for value in [target, *strings[key][1:]]:
            ET.SubElement(row, 'Cell').text = value
    for i, cue in enumerate(cues, 1):
        if cue['scale'] <= 0 or cue['duration'] <= 0 or cue['start'] < 0:
            raise ValueError('Invalid subtitle timing')
        start = round(cue['start'] * 1000 / cue['scale'])
        end = round((cue['start'] + cue['duration']) * 1000 / cue['scale'])
        srt.append(f"{i}\n{timestamp(start)} --> {timestamp(end)}\n{mapping[cue['key'].lstrip('@')]}\n")
    return ('\n'.join(srt) + '\n').encode('utf-8'), ET.tostring(table, encoding='utf-8', xml_declaration=True), provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cues', type=Path, required=True)
    parser.add_argument('--localization', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output directory')
    cues = json.loads(args.cues.read_text(encoding='utf-8'))
    srt, strings, provenance = convert(cues, args.localization)
    args.output.mkdir(parents=True)
    (args.output / 'cinematic.srt').write_bytes(srt)
    (args.output / 'text_ui_dialog.xml').write_bytes(strings)
    (args.output / 'conversion.json').write_text(json.dumps(dict(cues=len(cues), sources=provenance), indent=2), encoding='utf-8')
    print(f'Converted {len(cues)} subtitle cues')


if __name__ == '__main__':
    main()
