"""Publish source job ownership alongside fresh and resumed gameplay builds."""
import json
from pathlib import Path

from upgrade_map import digest

RECORD = 'source-work-coverage.json'


def upgrade(package, source, target=None):
    from source_work_coverage import audit
    from setup_gameplay import STATIC_WORLD_PROFILES
    if source is None:
        raise ValueError('KCD1 source is required to audit source job ownership')
    package = Path(package)
    report = audit(Path(source), STATIC_WORLD_PROFILES)
    payload = (json.dumps(report, indent=2) + '\n').encode('utf-8')
    path = package / RECORD
    if not path.exists() or path.read_bytes() != payload:
        # Resume inputs can be hard linked to the user's verified saved build.
        # Never write through those links or modify gameplay during this audit.
        pending = path.with_suffix('.json.pending')
        pending.write_bytes(payload)
        pending.replace(path)
    return {RECORD: digest(path)}, dict(version=report['version'], record=RECORD,
        profiles=report['selected_profiles'], actors=report['actor_count'],
        assignments=len(report['assignments']), ownership=report['ownership_counts'],
        runtime_verified=False)
