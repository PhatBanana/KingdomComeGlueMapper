"""Launch installed map shaders from setup; no SDK or build workspace is needed."""
import json
import os
from pathlib import Path
import subprocess

from setup_campaign import MOD_ID, runtime_directory


def installed_mod(target):
    if not isinstance(target, str) or not target.strip():
        raise ValueError('Choose your KCD2 installation in setup first.')
    game = Path(target).resolve()
    mod = game/'Mods'/MOD_ID
    if mod.resolve() != mod or not (mod/'mod.manifest').is_file():
        raise ValueError('Install KCD1 Map in the selected game before launching it.')
    if not (mod/'ShaderCache/shader-build.json').is_file():
        raise ValueError('This installation has no compiled shaders. Rebuild and install it with the current setup.')
    return mod


def launch(target, *, development=False, prepare_only=False):
    """Internal helper stays bundled with setup, never exposed as a mod shortcut.

    The helper validates archive hashes, source version and running processes
    before refreshing the single linked runtime. It starts the original game
    with Steam authentication, returning a PID rather than claiming game readiness.
    """
    if os.name != 'nt': raise ValueError('Launching KCD2 requires Windows.')
    mod = installed_mod(target)
    helper = runtime_directory()/'launch_with_shaders.ps1'
    powershell = Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    args = [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
        '-ExecutionPolicy', 'Bypass', '-File', str(helper), '-ModDirectory', str(mod)]
    if development: args.append('-Development')
    if prepare_only: args.append('-PrepareOnly')
    result = subprocess.run(args,
        capture_output=True, text=True, errors='replace', timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip() or 'Unable to launch KCD2.')
    report = json.loads(result.stdout.lstrip('\ufeff'))
    if prepare_only:
        if not report.get('root'): raise ValueError('The launcher did not return a prepared runtime.')
    elif not isinstance(report.get('pid'), int):
        raise ValueError('The launcher did not return a game process.')
    return dict(ok=True, **report)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Use the setup retail runtime, including canonical AI level paths.')
    parser.add_argument('--target', required=True)
    parser.add_argument('--development', action='store_true', help='Enable diagnostics in the same setup runtime')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare and inspect the runtime without starting the game')
    print(json.dumps(launch(**vars(parser.parse_args())), indent=2))
