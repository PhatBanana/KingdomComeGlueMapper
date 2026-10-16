"""Retain KCD1 route-policy defaults when using KCD2's engine-owned record."""
import re

# Libs/AI/TypeDefinitions_SaveGame.xml, pathFindingParams in source retail.
# Emit every field: the destination's default constructor is not a conversion.
DEFAULTS = dict(usePaths='true', useSmartObjects='true', autoAllowedSmartObjects='true',
                useDoorPortals='false', useGeneratedNSO='false', enableSecondTryWithGenNSO='true')


def native_fields(tree):
    """Collect members only from variables declared as the native parameter type."""
    fields = set()
    for variable in tree.findall('./Variables/Variable'):
        if variable.get('type') != 'pathFindingParams':
            continue
        fields.update(re.findall(r'([A-Za-z_]\w*)\s*\(', variable.get('values', '')))
        name = variable.get('name', '')
        if not name:
            continue
        for node in tree.findall('.//Root//Expression'):
            fields.update(re.findall(r'\$' + re.escape(name) + r'\.([A-Za-z_]\w*)\s*=',
                                     node.get('expressions', '')))
    return fields


def convert(values, fields):
    missing = set(DEFAULTS) - set(fields)
    if missing:
        raise ValueError('Native route-policy members are unverified: ' + ', '.join(sorted(missing)))
    result, seen = dict(DEFAULTS), set()
    for part in values.split(',') if values.strip() else []:
        match = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*\(\s*(true|false)\s*\)\s*', part)
        if not match or match[1] not in result or match[1] in seen:
            raise ValueError('Unsupported source route-policy initializer: ' + part)
        result[match[1]] = match[2]
        seen.add(match[1])
    return ','.join(name + '(' + value + ')' for name, value in result.items())
