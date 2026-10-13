"""Allow native eye adaptation to reach the KCD1 baked interior exposure range."""
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
