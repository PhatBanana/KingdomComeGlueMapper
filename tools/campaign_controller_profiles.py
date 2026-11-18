"""World profiles a controller switches, as the scene converter registers them.

The campaign importer's `WorldProfileAdapter` converts a profile only when
every layer member converts through the campaign's entity import and a
lifecycle adapter exists for `AutoActForOlderVersion`. In the analysis compile
of 2026-11-16 (people registered) none of the 152 source profiles of the
level converted: the members are level content (stashes, beds, cameras,
horses, brushes) that the map conversion owns, not the campaign importer.

The scene converter (C5, `campaign_scenes.register_profiles`) registers a
profile on the converted level instead: the entities the level already holds
move into one layer, and the profile is named `gm_<source name>`. For the
profiles it registers, this adapter gives the controller's `EnableProfile`
and `ProfileLoadedGate` that name. A profile it does not register stays
unconverted, with its reason. Nothing here checks that the registration
exists in a package: the build has to run C5 with the same list.
Not runtime-verified.
"""
from campaign_dependencies import ImportPlan


def native_name(source):
    """campaign_scenes.profile_name of the scene converter."""
    return 'gm_' + source


class OwnedProfiles:
    """`world_profiles` adapter for the dependency importer."""
    def __init__(self, registered):
        self.registered = {}
        for name in registered:
            if name.lower() in self.registered:
                raise ValueError('Duplicate registered world profile: ' + name)
            self.registered[name.lower()] = name

    def plan(self, identity):
        if identity not in self.registered:
            raise ValueError('World profile is not registered by the scene converter: ' + identity)
        return ImportPlan([], dict(name=self.registered[identity], registered_by='campaign_scenes.register_profiles'))

    def convert(self, identity, plan, registered):
        return native_name(plan.source['name']), {}, dict(source=plan.source['name'], runtime_validated=False,
                                                          registered_by=plan.source['registered_by'])


def report(importer, adapter):
    """Which profiles the controller asked for, and which the scene converter must still register."""
    asked = {identity: job for (group, identity), job in importer.jobs.items() if group == 'world_profiles'}
    return dict(registered=sorted(adapter.registered.values()),
                used={identity: dict(native=job.get('target'), sites=len(job['requested_by']))
                      for identity, job in sorted(asked.items()) if job['status'] == 'imported'},
                to_register={identity: len(job['requested_by']) for identity, job in sorted(asked.items())
                             if job['status'] != 'imported'},
                runtime_verified=False)
