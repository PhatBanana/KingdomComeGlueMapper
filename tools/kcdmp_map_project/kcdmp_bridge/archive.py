"""Bounded, path-checked archive IO. No executable or game asset is run."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile


class BridgeError(ValueError):
    pass


RETAIL_PAK_LIMIT = 2 ** 31
SHARD_LIMIT = 1024 ** 3
EXECUTABLE_SUFFIXES = {".lua", ".luac", ".py", ".pyc", ".exe", ".dll", ".cmd", ".bat", ".ps1", ".vbs", ".js", ".nut", ".cfg"}


def safe_name(name: str) -> str:
    name = name.replace("\\", "/")
    parts = name.split("/")
    if (not name or name.startswith("/") or any(c in name for c in (":", "\x00", "\r", "\n"))
            or any(p in ("", ".", "..") or p.endswith((" ", ".")) for p in parts)
            or any(re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p, re.I) for p in parts)):
        raise BridgeError(f"Unsafe archive path: {name!r}")
    return name


def checked_infos(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    result, seen = [], set()
    for info in archive.infolist():
        if info.is_dir():
            safe_name(info.filename.rstrip("/"))
            continue
        name = safe_name(info.filename)
        key = name.lower()
        if key in seen:
            raise BridgeError(f"Ambiguous duplicate archive member: {name}")
        if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
            raise BridgeError(f"Symlink or encrypted archive member: {name}")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BridgeError(f"Unsupported compression for {name}")
        seen.add(key)
        result.append(info)
    return result


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def xml_bytes(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int = 128 * 1024 ** 2) -> bytes:
    if info.file_size > limit:
        raise BridgeError(f"Metadata is unexpectedly large: {info.filename}")
    return archive.read(info)


def copy_file(source: Path, target: Path, *, link: bool = False) -> str:
    """Optional links are used only for the bridge's own immutable snapshot."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise BridgeError(f"Refusing to overwrite: {target}")
    before = source.stat()
    if link:
        try:
            os.link(source, target)
            return sha256(target)
        except OSError:
            if target.exists():
                raise
    digest = hashlib.sha256()
    with source.open("rb") as inp, target.open("xb") as out:
        while chunk := inp.read(4 * 1024 ** 2):
            digest.update(chunk)
            out.write(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BridgeError(f"Source changed during export; rebuild after conversion finishes: {source}")
    return digest.hexdigest()


def asset_allowed(name: str) -> bool:
    """Keep rendering/audio resources; gameplay and frontend replacements stay out."""
    key = safe_name(name).lower()
    if PurePosixPath(key).suffix in EXECUTABLE_SUFFIXES:
        return False
    if key.startswith(("scripts/", "quests/", "mods/", "libs/tables/", "libs/storm/",
                       "gluemapper/campaignsource/", "localization/")):
        return False
    if key.startswith("libs/ui/"):
        return key.startswith("libs/ui/textures/")
    if key.startswith("levels/kcd1_travel/"):
        local = key[len("levels/kcd1_travel/"):]
        # Do not let a root PAK remount uncleaned metadata over the exported level.
        return (not metadata_entry(local) and local != "triggerareas.fubar"
                and not local.startswith(("scripts/", "quests/")) and not local.endswith(".pak"))
    root = key.split("/", 1)[0]
    return (root.startswith("glue") or root in {"objects", "textures", "materials", "animations", "sounds", "music", "shaders"}
            or key.startswith(("libs/particles/", "libs/gameaudio/", "libs/materials/", "libs/environmentpresets/")))


def metadata_entry(name: str) -> bool:
    key = name.replace("\\", "/").lower()
    return (key.startswith(("tables/", "whdata_", "layers/"))
            or bool(re.fullmatch(r"(?:objects_|mission_)mission\d+\.xml", key))
            or key in {"levelinfo.xml", "leveldata.xml", "leveldataaction.xml", "waitinglinks.xml",
                       "extractedlayerentityids.xml", "smartobjecthelpersetanimations.xml"})


def write_member(out: zipfile.ZipFile, source: zipfile.ZipFile, info: zipfile.ZipInfo, *, replacement: bytes | None = None) -> None:
    item = zipfile.ZipInfo(safe_name(info.filename), info.date_time)
    item.create_system = 0
    item.compress_type = zipfile.ZIP_STORED
    item.file_size = len(replacement) if replacement is not None else info.file_size
    with out.open(item, "w") as dst:
        if replacement is not None:
            dst.write(replacement)
        else:
            with source.open(info) as src:
                shutil.copyfileobj(src, dst, 1024 ** 2)


def rewrite_assets(source: Path, destination: Path) -> dict:
    """Keep original PAK filenames and ordering; filter mixed PAKs per member."""
    with zipfile.ZipFile(source) as archive:
        infos = checked_infos(archive)
        keep = [i for i in infos if asset_allowed(i.filename)]
        dropped = [i.filename for i in infos if not asset_allowed(i.filename)]
        report = {"source": source.name, "kept_entries": len(keep), "dropped_entries": dropped, "output": []}
        if not keep:
            return report
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Pure asset archives need no decompression/recompression and stay byte-identical.
        if len(keep) == len(infos) and source.stat().st_size < RETAIL_PAK_LIMIT and len(infos) < 65535:
            copy_file(source, destination)
            report["output"] = [destination.name]
            report["byte_identical"] = True
            return report
        groups: list[list[zipfile.ZipInfo]] = []
        size = 22
        for info in keep:
            cost = info.file_size + 128 + 2 * len(info.filename.encode("utf-8"))
            if cost > SHARD_LIMIT:
                raise BridgeError(f"Single asset is too large for a retail PAK: {info.filename}")
            if not groups or size + cost > SHARD_LIMIT or len(groups[-1]) >= 50000:
                groups.append([])
                size = 22
            groups[-1].append(info)
            size += cost
        for index, members in enumerate(groups):
            dest = destination if len(groups) == 1 else destination.with_name(f"{destination.stem}_kcdmp_{index:04d}.pak")
            with zipfile.ZipFile(dest, "x", zipfile.ZIP_STORED, allowZip64=False) as out:
                for info in members:
                    write_member(out, archive, info)
            with zipfile.ZipFile(dest) as check:
                actual = [(i.filename, i.file_size, i.CRC) for i in check.infolist()]
                expected = [(safe_name(i.filename), i.file_size, i.CRC) for i in members]
                if actual != expected:
                    raise BridgeError(f"Asset rewrite changed a payload: {dest}")
            if dest.stat().st_size >= RETAIL_PAK_LIMIT:
                raise BridgeError(f"Generated PAK exceeds retail limit: {dest}")
            report["output"].append(dest.name)
        report["byte_identical"] = False
        return report


def extract_runtime(source: Path, destination: Path, *, windows_server: bool = False) -> Path:
    """Extract the supplied distribution, never run it. Server ZIP has two OS roots."""
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(source) as archive:
        infos = checked_infos(archive)
        selected = []
        for info in infos:
            name = safe_name(info.filename)
            if windows_server:
                if not name.startswith("windows/"):
                    continue
                name = name[len("windows/"):]
            selected.append((info, name))
        if sum(i.file_size for i, _ in selected) > 1024 ** 3:
            raise BridgeError("Distribution expands beyond the inspected package limit.")
        for info, name in selected:
            target = destination.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 ** 2)
    return destination
