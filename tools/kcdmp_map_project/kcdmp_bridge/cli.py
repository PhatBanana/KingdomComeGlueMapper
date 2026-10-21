"""Command-line entry point and a small Windows-friendly interactive setup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

from .archive import BridgeError
from .builder import BuildOptions, build, inspect
from .profile import activate, check_mod, launch, read_profile, restore_game


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export the converted KCD1 scenery for KCDMP 0.44.0. No executable patches or new bake.")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Ask for local paths, then build a new profile")
    for name in ("inspect", "build"):
        sub = commands.add_parser(name, help="Read-only compatibility inspection" if name == "inspect" else "Build a separate map and server profile")
        sub.add_argument("--game", type=Path, required=True, help="Retail KCD2 root")
        sub.add_argument("--client", type=Path, required=True, help="Original client ZIP or extracted 0.44.0 directory")
        sub.add_argument("--server", type=Path, required=True, help="Original server ZIP or extracted Windows directory")
        sub.add_argument("--source-mod", type=Path, help="Defaults to GAME/Mods/kingdomcomegluemapper")
        sub.add_argument("--output", type=Path, required=True, help="Fresh output folder outside the game and source")
        sub.add_argument("--spawn", type=float, nargs=3, metavar=("X", "Y", "Z"), help="Optional explicit world coordinates; otherwise use authored arrival")
        sub.add_argument("--yaw", type=float, help="Heading in degrees; otherwise use authored arrival quaternion")
        sub.add_argument("--name", default="SamGCoder", help="Multiplayer player name")
        sub.add_argument("--host", default="127.0.0.1:7777", help="Server address for the join command")
    for name in ("activate", "restore", "verify", "launch"):
        sub = commands.add_parser(name)
        if name == "restore":
            group = sub.add_mutually_exclusive_group(required=True)
            group.add_argument("--profile", type=Path)
            group.add_argument("--game", type=Path, help="Recover even if the exported profile folder was lost")
        else:
            sub.add_argument("--profile", type=Path, required=True)
        if name == "verify":
            sub.add_argument("--full", action="store_true", help="Read/hash every generated asset (can take time)")
        if name == "launch":
            sub.add_argument("--kind", choices=("server", "client", "offline"), required=True)
    return p


def ask_path(label: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default else ""
    answer = input(label + suffix + ": ").strip().strip('"')
    if not answer and default is None:
        raise BridgeError("A path is required.")
    return Path(answer) if answer else default


def setup() -> dict:
    print("GlueMapper -> KCDMP map-only project\n")
    print("Requires your existing combined GlueMapper map, retail KCD2 1.5.6 and the two original KCDMP 0.44.0 downloads.")
    print("This builds a separate snapshot. Activate it afterward with 1_ACTIVATE_MAP.cmd.\n")
    root = Path(__file__).resolve().parents[1]
    game = ask_path("KCD2 game root")
    source = ask_path("Converted GlueMapper mod/package", game / "Mods/kingdomcomegluemapper")
    client = ask_path("KCDMP client ZIP or directory", root / "KcdMp-0.44.0-win-x64.zip")
    server = ask_path("KCDMP server ZIP or directory", root / "KcdMp-server-0.44.0.zip")
    output = ask_path("Fresh output folder", root / "build")
    return build(BuildOptions(game=game, source_mod=source, client=client, server=server, output=output))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            setup()
        elif args.command in ("inspect", "build"):
            options = BuildOptions(game=args.game, client=args.client, server=args.server, output=args.output,
                                   source_mod=args.source_mod, spawn=tuple(args.spawn) if args.spawn else None,
                                   yaw=args.yaw, player_name=args.name, host=args.host)
            if args.command == "inspect":
                print(json.dumps(inspect(options), indent=2))
            else:
                build(options)
        elif args.command == "restore":
            game = args.game.expanduser().absolute() if args.game else Path(read_profile(args.profile)["game"])
            restore_game(game)
        else:
            profile = read_profile(args.profile)
            if args.command == "activate":
                activate(profile)
            elif args.command == "verify":
                receipt = check_mod(Path(profile["mod"]), full=args.full)
                print(f"Verified {len(receipt['files'])} generated files ({'all hashes' if args.full else 'sizes and core hashes'}). Runtime gameplay remains unverified.")
            elif args.command == "launch":
                return launch(profile, args.kind)
        return 0
    except (BridgeError, OSError, ValueError, KeyError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled. During activation, run RESTORE_MODS.cmd to recover its journal.", file=sys.stderr)
        return 130
    except Exception:
        traceback.print_exc()
        print("Unexpected failure. Keep this error and any BUILD_FAILED.json; no automatic binary patching is attempted.", file=sys.stderr)
        return 1
