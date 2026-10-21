"""Read-only comparison of a native terrain archive with the surface insertion policy."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

from compiled_terrain import parse
from terrain_object_tree import (DEFAULT_POLICY, SURFACES, bounds, destination,
                                 maximum_view_distance, read_tree)
from upgrade_map import read


def audit(archive):
    with zipfile.ZipFile(archive) as source:
        blob = read(source, 'terrain/terrain.dat')
    root, nodes = read_tree(parse(blob))
    counts = {str(k): dict(total=0, matching=0, differences=0) for k in sorted(SURFACES)}
    mismatch_ratios = Counter()
    examples = []
    def visit(node, path=()):
        for kind, record in node.records:
            if kind not in SURFACES:
                continue
            predicted = destination(root.box, bounds(record), maximum_view_distance(record))
            row = counts[str(kind)]
            row['total'] += 1
            row['matching' if predicted == path else 'differences'] += 1
            if predicted != path:
                mismatch_ratios[f'{kind}:{record[42]}'] += 1
                if len(examples) < 10:
                    examples.append(dict(kind=kind, bounds=bounds(record), native_path=path,
                        predicted_path=predicted, view_byte=record[42]))
        for bit, child in node.children.items():
            visit(child, path+(bit,))
    visit(root)
    return dict(archive=str(archive), terrain_sha256=hashlib.sha256(blob).hexdigest(),
        nodes=len(nodes), policy=vars(DEFAULT_POLICY), records=counts,
        difference_view_bytes=dict(mismatch_ratios), examples=examples, runtime_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(audit(args.archive), indent=2)
    if args.output:
        args.output.write_text(result+'\n', encoding='utf-8')
    print(result)
