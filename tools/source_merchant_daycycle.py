"""Authored merchant daycycles for the source merchant service builder.

A resident source keeper has a selling activity and a night at home. The home
night carries no activity link: the source brain resolves it from the keeper's
Home link, and the sleep extension owns that conversion. This module lets the
service builder accept exactly that shape and hands the night to the existing
sleep extension. Any other unlinked activity stays pending and fails the build.
"""
import zipfile
from pathlib import Path

SLEEP = 'sleep'
UNLINKED = 'No source activity link'


def source_restock_policy(shop):
    """Daily source stock is kept; weekday masks use the retail merchant period."""
    return 'source_daily' if shop['restock_day_mask'] == '127' else 'native_merchant'


def selling_schedule(schedule):
    """Move the unlinked home night out of `pending`; leave every other gap pending.

    Returns the schedule unchanged unless all its pending intervals are the
    authored sleep. The caller still rejects a schedule with anything pending.
    """
    pending = schedule['pending']
    if not pending or not schedule['resolved']:
        return schedule
    if any(entry['activity'].casefold() != SLEEP or entry.get('reason') != UNLINKED for entry in pending):
        return schedule
    return dict(schedule, pending=[], home_sleep=[dict(entry) for entry in pending])


def bind_sleep(files, merchant, source, target, *, source_level='rataje'):
    """Bind the keeper's authored night through the shared sleep extension.

    Call after the selling activity and shop hub are registered: the extension
    adds a higher-priority timed sleep pool beside the existing work links. A
    keeper without a converted bed would stand idle all night, so that fails.
    """
    from campaign_dependency_adapters import SourceTables
    from campaign_sources import RetailSourceReader
    from character_sleep_work import upgrade
    name = merchant['name']
    with RetailSourceReader(source) as reader, \
            zipfile.ZipFile(Path(source)/'Data/Levels'/source_level/'level.pak') as archive:
        files, reports = upgrade(files, {name: merchant}, archive, target, SourceTables(source, reader), reader, source)
    selected = [r for r in reports if r['person'] == name]
    if len(selected) != 1 or selected[0]['clock'].get('mode') != 'source' or not selected[0]['beds']:
        raise ValueError('Merchant night has no converted sleep place: ' + name)
    return files, selected[0]
