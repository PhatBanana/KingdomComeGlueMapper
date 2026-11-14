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

# Keeper and public shop namespace. Resident keepers outside the static world
# profile are selected here one by one; their namespace is the one the profile
# builder derives from the source shop (gm_source_shop_<source shop id>), so a
# keeper who later arrives with a profile keeps the same shop, saves and links.
# Every keeper below sells at an authored market point (innkeepers lean at
# their pub's Lean spot) and otherwise only sleeps at home; other daycycles
# need their own work adapters first.
MERCHANTS = (('ska_collierVarlet', 'gm_charcoal'),
             # Sasau: general stall, grocer, baker, tanner and vegetable stall.
             ('sas_woman23', 'gm_source_shop_62'),
             ('sas_merchant_grocery', 'gm_source_shop_71'),
             ('sas_bakers_wife', 'gm_source_shop_72'),
             ('sas_woman1', 'gm_source_shop_103'),
             ('sas_woman12', 'gm_source_shop_104'),
             # The Rattay armourer and the Sasau tailor bring their own stock items.
             ('rat_armorer', 'gm_source_shop_54'),
             ('sas_tailors_wife', 'gm_source_shop_70'),
             # Second batch: market keepers whose stock is already in the package,
             # except the Rattay general store, which imports 2 items.
             ('led_merchant_grocery', 'gm_source_shop_76'),
             ('aus_man3', 'gm_source_shop_117'),
             ('aus_baker', 'gm_source_shop_116'),
             ('aus_woman16', 'gm_source_shop_142'),
             ('mrh_woman5', 'gm_source_shop_120'),
             ('prib_bakers_wife', 'gm_source_shop_162'),
             ('rat_konrad_hagen', 'gm_source_shop_53'),
             # Third batch: Rattay market keepers with a home morning before work.
             # The butcher's and shoemaker's wives import 1 and 5 items.
             ('rat_merchant_grocery', 'gm_source_shop_52'),
             ('rat_woman11', 'gm_source_shop_96'),
             ('rat_merchant_shop1', 'gm_source_shop_97'),
             ('rat_merchant_shop3', 'gm_source_shop_98'),
             ('rat_merchant_shop2', 'gm_source_shop_99'),
             ('rat_butchers_wife', 'gm_source_shop_50'),
             ('rat_shoemakers_wife', 'gm_source_shop_56'),
             # Fourth batch: two-point Rattay keepers, innkeepers and bathhouses.
             # The swordsmith imports 13 weapons; the lower pub, the Rattay and
             # Sasau bathhouses 1 item each.
             ('rat_bakers_wife', 'gm_source_shop_49'),
             ('rat_swordsmith', 'gm_source_shop_100'),
             ('rat_innkeeper2', 'gm_source_shop_90'),
             ('rat_innkeeper1', 'gm_source_shop_93'),
             ('sas_innkeeper1', 'gm_source_shop_64'),
             ('led_innkeeper', 'gm_source_shop_77'),
             ('aus_innkeeper', 'gm_source_shop_61'),
             ('rat_spaAbbess', 'gm_source_shop_83'),
             ('sas_spaMistress', 'gm_source_shop_82'),
             ('led_barber1', 'gm_source_shop_84'),
             ('tal_spaAbbess', 'gm_source_shop_85'))
SOURCE_SHOP = 'gm_source_shop_'


def check_identity(person, namespace, report):
    """A derived namespace must name the shop this keeper really keeps."""
    stock = report['stock']
    if stock['shop_name'] != namespace + '_shop':
        raise ValueError('Source merchant shop name changed: ' + person)
    if namespace.startswith(SOURCE_SHOP) and str(stock['shop_id']) != str(20000 + int(namespace[len(SOURCE_SHOP):])):
        raise ValueError('Source merchant keeps a different shop: ' + person)


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
    if pending:
        # Temporary conversion lives beside the user's build, never on C:.
        # apply_overlay consumes its archives; remaining regenerable assets
        # are removed when the bounded stage closes. No retained build copies.
        # All pending keepers share one actor stage and one overlay, so the
        # level and travel archives are staged once, not once per keeper.
        people = [person for person, _ in pending]
        with tempfile.TemporaryDirectory(prefix='merchant-upgrade-',dir=package.parent) as temporary:
            stage = Path(temporary)/'actor'
            build_actors(SimpleNamespace(source=Path(source),target=Path(target),mod=package,
                output=stage,model=None,person=people,source_level='rataje',level=LEVEL,
                source_profile=[],dialogue_profile=[],dialogue_model=[],quest_path=None,
                project_path=PROJECT))
            actor_report = json.loads((stage/'report.json').read_text())
            if actor_report['pending'] or sorted(r['person'] for r in actor_report['converted']) != sorted(people):
                raise ValueError('Merchant actor conversion is incomplete: '+', '.join(people))
            for person, namespace in pending:
                report = build_service(source,target,package,stage/'package',person,namespace,ENTRY,LEVEL,
                    restock_policy='source',asset_archive=namespace+'_assets')
                check_identity(person, namespace, report)
                reports[namespace] = report
            changed.update(apply_overlay(package,stage/'package',consume=True))
    return changed, reports
