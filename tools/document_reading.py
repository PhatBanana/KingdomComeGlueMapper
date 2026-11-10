"""Carry source document reading rewards into the native reading tables.

Both games grant a read document's effect from tables keyed by the item, not
from the item row: rpg/document_required_skill (skill gate and skill XP),
rpg/document_reward and rpg/document_requirement (Lua run by the reading
code, used by stat books), and the document's recipe id. The item row alone
therefore imports a book that can be opened but teaches nothing.

Nothing here is runtime evidence. `offline_supported` only states that the
rows the native reading code is keyed on were emitted, or that the source
document never had a reward.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from character_person import native_xml
from upgrade_map import read, xml


# Source skills that the native skill table no longer names. Each successor is
# the one the native data itself uses: either the native skill keeps the source
# skill_id under a new name, or perks retained by GUID moved their
# skill_selector from the source skill to it.
SKILL_SUCCESSORS = {
    'hunter': 'survival',          # same skill_id 14
    'herbalism': 'survival',       # retained perks: selector 25 -> 14
    'lockpicking': 'thievery',     # same skill_id 4
    'pickpocketing': 'thievery',   # retained perk: selector 5 -> 4
    'repairing': 'craftsmanship',  # same skill_id 8
    'reading': 'scholarship',      # same skill_id 26
}
# Source Lua names the four stats by abbreviation. Native reading rows spell
# them out as rpg/stat.xml does.
STAT_NAMES = {'str': 'strength', 'agi': 'agility', 'vit': 'vitality', 'spc': 'speech'}
# Every native row in the reading tables belongs to a Type 3 (skillBook)
# document. The source game had no such class and filed skill books as books.
SKILL_BOOK_TYPE = '3'

REWARD_SCRIPT = re.compile(
    r'RPG\.AddStatXP\(event, soul, "(\w+)", (\d+), oldProgress, newProgress\);'
    r'RPG\.NotifyLevelXpGain\("(\w+)"\);')
REQUIREMENT_SCRIPT = re.compile(
    r'if\(playerSoul\.soul:GetStatLevel\(\'(\w+)\'\)<(\d+)\)\s+then\s+'
    r'return "@ui_playerCantStudy_lowSkill";\s+end')

TABLES = {
    'document_required_skill': ('document_required_skills', 'document_required_skill'),
    'document_reward': ('document_rewards', 'document_reward'),
    'document_requirement': ('document_requirements', 'document_requirement'),
}


def native_reading_contract(target):
    """Native skill, stat and alchemy recipe identities the rewards refer to."""
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as archive:
        def rows(name, tag):
            return [dict(r.attrib) for r in native_xml(read(archive, 'Libs/Tables/' + name + '.xml')).iter(tag)]
        return dict(
            skills=[dict(skill_id=r['skill_id'], skill_name=r['skill_name'], hidden=r.get('hidden', 'false'))
                    for r in rows('rpg/skill', 'skill')],
            stats=[r['stat_name'] for r in rows('rpg/stat', 'stat')],
            recipes=[r['RecipeId'] for r in rows('minigame/AlchemyRecipe', 'AlchemyRecipe')])


def source_reading(tables, identity, document):
    """Join every source record that gives reading this document an effect."""
    source = {name: dict(tables.row('rpg/' + name, 'item_id', identity, optional=True)) for name in TABLES}
    skill = source['document_required_skill']
    if skill:
        source['skill'] = dict(tables.row('rpg/skill', 'skill_id', skill['skill_id']))
    recipe = document.get('recipe_id')
    if recipe:
        source['recipe'] = dict(tables.row('item/recipe', 'recipe_id', recipe, optional=True)) or {'recipe_id': recipe}
    return {name: row for name, row in source.items() if row}


def _native_skill(contract, name):
    def visible(wanted):
        return [s for s in contract['skills'] if s['skill_name'] == wanted and s['hidden'].lower() != 'true']
    for candidate, basis in ((name, 'same_name'), (SKILL_SUCCESSORS.get(name), 'native_successor')):
        found = visible(candidate) if candidate else []
        if len(found) == 1:
            return found[0], basis
    return None, None


def _stat_script(pattern, script, contract):
    """Respell a stat script only when it is exactly the shape natives use."""
    match = pattern.fullmatch(script.replace('\r\n', '\n').strip())
    if not match:
        return None, 'source script is not the stat book form the native tables use'
    names = {g for g in match.groups() if not g.isdigit()}
    if len(names) != 1:
        return None, 'source script names more than one stat'
    source = names.pop()
    stat = STAT_NAMES.get(source, source)
    if stat not in contract['stats']:
        return None, 'no native stat for source stat ' + source
    quoted = re.compile(r'(["\'])' + re.escape(source) + r'\1')
    return quoted.sub(lambda m: m[1] + stat + m[1], match.string), None


def _table(namespace, identity, name, attrs):
    group, tag = TABLES[name]
    root = ET.Element('database', name='barbora')
    ET.SubElement(ET.SubElement(root, group, version='1'), tag, attrs)
    path = 'Libs/Tables/rpg/' + name + '__' + namespace + '_' + identity.replace('-', '') + '.xml'
    return path, xml(root)


def convert_reading(identity, target, source, contract, namespace):
    """Return native table patches, a document type and honest evidence.

    Rewards are all or nothing: a book whose gate converts but whose reward
    does not would take the reading time and teach nothing.
    """
    evidence = dict(source=source, runtime_verified=False)
    def unsupported(reason):
        return {}, None, dict(evidence, status='unsupported', offline_supported=False, reason=reason)
    if source is None:
        # An absent join is not evidence that the source had no reward.
        return unsupported('Source reading tables were not joined for this document')
    if not source:
        return {}, None, dict(evidence, status='no_source_reward', offline_supported=True,
            reason='The source game has no reading reward, requirement or recipe row for this document')
    if 'recipe' in source:
        recipe = source['recipe']['recipe_id']
        known = contract is not None and recipe in contract['recipes']
        return unsupported('Source alchemy recipe ' + recipe + (
            ' exists natively, but its document is not a retained native item; the recipe identity is unproven'
            if known else ' has no native AlchemyRecipe, recipe perk or perk_recipe row; the recipe itself is not ported'))
    if contract is None:
        return unsupported('Native skill and stat tables were not supplied to the item adapter')
    files, native = {}, {}
    if 'document_required_skill' in source:
        row, name = source['document_required_skill'], source['skill']['skill_name']
        skill, basis = _native_skill(contract, name)
        if skill is None:
            return unsupported('No visible native skill for source skill ' + name)
        native['document_required_skill'] = dict(item_id=target, skill_id=skill['skill_id'],
            skill_level_required=row['skill_level_required'], skill_xp_gained=row['skill_xp_gained'])
        evidence['skill_mapping'] = dict(source_id=row['skill_id'], source_name=name,
            target_id=skill['skill_id'], target_name=skill['skill_name'], basis=basis)
    for name, pattern in (('document_reward', REWARD_SCRIPT), ('document_requirement', REQUIREMENT_SCRIPT)):
        if name in source:
            script, reason = _stat_script(pattern, source[name]['script'], contract)
            if script is None:
                return unsupported(name + ': ' + reason)
            native[name] = dict(item_id=target, script=script)
    if not any(name in native for name in ('document_required_skill', 'document_reward')):
        return unsupported('The source document has a reading requirement but no reward')
    for name, attrs in native.items():
        path, blob = _table(namespace, identity, name, attrs)
        files[path] = blob
    return files, SKILL_BOOK_TYPE, dict(evidence, status='native_tables_emitted', offline_supported=True,
        native=native, files=sorted(files), document_type=SKILL_BOOK_TYPE,
        reason='Native reading tables are keyed by item_id; every native row belongs to a Type 3 document')
