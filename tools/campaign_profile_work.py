"""Discover routines reached through profile actors rather than quest calls.

An EnableProfile can introduce an entire population. Their daycycle roots are
not IncludeTree calls in the quest, so a quest-only traversal misses their jobs.
"""
import xml.etree.ElementTree as ET
from campaign_profile_actors import collect
from character_person_ai import capture_person_ai, index_person_links
from character_schedule import plan
from campaign_work_sources import area_context
from quest_import import behavior_path
from campaign_ai_registration import brain_definition
from campaign_entity_links import native_guid


class ProfileWorld:
    """Build-scoped source index shared by profile discovery calls."""
    def __init__(self, profiles, souls, documents):
        self.profiles, self.souls = profiles, souls
        self.documents = {path: blob if isinstance(blob, ET.Element) else ET.fromstring(blob)
                          for path, blob in documents.items()}
        self.entities = [e for root in self.documents.values() for e in root.iter('Entity')]
        self.person_link_index = index_person_links(self.entities)
        self.indexed = {}
        for entity in self.entities:
            if entity.get('EntityGuid'):
                self.indexed.setdefault(entity.get('EntityGuid').lower(), []).append(entity)
        self.instances = {s.findtext('Guid'): s for s in souls.findall('SoulList/Souls/Soul')}


def discover(profiles, souls, documents, names, tables, world=None, native_person_brains=None):
    world = world or ProfileWorld(profiles, souls, documents)
    actors=collect(profiles,souls,world.documents,names)
    entities, indexed, instances = world.entities, world.indexed, world.instances
    programs={};records=[]
    for actor in actors:
        candidates=indexed.get(actor['entity_guid'].lower(),[])
        if len(candidates)!=1:raise ValueError('Ambiguous profile actor: '+actor['name'])
        soul=tables.row('rpg/soul','soul_id',actor['soul_id'])
        ai=capture_person_ai(tables,soul,candidates[0],instances[actor['instance_id']],entities,
                             link_index=world.person_link_index)
        brain=brain_definition(tables, ai['source_brain']['brain_id'])
        record=dict(actor=actor,source_brain=ai['source_brain'],brain_dependencies=brain,schedule=None)
        replacement = (native_person_brains or {}).get(ai['source_brain'].get('brain_name'))
        if replacement:
            record['native_brain'] = replacement
        # PersonRegistration already delegates ordinary engine services to the
        # native person brain. Importing an unused second legacy brain would
        # require obsolete combat/daycycle subbrains and never bind them to the
        # actor. Authored work and all of its explicit includes remain roots.
        for entry in ([] if replacement else brain['entry_points']):
            program=dict(entry,file=behavior_path(entry['file']))
            identity=(program['file'].lower(),program['tree'])
            if identity not in programs:programs[identity]=dict(program,actors=[])
            if actor['entity_guid'] not in programs[identity]['actors']:
                programs[identity]['actors'].append(actor['entity_guid'])
        try:record['schedule']=plan(dict(name=actor['name'],ai=ai),tables)
        except ValueError as error:record['unresolved']=str(error)
        for entry in (record['schedule'] or {}).get('resolved',[]):
            row=entry['behavior']
            registry='so_behaviour_tag' if entry['target_kind']=='quest_controller' else 'sa_behaviour_tag'
            candidate=dict(table=registry,row=row,file=behavior_path(row['tree_file']),tree=row['tree_name'])
            context=area_context([candidate],lambda name:tables.get('ai/'+name)['rows'])
            for program in [candidate,*context['programs']]:
                identity=(program['file'].lower(),program['tree'])
                if identity not in programs:programs[identity]=dict(program,actors=[])
                if actor['entity_guid'] not in programs[identity]['actors']:
                    programs[identity]['actors'].append(actor['entity_guid'])
        records.append(record)
    return dict(profiles=sorted(set(names)),actors=records,programs=list(programs.values()),
                runtime_verified=False)


def import_dependencies(models, importer):
    """Request every profile member, including people never named by a quest.

    Registration builds resources; profile activation still belongs to the
    authored transition. No actors are inserted into the always-active world.
    """
    records=[]
    for model in models:
        for population in model.get('profile_work_dependencies', []):
            for entry in population['actors']:
                actor=entry['actor']
                site=dict(quest=model['quest'], profiles=actor['profiles'], actor=actor['entity_guid'])
                soul=importer.ensure('souls',actor['soul_id'],site)
                entity=importer.ensure('entities',native_guid(int(actor['entity_guid'],16)),site)
                brain_error = None
                if entry.get('native_brain'):
                    expected = entry['native_brain']['brain_id']
                    job = importer.jobs.get(('souls', actor['soul_id'].lower()), {})
                    actual = job.get('evidence', {}).get('native_brain')
                    brain = actual if actual == expected else None
                    if brain is None:
                        brain_error = 'Registered actor does not confirm the selected native person brain'
                else:
                    brain=importer.ensure('brains',model['quest']+'|'+entry['source_brain']['brain_id'],site)
                areas=[]
                for activity in (entry.get('schedule') or {}).get('resolved',[]):
                    area_guid=activity['area'].get('EntityGuid')
                    if area_guid:
                        target=importer.ensure('entities',native_guid(int(area_guid,16)),site)
                        areas.append(dict(source=area_guid,target=target))
                programs=[p for p in population['programs'] if actor['entity_guid'] in p['actors']]
                trees=[]
                for program in programs:
                    from campaign_ai_registration import tree_identity
                    # tree_identity takes the path relative to Libs/AI.
                    path=program['file'][len('Libs/AI/'):]
                    identity=tree_identity(model['quest'],path,program['tree'])
                    trees.append(dict(source=identity,target=importer.ensure('behavior_trees',identity,site)))
                records.append(dict(**site,soul=soul,entity=entity,brain=brain,areas=areas,programs=trees,
                    pending_schedule=(entry.get('schedule') or {}).get('pending',[]),
                    schedule_error=entry.get('unresolved'),
                    brain_discovery_errors=entry['brain_dependencies']['unresolved'] if not entry.get('native_brain') else [],
                    native_brain=entry.get('native_brain'), brain_binding_error=brain_error,
                    runtime_verified=False))
    return records
