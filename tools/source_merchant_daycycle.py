"""Authored merchant daycycles for the source merchant service builder.

A resident source keeper has a selling activity and a night at home. The home
night carries no activity link: the source brain resolves it from the keeper's
Home link, and the sleep extension owns that conversion. This module lets the
service builder accept exactly that shape and hands the night to the existing
sleep extension. An unlinked morning between that night and selling is the
source's wait at home. Any other unlinked activity stays pending and fails the build.
"""
import zipfile
from pathlib import Path

SLEEP = 'sleep'
MORNING = 'morning'
UNLINKED = 'No source activity link'


def source_restock_policy(shop):
    """Daily source stock is kept; weekday masks use the retail merchant period."""
    return 'source_daily' if shop['restock_day_mask'] == '127' else 'native_merchant'


def selling_schedule(schedule):
    """Move the unlinked home night (and its morning) out of `pending`.

    Returns the schedule unchanged unless every pending interval is the
    authored sleep or a home morning. The caller still rejects a schedule with
    anything pending.

    Source `morning` is sa_city's goToSmartArea. Without an activity link it
    has no area, so it neither moves the keeper nor calls a behaviour: it waits
    where the night left them, at home, until the next activity. A morning that
    starts as the home night ends and ends as selling starts is therefore
    kept as that wait. It needs no binding, because the converted night and the
    timed selling link leave the keeper at home in between.
    """
    pending = schedule['pending']
    if not pending or not schedule['resolved']:
        return schedule
    if any(entry.get('reason') != UNLINKED for entry in pending):
        return schedule
    night = [e for e in pending if e['activity'].casefold() == SLEEP]
    morning = [e for e in pending if e['activity'].casefold() == MORNING]
    if not night or len(night) + len(morning) != len(pending):
        return schedule
    ends = {e['end_minute'] % 1440 for e in night}
    starts = {e['start_minute'] for e in schedule['resolved']}
    if any(e['start_minute'] not in ends or e['end_minute'] not in starts for e in morning):
        return schedule
    result = dict(schedule, pending=[], home_sleep=[dict(entry) for entry in night])
    if morning:
        result['home_morning'] = [dict(entry) for entry in morning]
    return result


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
