"""Import selected KCD1 town residents with their homes, work and sleep.

Residents live in KCD1's base world, outside the static world profiles, so they
are selected here by soul name, town by town. The same actor, schedule, work and
sleep converters as the profile population run for them. Each one keeps the
KCD1 home, and the KCD1 work that an existing native work adapter supports.
Their unlinked sleep, eat, morning and fun intervals are home time
(character_schedule.blocking_pending). Shop keepers are not residents here;
they come through setup_merchant_upgrade with their shop.
"""
from pathlib import Path
import os
import tempfile

from setup_campaign import RECEIPT
from filesystem_paths import filesystem_path

VERSION = 1
MODE = 'selected_town_residents'
MARKER = 'resident_population'

# Rattay batch 1 (2026-11-14): every KCD1 resident whose work is the city walk,
# the nine shop guards and the stable's horse handler. Each has a KCD1 home.
# rat_machal (city walk) is left out: his placed instance name has no soul row
# of that name, so the actor stage cannot select him by name.
# Survey: D:/KCD/Builds/glue/issues/npcs/SURVEY.md.
RATTAY_1 = (
    # City walk: craftsmen's wives and townsfolk on the streets.
    'rat_armorers_wife', 'rat_bailiff_wife', 'rat_konyas_wife', 'rat_man117', 'rat_man16',
    'rat_man19', 'rat_man77', 'rat_man81', 'rat_man83', 'rat_man95', 'rat_man97', 'rat_ruch',
    'rat_swordsmiths_wife', 'rat_woman10', 'rat_woman12', 'rat_woman3', 'rat_woman32', 'rat_woman34',
    'rat_woman44', 'rat_woman47',
    # Shop guards at the market shops.
    'rat_shop_guard_armorer', 'rat_shop_guard_baker', 'rat_shop_guard_butcher', 'rat_shop_guard_general',
    'rat_shop_guard_grocery', 'rat_shop_guard_pharmacy', 'rat_shop_guard_shoemaker',
    'rat_shop_guard_swordsmith', 'rat_shop_guard_tailor',
    # The stable.
    'rat_horse_handler',
    # Housework at home.
    'rat_karolina', 'rat_man115', 'rat_man118', 'rat_man3', 'rat_man84', 'rat_pickpocket_woman1', 'rat_slavoj',
    'rat_woman13', 'rat_woman14', 'rat_woman16', 'rat_woman17', 'rat_woman20', 'rat_woman21', 'rat_woman23',
    'rat_woman24', 'rat_woman25', 'rat_woman27', 'rat_woman35', 'rat_woman4', 'rat_woman43', 'rat_woman50',
    'rat_woman52', 'rat_woman54', 'rat_woman55', 'rat_woman57', 'rat_woman58', 'rat_woman59', 'rat_woman6',
    'rat_woman61', 'rat_woman7', 'rato_man1', 'rato_woman1',
    # Farmers.
    'rat_man111', 'rat_man112', 'rat_man114', 'rat_man119', 'rat_man120', 'rat_upper_farmer', 'rat_woman53',
    'rat_woman56', 'rat_woman60', 'rato_babaMyskova',
    # People the KCD1 main quests up to the hunt need (feat/kcd1-quests-1). Their
    # KCD1 work has no native adapter yet, so they keep the native wait at their
    # KCD1 spot; the bailiff, Janik, Jana, the beggar and the parson keep homes.
    # rat_berthold keeps a KCD1 shop, so he comes through the shop route.
    'rat_bernard', 'rat_bailiff', 'rat_hanus', 'rat_racek_kobyla', 'rat_ptacek', 'rat_guardJanik',
    'rat_refugee_jana', 'rat_refugee_beggar', 'rat_parson',
)
RESIDENTS = RATTAY_1


def check_selection(residents=RESIDENTS):
    """Each resident once, and never a keeper that setup_merchant_upgrade imports."""
    from setup_merchant_upgrade import MERCHANTS
    if len(set(residents)) != len(residents):
        raise ValueError('A resident is selected twice')
    keepers = sorted(set(residents) & {person for person, _ in MERCHANTS})
    if keepers:
        raise ValueError('Shop keepers are imported with their shop, not as residents: ' + ', '.join(keepers))
    return list(residents)


def upgrade(package, source, target, notify=lambda *a: None, cancelled=lambda: False, residents=RESIDENTS):
    from build_profile_population_upgrade import build
    from build_recipe import apply_overlay
    from setup_gameplay import ENTRY, LEVEL

    names = check_selection(residents)
    if not names:
        return {}, dict(version=VERSION, mode=MODE, residents=[], people=0, runtime_verified=False)
    if source is None or target is None:
        raise ValueError('Both source games are required for resident population conversion')
    if cancelled(): raise InterruptedError('Cancelled before resident population conversion')
    package = filesystem_path(package)
    notify('Import KCD1 town residents', 0, 0, f'{len(names)} selected residents')
    with tempfile.TemporaryDirectory(prefix='resident-population-', dir=package.parent) as temporary:
        work = Path(temporary)
        report = build(source, target, package, work/'build', [], level=LEVEL, entry=ENTRY,
            update_receipt=False, cancelled=cancelled, progress=notify, names=names, marker=MARKER,
            notify=lambda message: notify('Import KCD1 town residents', 0, 0, message))
        placed = [r['person'] for r in report.get('residents', [])]
        failed = {r['person'] for r in report.get('residue', [])}
        if (report.get('version') != 1 or report.get('level') != LEVEL or report.get('people') != len(placed)
                or placed != [n for n in names if n not in failed] or not failed <= set(names)):
            raise ValueError('Resident population builder did not validate the selected residents')
        if cancelled(): raise InterruptedError('Cancelled before publishing resident population')
        notify('Publish KCD1 town residents', 0, 0, 'Publishing validated residents')
        # Same publication rule as the profile population: only detached or new
        # outputs, never the cloned receipt or unchanged hard-linked archives.
        staged = work/'build/package'
        overlay = work/'overlay'
        for path in sorted(staged.rglob('*')):
            if not path.is_file(): continue
            if path.is_symlink() or not path.resolve().is_relative_to(staged):
                raise ValueError('Unsafe resident population output: ' + str(path))
            relative = path.relative_to(staged)
            if relative.as_posix() == RECEIPT: continue
            original = package/relative
            if original.exists() and os.path.samefile(original, path): continue
            destination = overlay/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)
        changed = apply_overlay(package, overlay, consume=True) if overlay.exists() else {}
    notify('Import KCD1 town residents', 1, 1, 'Residents, homes, work and sleep validated')
    return changed, dict(version=VERSION, mode=MODE, residents=report['residents'], residue=report['residue'],
        people=report['people'],
        added=len(report['added']), scheduler_validation=True, runtime_verified=False, work=report['work'])
