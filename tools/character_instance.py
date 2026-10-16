"""Resolve placed-person overrides before discovering source dependencies."""

ZERO_GUID = '00000000-0000-0000-0000-000000000000'


def effective_soul(shared, instance):
    result = dict(shared)
    fields = {'inventory_id': 'InventoryId'}
    fields.update({'character_' + kind + '_id': 'CharacterBodyDescription/' + kind.title() + 'Id'
                   for kind in ('body', 'head', 'hair', 'beard')})
    fields.update({'initial_' + kind + '_preset_id': 'Initial' + kind.title() + 'Description/PresetId'
                   for kind in ('clothing', 'weapon')})
    if instance is not None:
        for field, path in fields.items():
            value = instance.findtext('StaticData/' + path)
            # Unset instance references inherit the shared definition.
            if value and value != ZERO_GUID:
                result[field] = value
    return result
