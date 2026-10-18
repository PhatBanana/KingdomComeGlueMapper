"""Publish selected source merchant services for fresh builds and resume.

Selections describe content, not quest logic. Both paths call the same actor
and merchant converters as the verified in-game purchase test.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import zipfile
from upgrade_map import read

MERCHANTS = (('ska_collierVarlet', 'gm_charcoal'),)


def upgrade(package, source, target):
    from setup_gameplay import QUEST_PATH, ENTRY, LEVEL, PROJECT
    from build_quest_people_test import build as build_actors
    from source_merchant_upgrade import build as build_service
    from build_recipe import apply_overlay
    package = Path(package)
    reports, changed, pending = {}, {}, []
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as archive:
        if QUEST_PATH not in archive.namelist(): return {}, {}
        for person, namespace in MERCHANTS:
            marker = 'Libs/GlueMapper/'+namespace+'.json'
            if marker not in archive.namelist():
                pending.append((person,namespace))
                continue
            report = json.loads(read(archive,marker))
            if report.get('person') != person or report.get('version',1) != 1:
                raise ValueError('Unsupported source merchant migration: '+namespace)
            required = ('Quests/GlueTravel/entry/'+namespace+'_trade.xml',
                        'Libs/Tables/shop/shop__'+namespace+'.xml',
                        'Libs/Tables/item/InventoryPreset__'+namespace+'_stock.xml')
            if any(n not in archive.namelist() for n in required):
                raise ValueError('Incomplete source merchant package: '+namespace)
            reports[namespace] = report
    if pending and (source is None or target is None):
        raise ValueError('Source games required for merchant upgrade')
    for person, namespace in pending:
        # Temporary conversion lives beside the user's build, never on C:.
        # apply_overlay consumes its archives; remaining regenerable assets
        # are removed when the bounded stage closes. No retained build copies.
        with tempfile.TemporaryDirectory(prefix='merchant-upgrade-',dir=package.parent) as temporary:
            stage = Path(temporary)/'actor'
            build_actors(SimpleNamespace(source=Path(source),target=Path(target),mod=package,
                output=stage,model=None,person=[person],source_level='rataje',level=LEVEL,
                source_profile=[],dialogue_profile=[],dialogue_model=[],quest_path=None,
                project_path=PROJECT))
            actor_report = json.loads((stage/'report.json').read_text())
            if actor_report['pending'] or len(actor_report['converted']) != 1:
                raise ValueError('Merchant actor conversion is incomplete: '+person)
            report = build_service(source,target,package,stage/'package',person,namespace,ENTRY,LEVEL)
            changed.update(apply_overlay(package,stage/'package',consume=True))
            reports[namespace] = report
    return changed, reports
