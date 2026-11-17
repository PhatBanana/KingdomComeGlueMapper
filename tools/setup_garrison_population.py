"""Import KCD1 town garrison guards with their KCD1 posts, homes and sleep.

KCD1 places town guards with its garrison allocator, not with authored posts.
garrison_census replays that allocator and writes tools/garrison_selection.py;
here the selected guards go through the resident build (setup_resident_population)
with their own marker, and garrison_posts gives each one its census post as the
garrison_forcedWorkplace link before any conversion. A guard is never both a
resident and a garrison guard (check_selection).
"""
from setup_resident_population import upgrade as upgrade_people

VERSION = 1
MODE = 'kcd1_garrison_guards'
MARKER = 'garrison_population'
# Towns whose garrisons are imported so far (garrison_census --town).
TOWNS = ('rattay',)


def selected():
    from garrison_selection import GUARDS
    return GUARDS


def check_selection(guards):
    """Guards the stage imports: never a selected resident or quest person, never a shop keeper."""
    from resident_selection import RESIDENTS
    from setup_merchant_upgrade import MERCHANTS
    residents = {name for names in RESIDENTS.values() for name in names}
    keepers = {person for person, _ in MERCHANTS}
    clash = sorted(set(guards) & (residents | keepers))
    if clash:
        raise ValueError('Garrison guards also selected by another stage: ' + ', '.join(clash))
    return sorted(guards)


def upgrade(package, source, target, notify=lambda *a: None, cancelled=lambda: False, guards=None):
    import garrison_posts
    guards = selected() if guards is None else guards
    names = check_selection(guards)

    def prepare(people):
        return garrison_posts.apply(people, source, guards)

    changed, result = upgrade_people(package, source, target, notify, cancelled, tuple(names),
                                     marker=MARKER, mode=MODE, prepare=prepare,
                                     title='Import KCD1 garrison guards')
    result['version'] = VERSION
    result['allocation'] = 'garrison_census: KCD1 sa_garrison allocator replayed, one frozen day per guard'
    return changed, result
