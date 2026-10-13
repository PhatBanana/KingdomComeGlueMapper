"""Source-driven buff dependencies with semantic checks before native reuse."""
import hashlib
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependencies import ImportPlan
from campaign_quest_graph import identifier, xml
from campaign_sources import MissingRetailSource
from upgrade_map import read


ENUMS = ('buff_class', 'buff_exclusivity', 'buff_lifetime', 'buff_ai_tag',
         'buff_ui_type', 'buff_ui_visibility')
TEXT = {'buff_desc', 'buff_ui_name', 'slot_buff_ui_name'}
PRESENTATION = TEXT | {'icon_id', 'slot_icon_id', 'buff_ui_order'}


def normalized(row):
    return {('buff_params' if k == 'params' else k):
            (v.lower() if v in ('True', 'False') else v)
            for k, v in row.items() if v != ''}


def effect(row):
    return {k: v for k, v in normalized(row).items()
            if k not in PRESENTATION | {'buff_id', 'buff_name'}}


def native_contract(target):
    records, enums, provenance = [], {}, []
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as archive:
        for name in archive.namelist():
            low = name.lower()
            if low == 'libs/tables/rpg/buff.xml' or (
                    low.startswith('libs/tables/rpg/buff__') and low.endswith('.xml')):
                data = read(archive, name)
                records.extend(dict(n.attrib) for n in ET.fromstring(data).iter('buff'))
                provenance.append(dict(entry=name, sha256=hashlib.sha256(data).hexdigest()))
        for name in ENUMS:
            data = read(archive, 'Libs/Tables/rpg/' + name + '.xml')
            enums[name] = [dict(n.attrib) for n in ET.fromstring(data).iter(name)]
    return dict(records=records, enums=enums, provenance=provenance)


class BuffAdapter:
    def __init__(self, tables, contract, namespace):
        self.tables, self.contract = tables, contract
        self.namespace = identifier(namespace).lower()

    def plan(self, identity):
        uuid.UUID(identity)
        row = self.tables.row('rpg/buff', 'buff_id', identity)
        converted = normalized(row)
        candidates = [n for n in self.contract['records']
                      if n.get('buff_id', '').lower() == identity.lower()]
        if len(candidates) > 1:
            raise ValueError('Ambiguous native buff: ' + identity)
        # Numeric enum IDs are only safe if their source and target meanings agree.
        for name in ENUMS:
            field = name + '_id'
            if field not in converted:
                continue
            try:
                original = normalized(self.tables.row('rpg/' + name, field, converted[field]))
            except MissingRetailSource:
                # Retail omits some enum dictionaries. Retain the field only
                # with a matching named native record as explicit ABI evidence.
                if (not candidates or candidates[0].get('buff_name') != row.get('buff_name')
                        or candidates[0].get(field) != converted[field]):
                    raise ValueError('Missing source buff enum contract: ' + name)
                continue
            matches = [normalized(n) for n in self.contract['enums'][name]
                       if n.get(field) == converted[field]]
            if len(matches) != 1 or original != matches[0]:
                raise ValueError('Buff enum requires an upgrade: ' + name + ':' + converted[field])
        reusable = candidates and effect(candidates[0]) == effect(row)
        if reusable:
            mode, target = 'merge_native', candidates[0]['buff_id']
        else:
            mode = 'convert_source'
            target = str(uuid.uuid5(uuid.NAMESPACE_URL,
                         'gluemapper/campaign/' + self.namespace + '/buff/' + identity.lower()))
            fields = set().union(*(normalized(n).keys() for n in self.contract['records']))
            unknown = set(converted) - fields
            if unknown:
                raise ValueError('Unsupported buff fields: ' + ', '.join(sorted(unknown)))
            # Only upgrade formulas whose individual clauses are demonstrated by
            # this native implementation. Arbitrary source scripts are not copied.
            implementations = [n for n in self.contract['records']
                               if n.get('implementation') == converted.get('implementation')]
            if not implementations:
                raise ValueError('Unsupported buff implementation: ' + str(converted.get('implementation')))
            clauses = {c.strip() for n in implementations
                       for c in n.get('buff_params', '').split(',') if c.strip()}
            missing = {c.strip() for c in converted.get('buff_params', '').split(',') if c.strip()} - clauses
            if missing:
                raise ValueError('Buff formula requires an upgrade: ' + ', '.join(sorted(missing)))
            for field in ('icon_id', 'slot_icon_id'):
                if converted.get(field, '0') != '0':
                    raise ValueError('Source buff icon needs atlas conversion: ' + converted[field])
            if converted.get('visual_effect'):
                raise ValueError('Buff visual effect needs asset conversion')
        deps = [('strings', converted[k]) for k in sorted(TEXT)
                if converted.get(k)] if not reusable else []
        return ImportPlan(deps, dict(row=row, converted=converted, mode=mode, target=target,
            native=candidates, provenance=self.tables.get('rpg/buff')['provenance']))

    def convert(self, identity, plan, registered):
        source = plan.source
        files = {}
        if source['mode'] == 'convert_source':
            row = dict(source['converted'], buff_id=source['target'],
                       buff_name=self.namespace + '_buff_' + identity.replace('-', ''))
            for field in TEXT:
                if row.get(field):
                    row[field] = registered['strings'][row[field].lower()]
            root = ET.Element('database', name='barbora')
            ET.SubElement(ET.SubElement(root, 'buffs', version='1'), 'buff', row)
            files['Libs/Tables/rpg/buff__' + self.namespace + '_' + identity.replace('-', '') + '.xml'] = xml(root)
        return source['target'], files, dict(mode=source['mode'], source_effect=effect(source['row']),
            target_effect=effect(source['converted']), native_provenance=self.contract.get('provenance', []),
            presentation='native' if source['mode'] == 'merge_native' else 'converted_source',
            runtime_validated=False)
