"""Translate verified Lua API moves without rewriting literals or comments."""
import re

# Both shipped Utils.lua (KCD1) and ItemUtils.lua (KCD2) implement the same
# inventory transfer, assertion, and player notification contract.
TOKENS = re.compile(r"--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|\b(?:Utils|dc)\.[A-Za-z_]\w*", re.S)


def translate(script, roles=None):
    roles = roles or {}
    def replace(match):
        token = match.group()
        if token == 'Utils.GiveItem':
            return 'ItemUtils.GiveItem'
        if token.startswith('dc.') and token[3:] in roles:
            return 'dc.' + roles[token[3:]]
        return token
    return TOKENS.sub(replace, script)


def upgrade_dialogue(blob, source_roles):
    """Recover the role mapping emitted by register_roles for saved packages."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(blob)
    roles = {e.get('Role') for e in root.iter() if e.get('Role')}
    for body in root.iter('Dialogue'):
        roles.update(body.get('NonSpeakerRoles', '').split(','))
    mapping = {}
    for role in source_roles:
        matches = {name for name in roles if name.endswith('_' + role['role_id'])}
        if len(matches) == 1:
            mapping[role['role_name']] = next(iter(matches))
    changed = 0
    for sequence in root.iter('Sequence'):
        original = sequence.get('ExitScript')
        if original is None:
            continue
        updated = translate(original, mapping)
        if updated != original:
            sequence.set('ExitScript', updated); changed += 1
    return (ET.tostring(root, encoding='utf-8', xml_declaration=True) if changed else blob), changed
