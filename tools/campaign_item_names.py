"""Resolve inventory-preset names from actual native/imported item definitions."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def registered_item_name(identity, native, files):
    # Dependency conversion happens before inventory emission. Read its final
    # definitions, including replacement IDs, instead of deriving a name from
    # the source GUID or from the source display/localization label.
    definitions = dict(native)
    for path, blob in files.items():
        if not re.fullmatch(r'libs/tables/item/item(?:__[^/]+)?\.xml', path, re.I):
            continue
        if isinstance(blob, Path):
            blob = blob.read_bytes()
        for row in ET.fromstring(blob).findall('ItemClasses/*'):
            key = row.get('Id', '').lower()
            if not key:
                raise ValueError('Imported item has no registration ID')
            if key in definitions and definitions[key].get('Name') != row.get('Name'):
                raise ValueError('Conflicting native item name: ' + key)
            definitions[key] = row
    row = definitions.get(identity.lower())
    name = row.get('Name') if row is not None else None
    if not name or not name.strip():
        raise ValueError('Missing registered inventory item name: ' + identity)
    if any(key != identity.lower() and item.get('Name', '').lower() == name.lower()
           for key, item in definitions.items()):
        raise ValueError('Ambiguous registered inventory item name: ' + name)
    return name
