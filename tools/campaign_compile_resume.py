"""A persistent, bounded work directory for campaign_compile (fork: skalitz-finish).

campaign_compile builds in a temporary directory and loses everything when it
stops. With `--work <dir>` it builds in that directory instead and, on the
next run with the same directory, reuses the two expensive products whose
inputs are fixed:

    stage/source-ir/<quest>.json     the imported quest IR, when its request
                                     key (quest, entry files, level, actor
                                     roots, person brains) is unchanged
    stage/person-assets/<person>/    a converted person, when its build
                                     finished (a marker beside the directory
                                     holds the builder's result)

Everything else is recomputed, so adapter state is never skipped. In a work
run the quest IR always goes through its JSON form, fresh or reused, so a
resumed run and an uninterrupted one see the same models. Without `--work`
none of this code runs and campaign_compile behaves as before.

The directory is bounded: a person build is refused once the directory holds
more than the cap, and person assets are moved, not copied, into the output
fragments, after which stage/person-assets is removed.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

CAP_BYTES = 60 * 1024 ** 3
KEEP = ('source-ir', 'person-assets')


def size(path):
    return sum(f.stat().st_size for f in Path(path).rglob('*') if f.is_file())


@contextmanager
def work_directory(work, output):
    """Yield the build directory: a temporary one, or the persistent `work`."""
    if work is None:
        with tempfile.TemporaryDirectory(prefix='.campaign-convert-', dir=output.parent) as temporary:
            yield temporary
        return
    work = Path(work)
    stage = work / 'stage'
    stage.mkdir(parents=True, exist_ok=True)
    for entry in stage.iterdir():
        # Only the reusable products survive a restart; the rest is rebuilt.
        if entry.name not in KEEP:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    yield str(work)


def quest_model(stage, name, request, build):
    """Return the quest IR through its JSON form, reusing a stored one whose request matches."""
    path = Path(stage) / 'source-ir' / (name + '.json')
    key = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
    marker = path.with_suffix('.key')
    if path.is_file() and marker.is_file() and marker.read_text(encoding='utf-8') == key:
        return json.loads(path.read_text(encoding='utf-8')), True
    model = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    text = json.dumps(model, indent=2)
    path.write_text(text, encoding='utf-8')
    marker.write_text(key, encoding='utf-8')
    return json.loads(text), False


def appearance_builder(work, cap=CAP_BYTES, progress=None):
    """Wrap the person appearance builder: reuse a finished person, refuse to exceed the cap."""
    used = [size(work)]

    def build(source, target, person, namespace, destination):
        from character_person_appearance import build_appearance
        destination = Path(destination)
        marker = destination.with_name(destination.name + '.done.json')
        if marker.is_file() and destination.is_dir():
            if progress:
                progress('Reusing converted person', 0, 0, namespace)
            return json.loads(marker.read_text(encoding='utf-8'))
        marker.unlink(missing_ok=True)
        if destination.exists():
            shutil.rmtree(destination)  # an interrupted build
        if used[0] > cap:
            raise RuntimeError('Campaign work directory is over its %d GB cap' % (cap // 1024 ** 3))
        character = build_appearance(source, target, person, namespace, destination)
        used[0] += size(destination)
        try:
            text = json.dumps(character)
        except TypeError:
            return character  # not storable: the person is rebuilt next time
        marker.write_text(text, encoding='utf-8')
        return json.loads(text)  # the form a later run will reuse
    return build


_moved = {}


def place(payload, path, stage):
    """Put a file payload into the output fragments; person assets are moved to keep the directory bounded."""
    people = Path(stage) / 'person-assets'
    payload = Path(payload)
    if people not in payload.parents:
        shutil.copyfile(payload, path)
    elif payload in _moved:
        shutil.copyfile(_moved[payload], path)  # one source file published under two names
    else:
        os.replace(payload, path)
        _moved[payload] = Path(path)


def release_people(stage):
    shutil.rmtree(Path(stage) / 'person-assets', ignore_errors=True)
