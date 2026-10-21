"""Reversible mod activation and argv-only process launch."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
import zipfile

from .archive import BridgeError, checked_infos, copy_file, safe_name, sha256
from .builder import LEVEL, MOD_ID, RECEIPT, check_distribution, inspect_game, unredirected


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_bytes(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def read_profile(path: Path) -> dict:
    path = unredirected(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema") != 1 or result.get("owner") != MOD_ID or result.get("level") != LEVEL:
        raise BridgeError("Not a generated GlueMapper KCDMP profile.")
    for key in ("game", "mod", "output", "client", "server", "server_profile"):
        unredirected(Path(result[key]))
    return result


def game_stopped() -> None:
    if os.name != "nt":
        return  # Tests perform filesystem-only activation on synthetic fixtures.
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KingdomCome.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise BridgeError("Unable to check whether KCD2 is running. Close it before activation/restoration.")
    if "kingdomcome.exe" in result.stdout.lower():
        raise BridgeError("Close KCD2 before changing its active mod profile.")


def check_mod(path: Path, *, full: bool = False) -> dict:
    path = unredirected(path)
    receipt_path = path / RECEIPT
    if not receipt_path.is_file():
        raise BridgeError("Generated mod receipt is missing; rebuild the profile.")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("owner") != MOD_ID or receipt.get("schema") != 1 or receipt.get("level") != LEVEL:
        raise BridgeError("Unrecognized map package receipt.")
    expected = receipt.get("files", {})
    if not expected or not isinstance(expected, dict):
        raise BridgeError("The map receipt has no files.")
    actual = set()
    for file in path.rglob("*"):
        if file.is_symlink() or file.resolve() != file:
            raise BridgeError(f"Redirected generated file: {file}")
        if file.is_file() and file != receipt_path:
            actual.add(file.relative_to(path).as_posix())
    if actual != set(expected):
        raise BridgeError("Generated package contents changed. Rebuild it, or preserve your edits separately.")
    core = {"mod.manifest", f"Data/Levels/{LEVEL}/level.pak", f"Data/Levels/{LEVEL}/levelinfo.xml",
            "Data/zzz_gluemapperkcdmp_registration.pak"}
    if not core <= set(expected):
        raise BridgeError("Generated map is missing a required core file.")
    for name, record in expected.items():
        safe_name(name)
        file = path / name
        if file.stat().st_size != record["bytes"]:
            raise BridgeError(f"Map file size changed: {name}")
        if full or name in core:
            if sha256(file) != record["sha256"]:
                raise BridgeError(f"Map file contents changed: {name}")
    if ET.parse(path / "mod.manifest").findtext("./info/modid") != MOD_ID:
        raise BridgeError("The manifest's mod ID does not match KCDMP's allow-list.")
    with zipfile.ZipFile(path / "Data/zzz_gluemapperkcdmp_registration.pak") as archive:
        checked_infos(archive)
        root = ET.fromstring(archive.read(f"Libs/Tables/level__{MOD_ID}.xml"))
        if root.find(f"./levels/LevelData[@LevelName='{LEVEL}'][@LevelId='1001']") is None:
            raise BridgeError("The map's level registration is missing.")
    return receipt


def state_paths(game: Path) -> tuple[Path, Path, Path]:
    game = unredirected(game)
    mods = unredirected(game / "Mods")
    unredirected(mods / MOD_ID)
    state = unredirected(game / ".gluemapper-kcdmp")
    unredirected(state / "active.json")
    order = unredirected(mods / "mod_order.txt")
    return mods, state, order


def activate(profile: dict, progress=print) -> dict:
    game_stopped()
    game = Path(profile["game"])
    inspect_game(game)
    source = Path(profile["mod"])
    receipt = check_mod(source)
    mods, state, order = state_paths(game)
    destination = mods / MOD_ID
    active_file = state / "active.json"
    if active_file.exists():
        raise BridgeError("A bridge activation already exists. Restore it before activating another export.")
    if destination.exists():
        raise BridgeError(f"{destination} already exists. Preserve or move it before activation; it will not be overwritten.")
    state.mkdir(parents=True, exist_ok=True)
    mods.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    stage = state / ("stage-" + token)
    stage.mkdir()
    record = {"schema": 1, "owner": MOD_ID, "token": token, "phase": "staging",
              "game": str(game), "destination": str(destination), "stage": str(stage),
              "profile_output": profile["output"], "receipt_sha256": sha256(source / RECEIPT),
              "order_existed": order.exists(),
              "old_order_b64": base64.b64encode(order.read_bytes()).decode("ascii") if order.exists() else "",
              "new_order_b64": base64.b64encode((MOD_ID + "\n").encode("utf-8")).decode("ascii")}
    atomic_json(active_file, record)
    try:
        for name in (*receipt["files"], RECEIPT):
            # Core/control files are copies. Large PAKs link only to our exported
            # snapshot, never the original single-player conversion.
            core_paks = {f"Data/Levels/{LEVEL}/level.pak", "Data/zzz_gluemapperkcdmp_registration.pak"}
            copy_file(source / name, stage / name, link=name.endswith(".pak") and name not in core_paks)
        check_mod(stage)
        game_stopped()
        # Do not overwrite mod-order edits made while the large package staged.
        if order.exists() != record["order_existed"] or (order.read_bytes() if order.exists() else b"") != base64.b64decode(record["old_order_b64"]):
            raise BridgeError("mod_order.txt changed while staging. No mod selection was replaced.")
        record["phase"] = "staged"
        atomic_json(active_file, record)
        if destination.exists():
            raise BridgeError("The destination appeared while staging. It will not be overwritten.")
        stage.rename(destination)
        record["phase"] = "installed"
        atomic_json(active_file, record)
        atomic_bytes(order, base64.b64decode(record["new_order_b64"]))
        record["phase"] = "active"
        atomic_json(active_file, record)
    except BaseException:
        # Keep a journal and every file. restore() can finish rollback after a
        # process interruption, a failed stage or a failed final mod-order write.
        progress("Activation did not finish. Original files were preserved; run RESTORE_MODS.cmd to roll back this journal.")
        raise
    progress("Map profile active. The previous mod order is saved; other installed mods are unchanged.")
    return record


def restore_game(game: Path, progress=print) -> dict:
    game_stopped()
    mods, state, order = state_paths(game)
    active_file = state / "active.json"
    if not active_file.is_file():
        raise BridgeError("No active bridge journal was found for this game.")
    record = json.loads(active_file.read_text(encoding="utf-8"))
    if record.get("owner") != MOD_ID or record.get("schema") != 1 or record.get("game") != str(game):
        raise BridgeError("Unrecognized activation journal.")
    token = record.get("token", "")
    if not token or any(c not in "0123456789abcdef" for c in token):
        raise BridgeError("Invalid activation journal token.")
    old = base64.b64decode(record["old_order_b64"], validate=True)
    new = base64.b64decode(record["new_order_b64"], validate=True)
    current = order.read_bytes() if order.exists() else b""
    # Recovery may find either side of the atomic order write.
    if current not in (old, new):
        raise BridgeError("mod_order.txt was edited after activation. Preserve/resolve those edits before restoring; the saved order will not overwrite them.")
    destination = mods / MOD_ID
    disabled = state / ("disabled-" + token)
    stage = state / ("stage-" + token)
    if destination.exists():
        if disabled.exists():
            raise BridgeError("Rollback destination already exists; preserve it and resolve the interrupted restore.")
        receipt = destination / RECEIPT
        if not receipt.is_file() or sha256(receipt) != record.get("receipt_sha256"):
            raise BridgeError("The destination no longer matches the installed map receipt. Preserve/resolve the replacement folder before restoring.")
        # Preserve even subsequently edited map files, by moving them out of Mods.
        destination.rename(disabled)
    if record["order_existed"]:
        atomic_bytes(order, old)
    elif order.exists():
        order.unlink()
    record["phase"] = "restored"
    record["restored_utc"] = datetime.now(timezone.utc).isoformat()
    record["preserved_map"] = str(disabled if disabled.exists() else stage)
    atomic_json(state / ("restored-" + token + ".json"), record)
    active_file.unlink()
    progress("Original mod order restored exactly. The generated test map was preserved outside Mods.")
    return record


def require_active(profile: dict) -> Path:
    mods, state, order = state_paths(Path(profile["game"]))
    journal_path = state / "active.json"
    if not journal_path.is_file():
        raise BridgeError("Run 1_ACTIVATE_MAP.cmd first.")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("owner") != MOD_ID or journal.get("phase") != "active" or journal.get("profile_output") != profile["output"]:
        raise BridgeError("A different or incomplete bridge activation exists. Restore it before launching this profile.")
    if not order.is_file() or order.read_bytes() != (MOD_ID + "\n").encode("utf-8"):
        raise BridgeError("The map-only mod order changed. Restore/re-activate before joining the restricted test server.")
    check_mod(mods / MOD_ID)
    return mods / MOD_ID


def launch_spec(profile: dict, kind: str) -> tuple[list[str], Path, dict]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("KCDMP_")}
    if kind == "server":
        root = Path(profile["server"])
        check_distribution(root, "server")
        cwd = Path(profile["server_profile"])
        return [str(root / "KcdMp.Server.exe"), "--config", str(cwd / "server.kcd1-map-only.toml")], cwd, env
    root = Path(profile["client"])
    check_distribution(root, "client")
    require_active(profile)
    inspect_game(Path(profile["game"]))
    args = [str(root / "KcdMp_launcher.exe"), "--game", profile["game"], "--name", profile["name"]]
    if kind == "client":
        # Let the queried server choose +map. The Welcome packet must agree.
        args += ["--connect", profile["host"]]
    elif kind == "offline":
        spawn = profile["spawn"]
        coords = ",".join(format(float(x), ".9g") for x in (*spawn["xyz"], spawn["yaw_degrees"]))
        args += ["--map", LEVEL, "--", "-KcdMp_spawn", coords]
    else:
        raise BridgeError("Unknown launch kind.")
    return args, root, env


def launch(profile: dict, kind: str, progress=print) -> int:
    if os.name != "nt":
        raise BridgeError("The supplied client/server executables run on Windows. Build and inspect are portable; launch on your Windows gaming PC.")
    args, cwd, env = launch_spec(profile, kind)
    progress("Starting " + kind + ". " + ("Leave this server window open." if kind == "server" else "The launcher will check the retail game build."))
    return subprocess.run(args, cwd=cwd, env=env, shell=False).returncode
