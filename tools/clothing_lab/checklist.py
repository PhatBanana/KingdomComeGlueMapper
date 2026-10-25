"""Publish a reproducible, scoped checklist from completed developer audits."""
import csv
import json
from pathlib import Path
from .matrix import VALIDATION_CONTRACT


def write_checklist(matrix, full_layers, repairs, output, source_report=None, captures=None):
    matrix,full_layers,repairs,output=map(Path,(matrix,full_layers,repairs,output))
    summary=json.loads((matrix/'summary.json').read_text(encoding='utf-8'))
    full=json.loads((full_layers/'summary.json').read_text(encoding='utf-8'))
    repair=json.loads((repairs/'repair.json').read_text(encoding='utf-8'))
    catalog=json.loads((matrix/'catalog.json').read_text(encoding='utf-8'))
    if not summary['matrix_enumeration_complete']:
        raise ValueError('The single/pair matrix is incomplete')
    if not full.get('enumeration_complete'):
        raise ValueError('The full-layer enumeration is incomplete')
    if summary['signature']!=full['signature']:
        raise ValueError('Reports describe different candidates')
    if (summary.get('validation_contract')!=VALIDATION_CONTRACT or
            full.get('validation_contract')!=VALIDATION_CONTRACT or
            summary['rule_evidence']!=full['rule_evidence']):
        raise ValueError('Reports describe different or outdated validation rules')
    extras={}
    for label,path in (('Source soul audit',source_report),('Rendered examples',captures)):
        if path:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if data['signature']!=summary['signature'] or data.get('rule_evidence',data.get('rules'))!=summary['rule_evidence']:
                raise ValueError('Supplementary evidence describes a different candidate or native rules')
            extras[label]=(str(path),data)
    parts={p['id']:p for p in catalog['parts']}
    presets={p['id']:p for p in catalog['presets']}
    confirmed=json.loads((matrix/'confirmed.json').read_text(encoding='utf-8'))
    for row in json.loads((full_layers/'confirmed.json').read_text(encoding='utf-8')):
        confirmed.append(dict(row,case='full-layer:'+str(row['case']),gender=full['gender'],body=full['body']))
    unique={}
    baselines=[]
    for row in confirmed:
        if not any(parts[i]['kind']=='Clothing' for i in row['selected']):
            baselines.append(row);continue
        unique.setdefault((row['body'],tuple(sorted(row['selected']))),row)
    garment_count=sum(g['counts']['singles'] for g in summary['genders'].values())
    pair_count=sum(g['counts']['pairs'] for g in summary['genders'].values())
    output.parent.mkdir(parents=True,exist_ok=True)
    listing=output.with_name(output.stem+'-confirmed.csv')
    with listing.open('w',newline='',encoding='utf-8') as file:
        writer=csv.writer(file)
        writer.writerow(['confirmed_by_enabled_checks','case','gender','body_preset','body_name','garment_roles',
                         'exact_components','native_table_contract','bind_pose_geometry','native_runtime'])
        for row in unique.values():
            writer.writerow(['yes',row['case'],row['gender'],row['body'],presets[row['body']]['label'],
                ';'.join(parts[i]['attributes'].get('ArmorType','fallback') for i in row['selected'] if parts[i]['kind']=='Clothing'),
                ';'.join(row['selected']),'checked','checked','NOT VERIFIED'])
    lines=['# Clothing combination validation checklist','',
        'This is a developer audit of the **converted package**, not certification by the KCD2 runtime. '
        'A checked combination below has exact native role/gender/layer matches, no reported slot/archetype conflicts, '
        'and no findings from the enabled bind-pose geometry checks. It was not tested in native animation or cloth physics.','',
        f"Package signature: `{summary['signature']}`.",
        'Native rule-table hashes:','',
        *[f"- `{row['member']}`: `{row['sha256']}`." for row in summary['rule_evidence']],'',
        '## Completed checks','',
        f'- [x] Enumerated all {garment_count:,} registered garments and all {pair_count:,} same-gender pairs.',
        '- [x] Inspected every existing converted character preset on its own body.',
        f"- [x] Enumerated all {full['total']:,} {full['gender'].lower()} layer selections on the named representative body.",
        f"- [x] Ran geometry on {full['counts']['geometry_runs']:,} table-compatible full {full['gender'].lower()} selections.",
        '- [x] Counted the male full-layer registration space exactly using compressed constraint states.',
        '- [x] Fixed missing native VCloth layer inheritance and unsupported upper-body region partitions; retested the isolated candidate.',
        '- [x] Added regression checks requiring converted UV alpha even when a source opacity cache exists.',
        '- [x] Excluded unused partition vertices from geometry findings and distinguished native masks from private outfit masks.',
        '- [x] Applied native `body_layer.xml` ordering instead of comparing layer IDs numerically; reran the matrix.',
        '- [ ] Rebuild existing garment/body hiding buffers using the opacity fix. The layer candidate does not contain that rebuild.',
        f"- [ ] Resolve the {len(repair['unresolved'])} item tables without a supported native region repair.",
        '- [ ] Resolve the remaining dress/archetype, mask compatibility, and geometric review findings.',
        '- [ ] Test all male full-outfit geometry, all body variants, all LODs and animated poses.',
        '- [ ] Verify clothing selection, rendering and cloth physics inside KCD2.','',
        '## Matrix results','',
        '| Gender | Garments | Pairs enumerated | Pairs receiving geometry checks | NPC presets |',
        '| --- | ---: | ---: | ---: | ---: |']
    for gender,data in summary['genders'].items():
        c=data['counts']
        lines.append(f"| {gender} | {c['singles']:,} | {c['pairs']:,} | {c.get('pair_geometry_runs',0):,} | {c['presets']} |")
    lines.extend(['','Pairs failing the registration policy are recorded as rejected or needing review; they are not rendered as valid outfits. '
        'Singles and pairs use one explicitly recorded representative body per gender. Presets use their own bodies.','',
        '## Confirmed by the enabled checks','',
        f"**{len(unique):,} distinct clothed selections** passed both the table contract and the enabled geometry diagnostics. "
        f"The separate {len(baselines)} unclothed baseline record(s) are excluded from this count.",
        f"The complete checkbox-equivalent list, with exact selections, is [{listing.name}]({listing.name}). "
        'A role name alone is not a confirmation: different items using that role can have different geometry and masks.','',
        '| Checked | Gender | Body / source actor | Clothing roles | Exact case |',
        '| --- | --- | --- | --- | --- |'])
    selected=sorted(unique.values(),key=lambda r:(not r['case'].startswith('preset:'),r['gender'],r['case']))
    for row in selected[:40]:
        roles=', '.join(parts[i]['attributes'].get('ArmorType','fallback') for i in row['selected'] if parts[i]['kind']=='Clothing')
        lines.append(f"| [x] | {row['gender']} | {presets[row['body']]['label']} | {roles} | `{row['case']}` |")
    if len(selected)>40:lines.extend(['',f'The table shows 40 cases; the CSV contains all {len(selected):,}.'])
    lines.extend(['','## Exact full-space counts — registration only','',
        'These are exact algebraic counts of the listed constraints, not individually rendered outfits. '
        'They exclude geometry, body-dependent private masks, native equip arbitration, and any additional engine exclusions. '
        'Passing every pair does not prove a complete outfit works.','',
        '| Gender | Full Cartesian space | Pass listed registration constraints |',
        '| --- | ---: | ---: |'])
    for gender,data in summary['genders'].items():
        space=data['full_layer_space']
        lines.append(f"| {gender} | {space['cartesian_total']:,} | {space['registration_constraints_pass']:,} |")
    lines.extend(['','## Repaired registrations','',
        f"The isolated overlay repairs **{len(repair['corrections'])} components**. The installed package is unchanged. "
        'Region joins retain all source triangles and material bindings. The converter now applies the same native-layer policy to future builds.','',
        '| Component | Native role | Correction |','| --- | --- | --- |'])
    for row in repair['corrections']:
        description='; '.join((c['region']+' inherits layer '+c['layer']) if c['kind']=='inherited_layer'
                             else 'Recombined '+', '.join(c['removed_regions'])+f" into torso; {c['after_triangles']} triangles retained"
                             for c in row['changes'])
        lines.append(f"| `{row['component']}` | {row['role']} | {description} |")
    lines.extend(['','Unresolved source item tables:',''])
    lines.extend('- `'+r['table']+'`: '+r['error'] for r in repair['unresolved'])
    if 'Source soul audit' in extras:
        path,data=extras['Source soul audit']
        lines.extend(['','## KCD1 source coverage','',
            f"Enumerated {data['source_records']:,} shared KCD1 soul records. "
            'Only records with an existing converted character preset can receive converted-geometry checks.',
            '', '| Result | Source records |','| --- | ---: |',
            *[f'| {status} | {count:,} |' for status,count in data['counts'].items()],
            '',f'Source evidence: `{Path(path).as_posix()}`. Unconverted records are not confirmed clothing combinations.'])
    if 'Rendered examples' in extras:
        path,data=extras['Rendered examples']
        lines.extend(['','## Developer renderer examples','',
            'These actual packaged outfits were opened in the standalone WebGL workbench and captured from front, back, '
            'and side, plus the masked/unmasked comparison. Captures are visual evidence for these cases only; '
            'they do not certify every matrix row or native KCD2 rendering.',''])
        for row in data['cases']:
            lines.append(f"- `{row['actor']}`: {row['status']} Captures: `{Path(path).parent.as_posix()}/{row['views'][0]}`.")
    lines.extend(['','## Evidence and reproduction','',
        f'- Detailed pair/preset cases: `{matrix.as_posix()}/cases.jsonl`.',
        f'- Complete matrix checklist: `{matrix.as_posix()}/checklist.csv`.',
        f'- Full female case stream: `{full_layers.as_posix()}/cases.jsonl.gz`.',
        f'- Isolated candidate provenance: `{repairs.as_posix()}/repair.json`.',
        '- Developer commands and limits: [Clothing & Body Test](../tools/clothing_lab/README.md).','',
        'The raw reports and candidate meshes stay in ignored local `reports/`; only this checklist, its confirmed-selection CSV, '
        'and source code are suitable for the repository. No copyrighted game assets are included in this report.',''])
    output.write_text('\n'.join(lines),encoding='utf-8')
    return dict(report=str(output),confirmed_csv=str(listing),confirmed_clothed=len(unique))
