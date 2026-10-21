"""Export an existing GlueMapper conversion; this does not convert either game."""
from __future__ import annotations

from dataclasses import dataclass
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tomllib
import xml.etree.ElementTree as ET
import zipfile

from .archive import (BridgeError, RETAIL_PAK_LIMIT, asset_allowed, checked_infos,
                      copy_file, extract_runtime, metadata_entry, rewrite_assets,
                      safe_name, sha256, write_member, xml_bytes)
from .scene import prepare_scene, transform_level_entry

MOD_ID = "gluemapperkcdmp"
LEVEL = "kcd1_travel"
LEVEL_ID = 1001
SOURCE_COMMIT = "80afe68572c2d0690c97b4ea0ae0e6dc5f87a301"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "kcdmp-map-receipt.json"


@dataclass
class BuildOptions:
    game: Path
    client: Path
    server: Path
    output: Path
    source_mod: Path | None = None
    spawn: tuple[float, float, float] | None = None
    yaw: float | None = None
    player_name: str = "SamGCoder"
    host: str = "127.0.0.1:7777"
    standalone: bool = True
    portable_runtime: bool = False


def json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def xml(data: ET.Element) -> bytes:
    return ET.tostring(data, encoding="utf-8", xml_declaration=True)


def evidence() -> dict:
    return json.loads((PROJECT_ROOT / "evidence/inspected-packages.json").read_text(encoding="utf-8"))


def inside(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def unredirected(path: Path) -> Path:
    raw = path.expanduser().absolute()
    if raw.resolve() != raw:
        raise BridgeError(f"Choose a real path without symlinks/junctions or '..': {raw}")
    return raw


def check_distribution(path: Path, kind: str) -> dict:
    path = unredirected(path)
    name = "KcdMp-0.44.0-win-x64.zip" if kind == "client" else "KcdMp-server-0.44.0.zip"
    expected = evidence()[name]
    if path.is_file():
        actual = sha256(path)
        if actual != expected["sha256"]:
            raise BridgeError(f"{kind} ZIP differs from the inspected KCDMP 0.44.0 release. Select the original supplied ZIP. No binary patch was applied.")
        return {"kind": kind, "source": str(path), "zip": True, "sha256": actual}
    if not path.is_dir():
        raise BridgeError(f"Missing {kind} directory or ZIP: {path}")
    if kind == "server" and (path / "windows/KcdMp.Server.exe").is_file():
        path /= "windows"
    checked = {}
    for filename, entry in expected["binaries"].items():
        local_name = filename.removeprefix("windows/")
        file = path / local_name
        if not file.is_file() or file.stat().st_size != entry["bytes"] or sha256(file) != entry["sha256"]:
            raise BridgeError(f"Unexpected {kind} binary: {file}. This project is pinned to the supplied 0.44.0 build.")
        checked[local_name] = entry["sha256"]
    if kind == "client":
        build_file = path / "builds.json"
        if not build_file.is_file() or sha256(build_file) != "1cf020645f91900596047713e3905f13b3688741e3ec1af5fcd1d03aaa43e2ec":
            raise BridgeError("The client's builds.json differs from the inspected 0.44.0 build table.")
    elif not (path / "KcdMp.Server.exe").is_file():
        raise BridgeError("Select the Windows server distribution containing KcdMp.Server.exe.")
    return {"kind": kind, "source": str(path), "zip": False, "binaries": checked}


def inspect_game(game: Path) -> dict:
    game = unredirected(game)
    config = game / "system.cfg"
    if not config.is_file():
        raise BridgeError("Select the retail KCD2 root containing system.cfg, Data, and Bin.")
    version = re.search(r'^\s*wh_sys_version\s*=\s*["\']?([^\s"\']+)', config.read_text(encoding="utf-8-sig"), re.M | re.I)
    if not version or version[1] != "1.5.6":
        raise BridgeError("The supplied KCDMP build requires retail KCD2 1.5.6. A development build is not interchangeable.")
    for name in ("Data/Tables.pak", "Data/Scripts.pak"):
        if not (game / name).is_file():
            raise BridgeError(f"Incomplete retail game installation: missing {name}")
    # Match the launcher's actual directory selection. Finding some supported
    # DLL in a backup/development folder must never certify a different engine.
    ms_config = game / "MicrosoftGame.Config"
    msstore = False
    if ms_config.is_file() and (game / "KingdomCome.exe").is_file():
        raw_config = ms_config.read_bytes()
        text = raw_config.decode("utf-16" if raw_config.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        msstore = "DeepSilver.77536C3FE941" in text
    binary_directory = game if msstore else game / "Bin/Win64MasterMasterSteamPGO"
    executable = unredirected(binary_directory / "KingdomCome.exe")
    candidate = unredirected(binary_directory / "WHGame.dll")
    if not executable.is_file() or not candidate.is_file():
        raise BridgeError(f"The launcher's retail executable/DLL is missing in {binary_directory}. For Microsoft Store select its Content root beside MicrosoftGame.Config.")
    store = "msstore" if msstore else "steam"
    builds = evidence()["KcdMp-0.44.0-win-x64.zip"]["supported_builds"]
    possible = [b for b in builds if b["store"] == store and b["whgame"]["size"] == candidate.stat().st_size]
    digest = sha256(candidate) if possible else None
    matches = [{"path": str(candidate), "build_id": b["id"], "sha256": digest}
               for b in possible if digest == b["whgame"]["sha256"]]
    if not matches:
        raise BridgeError("No retail WHGame.dll matches the Steam/Microsoft Store 1.5.6 builds in KCDMP 0.44.0. Restore the matching retail build; skipping a version check does not fix incompatible hooks.")
    return {"root": str(game), "version": version[1], "store": store,
            "executable": str(executable), "matching_builds": matches}


def source_paths(options: BuildOptions) -> tuple[Path, Path]:
    source = unredirected(options.source_mod or options.game / "Mods/kingdomcomegluemapper")
    manifest = source / "mod.manifest"
    if not manifest.is_file() or ET.parse(manifest).findtext("./info/modid") != "kingdomcomegluemapper":
        raise BridgeError("Select the complete kingdomcomegluemapper mod/package generated by GlueMapper.")
    level = source / "Data/Levels" / LEVEL
    for name in ("level.pak", "terrain.pak"):
        if not (level / name).is_file():
            raise BridgeError(f"Missing {level / name}. Build/install the combined GlueMapper world first; a Git checkout alone contains no map assets.")
    for p in source.rglob("*"):
        if p.is_symlink() or p.resolve() != p:
            raise BridgeError(f"Redirected source file: {p}")
    return source, level


def selected_level_registration(source: Path, game: Path) -> bytes:
    rows = []
    for path in sorted((source / "Data").glob("*.pak")):
        with zipfile.ZipFile(path) as pak:
            for info in checked_infos(pak):
                if re.fullmatch(r"libs/tables/level__[^/]+\.xml", info.filename.replace("\\", "/").lower()):
                    doc = ET.fromstring(xml_bytes(pak, info))
                    for row in doc.findall("./levels/LevelData"):
                        if row.get("LevelName", "").lower() == LEVEL:
                            rows.append((doc, copy.deepcopy(row)))
    if not rows:
        raise BridgeError("The source package does not register kcd1_travel in a root Data PAK.")
    chosen = rows[-1]
    if any(row.attrib != chosen[1].attrib for _, row in rows):
        raise BridgeError("Conflicting kcd1_travel registration rows in source PAKs; rebuild a consistent GlueMapper package.")
    if chosen[1].get("LevelId") != str(LEVEL_ID):
        raise BridgeError("Unexpected kcd1_travel level ID; this bridge expects GlueMapper LevelId 1001.")
    with zipfile.ZipFile(game / "Data/Tables.pak") as pak:
        info = next((i for i in checked_infos(pak) if i.filename.lower() == "libs/tables/level.xml"), None)
        if info is None:
            raise BridgeError("Retail Tables.pak has no level registry.")
        native = ET.fromstring(xml_bytes(pak, info))
        if any(r.get("LevelId") == str(LEVEL_ID) or r.get("LevelName", "").lower() == LEVEL for r in native.findall("./levels/LevelData")):
            raise BridgeError("The custom level collides with the game's native level registry.")
    root = ET.Element(chosen[0].tag, chosen[0].attrib)
    container = chosen[0].find("levels")
    ET.SubElement(root, "levels", container.attrib).append(chosen[1])
    return xml(root)


def scene_context(level: Path, options: BuildOptions):
    with zipfile.ZipFile(level / "level.pak") as pak:
        checked_infos(pak)
        return prepare_scene(pak, spawn=options.spawn, heading=options.yaw)


def inspect(options: BuildOptions) -> dict:
    options.game = unredirected(options.game)
    game = inspect_game(options.game)
    source, level = source_paths(options)
    client, server = check_distribution(options.client, "client"), check_distribution(options.server, "server")
    out = unredirected(options.output)
    for path in (options.game.resolve(), source, Path(client["source"]), Path(server["source"])):
        if inside(out, path) or inside(path, out):
            raise BridgeError("Choose a fresh output folder outside the game, source conversion, and KCDMP distribution folders.")
    for runtime in (Path(client["source"]), Path(server["source"])):
        if inside(runtime, options.game.resolve() / "Mods"):
            raise BridgeError("KCDMP must be stored outside the game's Mods folder.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", options.player_name):
        raise BridgeError("Use a player name of 1-32 letters, numbers, underscores, dots or hyphens.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+:[0-9]{1,5}", options.host) or not 1 <= int(options.host.rsplit(":", 1)[1]) <= 65535:
        raise BridgeError("Server address must be host:port, for example 127.0.0.1:7777.")
    ctx = scene_context(level, options)
    selected_level_registration(source, options.game)
    candidates = [*sorted((source / "Data").glob("*.pak")), *sorted(level.rglob("*.pak"))]
    source_size = sum(p.stat().st_size for p in candidates)
    estimated = 0
    for path in candidates:
        with zipfile.ZipFile(path) as pak:
            infos = checked_infos(pak)
            if path.parent == source / "Data":
                keep = [i for i in infos if asset_allowed(i.filename)]
                if len(keep) == len(infos):
                    estimated += path.stat().st_size
                else:
                    estimated += sum(i.file_size + 128 + 2 * len(i.filename.encode("utf-8")) for i in keep)
            elif path == level / "level.pak":
                estimated += sum(i.file_size + 128 + 2 * len(i.filename.encode("utf-8")) for i in infos)
            else:
                estimated += path.stat().st_size
    return {"game": game, "source_mod": str(source), "level": str(level), "client": client, "server": server,
            "spawn": {"xyz": list(ctx.spawn_xyz), "yaw_degrees": ctx.heading},
            "source_data_bytes": source_size, "estimated_output_bytes": estimated,
            "output": str(out), "runtime_verified": False,
            "scope": "Converted scenery and multiplayer player spawn; no campaign integration."}


def build_level(source: Path, destination: Path, ctx) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    report = {"copied_archives": [], "changed_entries": [], "removed_entries": []}
    with zipfile.ZipFile(source / "level.pak") as pak, zipfile.ZipFile(destination / "level.pak", "x", zipfile.ZIP_STORED, allowZip64=False) as out:
        for info in checked_infos(pak):
            key = safe_name(info.filename).lower()
            if key.startswith(("scripts/", "quests/")) or Path(key).suffix in {".lua", ".luac", ".gfx"}:
                report["removed_entries"].append(info.filename)
                continue
            # Scene transforms also handle compiled trigger/profile metadata.
            if key in ctx.replacements or metadata_entry(key) or key == "triggerareas.fubar":
                data = xml_bytes(pak, info)
                revised = transform_level_entry(info.filename, data, ctx)
                if revised is None:
                    report["removed_entries"].append(info.filename)
                    continue
                if revised != data:
                    report["changed_entries"].append(info.filename)
                write_member(out, pak, info, replacement=revised)
            else:
                write_member(out, pak, info)
    if (destination / "level.pak").stat().st_size >= RETAIL_PAK_LIMIT:
        raise BridgeError("Cleaned level.pak exceeds the retail archive size limit.")
    with zipfile.ZipFile(destination / "level.pak") as pak:
        infos = {i.filename.lower(): i for i in checked_infos(pak)}
        for name in ("levelinfo.xml", "leveldata.xml", "objects_mission0.xml", "mission_mission0.xml"):
            if name not in infos:
                raise BridgeError(f"Cleaned map is missing {name}")
        (destination / "levelinfo.xml").write_bytes(pak.read(infos["levelinfo.xml"]))
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pak" or path == source / "level.pak":
            continue
        relative = path.relative_to(source)
        with zipfile.ZipFile(path) as pak:
            for info in checked_infos(pak):
                key = safe_name(info.filename).lower()
                if metadata_entry(key) or key.startswith(("scripts/", "quests/")) or Path(key).suffix in {".lua", ".luac"}:
                    raise BridgeError(f"Unexpected gameplay metadata in auxiliary PAK {relative}: {key}. Merge it into level.pak before export.")
        if path.stat().st_size >= RETAIL_PAK_LIMIT:
            raise BridgeError(f"Source PAK exceeds the retail limit: {path}")
        copy_file(path, destination / relative)
        report["copied_archives"].append(relative.as_posix())
    return report


def make_manifest(destination: Path) -> None:
    root = ET.Element("kcd_mod")
    info = ET.SubElement(root, "info")
    for key, value in {"name": "KCD1:MP", "modid": MOD_ID, "author": "SamG-Coder",
                       "version": "0.1.0", "description": "KCD1 scenery for the KCDMP 0.44.0 map-load test."}.items():
        ET.SubElement(info, key).text = value
    (destination / "mod.manifest").write_bytes(xml(root))


def make_registration(destination: Path, level_data: bytes) -> None:
    level_file = destination / "Data/Levels" / LEVEL / "level.pak"
    with zipfile.ZipFile(destination / "Data/zzz_gluemapperkcdmp_registration.pak", "x", zipfile.ZIP_STORED, allowZip64=False) as out:
        out.writestr(f"Libs/Tables/level__{MOD_ID}.xml", level_data)
        # Retail prefixes the discovered custom level path while loading its database.
        with zipfile.ZipFile(level_file) as level:
            for info in checked_infos(level):
                if info.filename.lower().startswith("tables/"):
                    out.writestr(f"Mods/{MOD_ID}/Data/Levels/{LEVEL}/{safe_name(info.filename)}", xml_bytes(level, info))


def materialize_runtime(record: dict, output: Path) -> Path:
    source = Path(record["source"])
    if not record["zip"]:
        return source
    destination = output / "runtime" / record["kind"]
    return extract_runtime(source, destination, windows_server=record["kind"] == "server")


def copy_tool(output: Path) -> None:
    dest = output / "bridge_tool"
    dest.mkdir()
    shutil.copy2(PROJECT_ROOT / "patch.py", dest / "patch.py")
    for folder in ("kcdmp_bridge", "templates", "evidence"):
        shutil.copytree(PROJECT_ROOT / folder, dest / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def windows_script(output: Path, name: str, arguments: str) -> None:
    text = ('@echo off\nsetlocal DisableDelayedExpansion\n'
            'where py >nul 2>nul\nif errorlevel 1 (\n'
            f'  python "%~dp0bridge_tool\\patch.py" {arguments}\n'
            ') else (\n'
            f'  py -3 "%~dp0bridge_tool\\patch.py" {arguments}\n'
            ')\nset "bridge_exit=%errorlevel%"\nif not "%bridge_exit%"=="0" pause\nexit /b %bridge_exit%\n')
    (output / name).write_bytes(text.replace("\n", "\r\n").encode("ascii"))


def build(options: BuildOptions, progress=print, *, upgrade_level=None) -> dict:
    progress("Checking game build, source conversion and the supplied KCDMP release...")
    plan = inspect(options)
    output = Path(plan["output"])
    if output.exists():
        raise BridgeError("Output already exists. Choose a fresh folder so previous exports are preserved.")
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    needed = plan["estimated_output_bytes"] + 512 * 1024 ** 2
    if shutil.disk_usage(parent).free < needed:
        raise BridgeError(f"Not enough output space. Allow approximately {needed / 1024 ** 3:.1f} GiB for this snapshot.")
    output.mkdir()
    try:
        source, level = Path(plan["source_mod"]), Path(plan["level"])
        ctx = scene_context(level, options)
        mod = output / "client_mod" / MOD_ID
        (mod / "Data").mkdir(parents=True)
        progress("Cleaning campaign entities and retaining converted map rendering...")
        level_report = build_level(level, mod / "Data/Levels" / LEVEL, ctx)
        if upgrade_level is not None:
            level_report['surface_placement'] = upgrade_level(mod, LEVEL)
        reports = []
        root_paks = sorted((source / "Data").glob("*.pak"))
        for n, path in enumerate(root_paks, 1):
            progress(f"Assets {n}/{len(root_paks)}: {path.name}")
            reports.append(rewrite_assets(path, mod / "Data" / path.name))
        # Installed release packages use root PAKs. Do not silently omit loose dev assets.
        loose_assets = [p.relative_to(source / "Data").as_posix() for p in (source / "Data").rglob("*")
                        if p.is_file() and not p.is_relative_to(source / "Data/Levels") and p.parent != source / "Data"]
        if loose_assets:
            raise BridgeError("This input contains loose development assets. Use GlueMapper's combined install/package output; first example: " + loose_assets[0])
        make_registration(mod, selected_level_registration(source, options.game))
        make_manifest(mod)
        # The setup launcher mounts these outside Data, in its private Engine
        # view. They must travel with the exported map and enter its receipt.
        if (source / "ShaderCache").is_dir():
            progress("Reusing the completed map's compiled shaders...")
            shutil.copytree(source / "ShaderCache", mod / "ShaderCache")
        progress("Preparing the isolated server profile and launch commands...")
        client = materialize_runtime(plan["client"], output)
        server = materialize_runtime(plan["server"], output)
        if options.portable_runtime:
            for kind, location in (("client", client), ("server", server)):
                destination = output / "runtime" / kind
                if location != destination:
                    shutil.copytree(location, destination)
                if kind == "client": client = destination
                else: server = destination
        server_profile = output / "server-profile"
        (server_profile / "gamemodes").mkdir(parents=True)
        numbers = dict(zip(("X", "Y", "Z", "YAW"), (*ctx.spawn_xyz, ctx.heading)))
        for source_name, target_name in (("server.toml.template", "server.kcd1-map-only.toml"),
                                         ("kcd1_map_only.lua.template", "gamemodes/kcd1_map_only.lua")):
            text = (PROJECT_ROOT / "templates" / source_name).read_text(encoding="utf-8")
            for key, value in numbers.items():
                if not math.isfinite(value):
                    raise BridgeError("Spawn values must be finite.")
                text = text.replace(f"@@SPAWN_{key}@@", format(value, ".9g"))
            if "@@" in text:
                raise BridgeError("Unresolved template placeholder.")
            if target_name.endswith(".toml"):
                text = text.replace("\nport = 7777\n", f"\nport = {int(options.host.rsplit(':', 1)[1])}\n", 1)
                tomllib.loads(text)
            (server_profile / target_name).write_text(text, encoding="utf-8")
        report = {"schema": 1, "owner": MOD_ID, "created_utc": datetime.now(timezone.utc).isoformat(),
                  "gluemapper_commit_inspected": SOURCE_COMMIT, "level": LEVEL, "level_id": LEVEL_ID,
                  "source": plan, "scene": ctx.report, "level_package": level_report, "asset_archives": reports,
                  "runtime_verified": False, "verification": "Static format/API checks only; a real client must reach KcdMp_ready and OnPlayerSpawn."}
        progress("Recording file hashes for rollback and verification...")
        report["files"] = {p.relative_to(mod).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                           for p in sorted(mod.rglob("*")) if p.is_file()}
        json_write(mod / RECEIPT, report)
        profile = {"schema": 1, "owner": MOD_ID, "game": str(options.game.resolve()), "mod": str(mod),
                   "output": str(output), "client": str(client), "server": str(server), "server_profile": str(server_profile),
                   "spawn": {"xyz": list(ctx.spawn_xyz), "yaw_degrees": ctx.heading},
                   "name": options.player_name, "host": options.host, "level": LEVEL,
                   "runtime_verified": False}
        json_write(output / "profile.json", profile)
        json_write(output / "build-report.json", report)
        if not options.standalone:
            progress("KCD1:MP package ready. Manage activation and launching from setup.")
            return profile
        copy_tool(output)
        for filename, arguments in {
            "1_ACTIVATE_MAP.cmd": 'activate --profile "%~dp0profile.json"',
            "2_START_SERVER.cmd": 'launch --profile "%~dp0profile.json" --kind server',
            "3_JOIN_LOCAL_SERVER.cmd": 'launch --profile "%~dp0profile.json" --kind client',
            "OFFLINE_MAP_TEST.cmd": 'launch --profile "%~dp0profile.json" --kind offline',
            "RESTORE_MODS.cmd": 'restore --profile "%~dp0profile.json"',
            "VERIFY_PROFILE.cmd": 'verify --profile "%~dp0profile.json"',
        }.items():
            windows_script(output, filename, arguments)
        (output / "START_HERE.txt").write_text(
            "1. Close KCD2. Run 1_ACTIVATE_MAP.cmd. It saves your old mod order and enables only this test map.\n"
            "2. Run 2_START_SERVER.cmd. The Windows server needs the .NET 10 x64 runtime.\n"
            "3. Leave the server running. Run 3_JOIN_LOCAL_SERVER.cmd. Steam must be running for Steam KCD2.\n"
            "4. Look for the server log '<name> spawned on kcd1_travel'. Use /where and /spawn in game.\n"
            "5. Close KCD2 and run RESTORE_MODS.cmd to restore the exact previous mod order.\n\n"
            "OFFLINE_MAP_TEST.cmd isolates client map loading if joining fails. It still uses the KCDMP client.\n"
            "This is an experimental scenery export. Runtime loading/rendering has not been verified here.\n"
            "All players need their own converted map. No game files are supplied by this project.\n"
            "The unlisted server still listens on network interfaces; master registration is disabled.\n"
            "Keep this output folder while using the profile. build-report.json lists retained/removed content.\n", encoding="utf-8")
        progress(f"Built {output}. Run 1_ACTIVATE_MAP.cmd to install the isolated map profile.")
        return profile
    except BaseException as error:
        json_write(output / "BUILD_FAILED.json", {"error": str(error), "game_modified": False,
                                                  "next_step": "Source/game files were not changed. Choose a fresh output after resolving the error."})
        raise
