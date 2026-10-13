"""Resolve garment morph requests against source geometry and clothing records."""
import re


def resolve_variant(part, morphs, clothing_rows):
    requested = part.get('morph_target') or None
    evidence = dict(requested=requested, applied=requested, status='present' if requested else 'base')
    if not requested or requested in morphs:
        return requested, evidence
    # Dedicated garment meshes can retain a stale variant selector in the RPG
    # table. Accept their base shape only when another source clothing record
    # explicitly uses that SAME mesh/archetype/gender with no selector, and the
    # mesh contains no selectable variant shapes. Adjustment morphs are not
    # substitutes for garment variants and must not be applied here.
    def model(row):
        return row.get('model', '').replace('\\', '/').lower().removesuffix('.skin')
    base_rows = [row for row in clothing_rows if model(row) == model(part)
                 and not row.get('morph_target')
                 and all(row.get(k) == part.get(k) for k in ('armor_archetype_id', 'gender_id'))]
    has_variants = any(re.search(r'(?:^|:)#?V_', name, re.I) for name in morphs)
    if re.fullmatch(r'#V_\d+', requested) and not has_variants and base_rows:
        evidence.update(applied=None, status='source_base_geometry',
                        base_clothing_ids=sorted(row['clothing_id'] for row in base_rows),
                        available_morphs=list(morphs))
        return None, evidence
    raise ValueError(f'Requested variant {requested} missing in {part.get("model")}; available: {morphs}')
