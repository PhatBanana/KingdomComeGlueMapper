"""Allow native eye adaptation to reach the KCD1 baked interior exposure range."""
import copy
import math
import xml.etree.ElementTree as ET

from upgrade_map import xml


def convert(blob, minimum_ev=4.0):
    """Cap only EV Min, including native HDR colour-space spline overrides.

    Keep lower authored limits, exposure compensation, EV Max, weather,
    sun intensity and probe radiance. This changes the adaptation boundary,
    not the exposure of a scene already above that boundary.
    """
    if not math.isfinite(minimum_ev) or not 0 < minimum_ev <= 4:
        raise ValueError('Expected a positive source-compatible EV floor <= 4')
    root = ET.fromstring(blob)
    tod = root.find('TimeOfDay')
    if tod is None:
        raise ValueError('Missing TimeOfDay settings')
    count = 0
    def cap(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Non-finite exposure key')
        return format(min(number, minimum_ev), '.9g')
    for variable in tod.iter('Variable'):
        if variable.get('Name') != 'EV Min':
            continue
        variable.set('Value', cap(variable.attrib['Value']))
        for curve in variable:
            if curve.tag not in ('Spline', 'ColorSpaceOverride'):
                continue
            keys = []
            for key in curve.attrib['Keys'].split(','):
                if not key:
                    continue
                time, value, flags = key.split(':')
                keys.append(':'.join((time, cap(value), flags)))
            curve.set('Keys', ','.join(keys) + (',' if keys else ''))
        count += 1
    if not count:
        raise ValueError('No EV Min variables found')
    return xml(root), {'minimum_ev_cap': minimum_ev, 'exposure_profiles': count}


def _minimums(root):
    tod = root.find('TimeOfDay')
    if tod is None:
        raise ValueError('Missing TimeOfDay settings')
    return [variable for variable in tod.iter('Variable') if variable.get('Name') == 'EV Min']


def _shape(element):
    """An element without its trailing whitespace, for comparison."""
    element = copy.deepcopy(element)
    element.tail = None
    return ET.tostring(element)


def restore(blob, native):
    """Undo convert() once a lighting bake lights the interiors itself.

    Only a mission whose EV Min variables are exactly convert(native)'s is
    changed; each is replaced by the native variable, keeping this file's
    layout. Anything else is returned unchanged, so a level that was not
    capped from this native mission is never given its exposure.
    """
    root = ET.fromstring(blob)
    ours = _minimums(root)
    expected = _minimums(ET.fromstring(convert(native)[0]))
    if [_shape(v) for v in ours] != [_shape(v) for v in expected]:
        return blob, {'restored_exposure_profiles': 0}
    parents = {child: parent for parent in root.iter() for child in parent}
    for variable, original in zip(ours, _minimums(ET.fromstring(native))):
        replacement = copy.deepcopy(original)
        replacement.tail = variable.tail
        parent = parents[variable]
        parent[list(parent).index(variable)] = replacement
    return xml(root), {'restored_exposure_profiles': len(ours)}
