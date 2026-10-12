"""Compare two setup packages or build folders by content, ignoring write times.

Identical builds still differ byte for byte: most generated archives stamp each
ZIP entry with the time it was written, mod.manifest records created_on, and the
receipt therefore records different archive digests. Archives are compared by
entry name, order, compression, size and CRC-32 (SHA-256 of every entry with
--deep); those three volatile values are ignored and every other file must match
exactly. Read-only. Exits 1 when the folders differ.
"""
import argparse
import filecmp
import fnmatch
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

RECEIPT = 'gluemapper-install.json'


def relative_files(root, ignore=()):
    names = (p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    return {n for n in names if not any(fnmatch.fnmatch(n, pattern) for pattern in ignore)}


def archive_entries(path, deep=False):
    """Entry name, compression, size and content check value, in archive order."""
    entries = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            content = info.CRC
            if deep:
                with archive.open(info) as stream:
                    content = hashlib.file_digest(stream, 'sha256').hexdigest()
            entries.append((info.filename, info.compress_type, info.file_size, content))
    return entries


def entry_differences(name, left, right):
    if left == right:
        return []
    found = []
    a, b = {e[0]: e for e in left}, {e[0]: e for e in right}
    found += [f'{name}: {entry} only in left' for entry in sorted(a.keys() - b.keys())]
    found += [f'{name}: {entry} only in right' for entry in sorted(b.keys() - a.keys())]
    for entry in sorted(a.keys() & b.keys()):
        fields = [label for label, x, y in zip(('compression', 'size', 'content'), a[entry][1:], b[entry][1:]) if x != y]
        if fields:
            found.append(f'{name}: {entry} differs in {", ".join(fields)}')
    return found or [f'{name}: entry order or duplicate entries differ']


def manifest_without_date(path):
    root = ET.parse(path).getroot()
    for info in root.iter('info'):
        for node in info.findall('created_on'):
            info.remove(node)
    return ET.tostring(root)


def receipt_without_volatile_digests(path, prefix, volatile):
    """Digests of archives and manifests change with write times; those files are compared directly."""
    receipt = json.loads(path.read_text(encoding='utf-8'))
    receipt['files'] = {n: None if prefix + n in volatile else digest
                        for n, digest in receipt.get('files', {}).items()}
    return receipt


def compare(left, right, deep=False, ignore=()):
    left, right = Path(left), Path(right)
    left_names, right_names = relative_files(left, ignore), relative_files(right, ignore)
    differences = [f'{n}: only in {"left" if n in left_names else "right"}'
                   for n in sorted(left_names ^ right_names)]
    common = sorted(left_names & right_names)
    archives = {n for n in common if zipfile.is_zipfile(left / n) and zipfile.is_zipfile(right / n)}
    volatile = archives | {n for n in common if n.rsplit('/', 1)[-1] == 'mod.manifest'}
    for name in common:
        a, b = left / name, right / name
        filename = name.rsplit('/', 1)[-1]
        if name in archives:
            differences += entry_differences(name, archive_entries(a, deep), archive_entries(b, deep))
        elif filename == RECEIPT:
            prefix = name[:-len(RECEIPT)]
            first, second = (receipt_without_volatile_digests(p, prefix, volatile) for p in (a, b))
            changed = sorted(k for k in first.keys() | second.keys() if first.get(k) != second.get(k))
            if changed:
                differences.append(f'{name}: receipt differs in {", ".join(changed)}')
        elif filename == 'mod.manifest':
            if manifest_without_date(a) != manifest_without_date(b):
                differences.append(f'{name}: manifest differs beyond created_on')
        elif not filecmp.cmp(a, b, shallow=False):
            differences.append(f'{name}: content differs')
    return differences


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--left', required=True, type=Path, help='First package or build folder')
    parser.add_argument('--right', required=True, type=Path, help='Second package or build folder')
    parser.add_argument('--deep', action='store_true', help='Hash every archive entry instead of trusting stored CRC-32 values')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB',
                        help='Skip relative paths matching GLOB, e.g. "*report.json"; repeatable')
    parser.add_argument('--limit', type=int, default=50, help='Maximum differences to print')
    args = parser.parse_args()
    for root in (args.left, args.right):
        if not root.is_dir():
            parser.error(f'Not a directory: {root}')
    differences = compare(args.left, args.right, args.deep, args.ignore)
    print(json.dumps({'equivalent': not differences, 'differences': len(differences),
                      'shown': differences[:args.limit]}, indent=2))
    if differences:
        parser.exit(1)


if __name__ == '__main__':
    main()
