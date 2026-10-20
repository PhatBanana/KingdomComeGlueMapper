"""Keep each localized key unique across the tables in one language archive."""
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml


def signature(node):
    # Formatting between cells is irrelevant; text inside a cell is not.
    text = node.text or ''
    if len(node) and not text.strip():
        text = ''
    return (node.tag, tuple(sorted(node.attrib.items())), text,
            tuple((signature(child), child.tail if (child.tail or '').strip() else '')
                  for child in node))


def reconcile(tables):
    """Remove identical duplicate rows, rejecting conflicting definitions.

    Localization is registered across files, not separately for each Table.
    Sorted filenames give repeated builds a stable owner without item-specific
    exceptions. Unmodified tables retain their original bytes.
    """
    owners, replacements, removed = {}, {}, []
    for name in sorted(tables):
        root = E.fromstring(tables[name])
        if root.tag != 'Table':
            continue
        changed = False
        for row in list(root):
            if row.tag != 'Row':
                continue
            key = row.findtext('Cell')
            if not key:
                raise ValueError('Localization row has no key: ' + name)
            value = signature(row)
            if key not in owners:
                owners[key] = (name, value)
                continue
            owner, previous = owners[key]
            if previous != value:
                raise ValueError(f'Conflicting localization key {key}: {owner} and {name}')
            root.remove(row)
            removed.append(dict(key=key, owner=owner, removed_from=name))
            changed = True
        if changed:
            replacements[name] = xml(root)
    return replacements, removed


def repair_package(package):
    """Called on a private package before its receipt hashes are finalized."""
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    changes, report = {}, []
    for path in sorted((Path(package)/'Localization').glob('*_xml.pak')):
        with zipfile.ZipFile(path) as archive:
            tables = {n: read(archive, n) for n in archive.namelist()
                      if n.lower().endswith('.xml')}
        replacements, duplicates = reconcile(tables)
        if replacements:
            relative = path.relative_to(package).as_posix()
            rewrite(Path(package), relative, replacements)
            changes[relative] = digest(path)
            report.append(dict(archive=relative, duplicates=duplicates))
    return changes, report
