"""Preserve source smart-object property data and upgrade bounded property reads."""
import re
from campaign_lua_contracts import tokens


def misc_properties(attributes):
    """Encode Script fields in the native Misc data format, retaining precedence.

    Both retail EntityUtils readers parse |key:value entries; named source
    fields override Misc entries. This is property data, never Lua execution.
    """
    values = {}
    raw = attributes.get('Misc', '')
    for match in re.finditer(r'\|?([^:]+):([^|]+)', raw):
        values[match[1]] = match[2]
    # Refuse a malformed tail or separator instead of losing authored data.
    if raw and ''.join(m[0] for m in re.finditer(r'\|?([^:]+):([^|]+)', raw)) != raw:
        raise ValueError('Malformed source Script Misc property data')
    values.update({k:v for k,v in attributes.items() if k != 'Misc'})
    for name, value in values.items():
        if not name or ':' in name or '|' in name or '|' in value or not value:
            raise ValueError('Script property cannot be represented in native Misc: ' + name)
    return '|'.join(name + ':' + value for name,value in values.items())


def upgrade_reads(script, supported, misc_supported=False):
    """Translate whole lookup/assignment programs only, with no extra Lua allowed."""
    if not supported and not misc_supported:
        return None
    program = tokens(script)
    if program is None:
        return None
    p, aliases, output, reads = 0, {'entity': 'entity'}, [], 0

    def take(*items):
        nonlocal p
        if program[p:p+len(items)] != items:
            raise ValueError
        p += len(items)

    def identifier():
        nonlocal p
        value = program[p]
        if not re.fullmatch(r'[A-Za-z_]\w*', value):
            raise ValueError
        p += 1
        return value

    def data_reference():
        take('data', '.')
        parts = ['data', '.', identifier()]
        while p < len(program) and program[p] == '.':
            take('.')
            parts.extend(('.', identifier()))
        return parts

    try:
        while p < len(program):
            if program[p] == 'local':
                take('local')
                name = identifier()
                if name in ('data', 'entity', 'EntityUtils', 'XGenAIModule') or name in aliases:
                    return None
                take('=', 'XGenAIModule', '.')
                lookup = identifier()
                if lookup not in ('GetEntityByWUID', 'GetEntityIdByWUID'):
                    return None
                take('(')
                ref = data_reference()
                take(')')
                aliases[name] = 'entity' if lookup == 'GetEntityByWUID' else 'entity_id'
                output.append('local ' + name + ' = XGenAIModule.' + lookup + '(' + ''.join(ref) + ')')
            else:
                ref = data_reference()
                take('=')
                reader = identifier()
                readers = {'GetEntityScriptProperty': ('entity', 'GetScriptProperty', supported),
                           'GetEntityMiscProperty': ('entity_id', 'GetMiscProperty', misc_supported)}
                if reader not in readers or not readers[reader][2]:
                    return None
                kind, native_reader, _ = readers[reader]
                take('(')
                actor = identifier()
                if aliases.get(actor) != kind: return None
                take(',')
                prop = program[p]; p += 1
                if not re.fullmatch(r'''(['"])[A-Za-z_][A-Za-z_0-9]*\1''', prop):
                    return None
                take(')')
                statement = ''.join(ref) + ' = EntityUtils.' + native_reader + '(' + actor + ', ' + prop + ')'
                if p < len(program) and program[p] == 'or':
                    take('or')
                    default = program[p]; p += 1
                    if not (default in ('true','false','nil') or re.fullmatch(r'\d+(?:\.\d+)?', default)
                            or (len(default) >= 2 and default[0] in "'\"" and default[-1] == default[0])):
                        return None
                    statement += ' or ' + default
                output.append(statement)
                reads += 1
            if p < len(program) and program[p] == ';': take(';')
    except (ValueError, IndexError):
        return None
    return '; '.join(output) if reads else None
