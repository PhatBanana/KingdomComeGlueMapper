"""Per-family texture analysis shared by the package audit and the retail baseline."""
from . import dds


def prefix_of(key):
    return key.split('/', 1)[0] if '/' in key else ''


def analyze(archives):
    """Yield one record per DDS family mounted in ``archives`` (stream pieces, header, problems)."""
    for base, parts in dds.families(archives.keys()).items():
        sizes = {suffix: archives.size(key) for suffix, key in parts.items()}
        record = dict(base=base, prefix=prefix_of(base), slot=dds.slot_class(base), sizes=sizes,
                      pak=archives.pak_of(parts[''] if '' in parts else next(iter(parts.values()))),
                      info=None, error=None, problems=[], piece_bytes=max(sizes.values()),
                      piece_member=max(sizes, key=sizes.get))
        if '' not in parts:
            record['problems'].append(('error', 'dds_orphan_parts', f'{base}: streamed parts without a base .dds'))
            yield record
            continue
        try:
            info = dds.parse_header(archives.read_head(base, 148))
        except dds.Malformed as exc:
            record['error'] = (exc.code, str(exc))
            record['problems'].append(('error', exc.code, f'{base}: {exc}'))
            yield record
            continue
        record['info'] = info
        if 'unsupported' not in info:
            numeric = {k: v for k, v in sizes.items() if k.isdigit()}
            tail = archives.read_tail(base, 8) if sizes[''] > info['header'] else b''
            record['problems'] += dds.family_problems(info, sizes[''], tail, numeric, base)
            alpha_parts = {k[:-1]: v for k, v in sizes.items() if k.endswith('a') and k[:-1].isdigit()}
            if alpha_parts and 'a' not in sizes:
                record['problems'].append(('error', 'dds_alpha_base_missing', f'{base}: alpha mips without .a base'))
            record['implied_bytes'] = dds.implied_piece(info, sizes[''])
            if record['implied_bytes'] > record['piece_bytes']:
                record['piece_bytes'], record['piece_member'] = record['implied_bytes'], 'header'
        yield record
