"""Resolve original quest journal text through retail database IDs.

No story text or quest-specific identifiers are embedded in the converter.
Missing strings are reported, never replaced by a different quest's text.
"""
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import retail_sources
from upgrade_map import read


TABLES = ('skald_objective', 'skald_objective_string', 'skald_objective_string_type',
          'skald_quest_string', 'skald_quest_string_type')


def register_journal_strings(blob):
    """Native journal fields require registered keys, not Text-only fallbacks."""
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None: raise ValueError('Expected a quest journal definition')
    records = []

    def bind(element, identity):
        if element is None: return
        text = element.get('Text', '')
        key = 'gmq_' + hashlib.sha256((quest.get('Name') + ':' + identity).encode()).hexdigest()[:24]
        element.set('StringName', key)
        records.append(dict(key=key, text=text))

    bind(quest.find('QuestName'), 'name')
    bind(quest.find('QuestDescription'), 'description')
    for objective in quest.findall('Objectives/Objective'):
        identity = objective.get('Name')
        bind(objective.find('LocalizedName'), identity + ':name')
        for state in objective.findall('Logs/EnumLog'):
            bind(state.find('Log'), identity + ':' + state.get('Name'))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), records


def localization_table(records):
    table = ET.Element('Table')
    seen = {}
    for row in records:
        if row['key'] in seen:
            if seen[row['key']] != row['text']: raise ValueError('Conflicting quest journal string')
            continue
        seen[row['key']] = row['text']
        element = ET.SubElement(table, 'Row')
        for value in (row['key'], row['text'], row['text']):
            ET.SubElement(element, 'Cell').text = value
    return ET.tostring(table, encoding='utf-8', xml_declaration=True)


def resolve(models, tables, strings):
    objective_types = {r['skald_objective_string_type_id']: r['skald_objective_string_type_name']
                       for r in tables['skald_objective_string_type']}
    quest_types = {r['skald_quest_string_type_id']: r['skald_quest_string_type_name']
                   for r in tables['skald_quest_string_type']}
    result, missing = {}, []
    for model in models:
        data = {'objectives': {}}
        result[model['quest']] = data
        quest_id = model['quest_id']
        subchapters = {r['skald_subchapter_id'] for r in model['tables']['quest2skald_subchapter']['rows']}
        if len(subchapters) > 1: raise ValueError('Ambiguous quest journal subchapter')
        elements = {}
        for r in tables['skald_objective']:
            if r['quest_id'] != quest_id: continue
            objective = r['objective_id']
            if objective in elements.values(): raise ValueError('Ambiguous objective journal element')
            elements[r['skald_element_id']] = objective
            data['objectives'][objective] = {}
        jobs = [(data, quest_types[r['skald_quest_string_type_id']], r['string_name'])
                for r in tables['skald_quest_string'] if r['skald_subchapter_id'] in subchapters]
        jobs += [(data['objectives'][elements[r['skald_element_id']]],
                  objective_types[r['skald_objective_string_type_id']], r['string_name'])
                 for r in tables['skald_objective_string'] if r['skald_element_id'] in elements]
        for destination, field, key in jobs:
            if field in destination: raise ValueError('Duplicate quest journal string role')
            if key not in strings or not strings[key]:
                missing.append(dict(quest=model['quest'], field=field, string=key))
            else:
                destination[field] = strings[key]
    return result, missing


def load(game, models, locale='English'):
    if not re.fullmatch(r'[A-Za-z]+', locale): raise ValueError('Invalid source locale')
    sources = retail_sources(game, {name: ('Tables.pak', 'Libs/Tables/skald/' + name + '.xml') for name in TABLES})
    tables = {name: [dict(r.attrib) for r in ET.fromstring(s['data']).findall('./table/rows/row')]
              for name, s in sources.items()}
    archive = Path(game) / 'Localization' / (locale + '_xml.pak')
    with zipfile.ZipFile(archive) as z:
        data = read(z, 'text_ui_quest.xml')
    strings = {}
    for row in ET.fromstring(data).findall('Row'):
        cells = row.findall('Cell')
        if len(cells) < 3: raise ValueError('Unsupported retail localization row')
        key = cells[0].text or ''
        value = ''.join(cells[2].itertext())
        if key in strings and strings[key] != value: raise ValueError('Conflicting localized text: ' + key)
        strings[key] = value
    result, missing = resolve(models, tables, strings)
    return result, dict(locale=locale, missing=missing,
                        tables={n: s['candidates'] for n, s in sources.items()},
                        strings=dict(archive='Localization/' + archive.name, entry='text_ui_quest.xml',
                                     sha256=hashlib.sha256(data).hexdigest()))
