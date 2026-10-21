"""KCD1:MP setup adapter: reuse a finished world, configure and launch KCD:MP."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tomllib
import uuid

from kcdmp_map_project.kcdmp_bridge import builder, profile as bridge

MOD_ID = builder.MOD_ID
DEFAULTS = dict(mp_source='', mp_client='', mp_server='', mp_profile='',
    mp_host='127.0.0.1:7777', mp_player='Player', mp_server_name='KCD1:MP',
    mp_port=7777, mp_max_players=4, mp_password='', mp_pvp=False,
    mp_time='12:00', mp_time_ratio=0.0)


def settings(raw):
    result = {key: raw.get(key, value) for key, value in DEFAULTS.items()}
    for key in ('mp_source', 'mp_client', 'mp_server', 'mp_profile', 'mp_host',
                'mp_player', 'mp_server_name', 'mp_password', 'mp_time'):
        if not isinstance(result[key], str) or any(ord(c) < 32 for c in result[key]):
            raise ValueError('Invalid KCD1:MP field: '+key)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', result['mp_player']):
        raise ValueError('Player name needs 1–32 letters, numbers, dots, hyphens or underscores.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+:[0-9]{1,5}', result['mp_host']) or not 1 <= int(result['mp_host'].rsplit(':',1)[1]) <= 65535:
        raise ValueError('Join address must be host:port, such as 127.0.0.1:7777.')
    for key, upper in (('mp_port',65535),('mp_max_players',128)):
        if type(result[key]) is not int or not 1 <= result[key] <= upper:
            raise ValueError(f'{key} must be an integer from 1 to {upper}.')
    if not 1 <= len(result['mp_server_name']) <= 100:
        raise ValueError('Server name needs 1–100 characters.')
    if result['mp_password'] and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', result['mp_password']):
        raise ValueError('Password needs up to 64 letters, numbers, dots, hyphens or underscores (launcher token format).')
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',result['mp_time']):
        raise ValueError('Server time must be HH:MM, from 00:00 to 23:59.')
    ratio = result['mp_time_ratio']
    if type(ratio) not in (int,float) or not math.isfinite(ratio) or not 0 <= ratio <= 100:
        raise ValueError('Time speed must be from 0 (frozen) to 100.')
    if type(result['mp_pvp']) is not bool: raise ValueError('Invalid PvP option.')
    return result


def resolve_source(value, game):
    root = Path(value) if value else Path(game)/'Mods/kingdomcomegluemapper'
    root = builder.unredirected(root)
    for candidate in (root, root/'package/map', root/'map'):
        if (candidate/'mod.manifest').is_file(): return candidate
    raise ValueError('Choose a completed KCD1 Map build/package, or install KCD1 Map first. A lighting cache alone does not contain the world.')


def sources(workspace, game):
    """Only advertise finished jobs; never choose a still-running conversion."""
    candidates = []
    root = Path(workspace)
    if root.is_dir():
        for folder in sorted(root.iterdir(), reverse=True):
            if not folder.is_dir(): continue
            events = folder/'events.jsonl'
            try:
                complete = any(json.loads(line).get('kind') == 'done' for line in events.read_text(encoding='utf-8').splitlines())
            except (OSError,ValueError): continue
            if complete and (folder/'package/map/mod.manifest').is_file():
                candidates.append(dict(path=str(folder/'package/map'), label=folder.name))
    installed = Path(game)/'Mods/kingdomcomegluemapper'
    if (installed/'mod.manifest').is_file():
        candidates.append(dict(path=str(installed),label='Installed KCD1 Map'))
    return candidates


def options(config, output, source=None):
    return builder.BuildOptions(game=Path(config['kcd2']), client=Path(config['mp_client']),
        server=Path(config['mp_server']), output=Path(output),
        source_mod=source or resolve_source(config['mp_source'],config['kcd2']),
        host=config['mp_host'], player_name=config['mp_player'], standalone=False, portable_runtime=True)


def validate_shaders(source, game):
    from setup_shaders import validate
    from setup_campaign import digest
    validate(Path(source)/'ShaderCache')
    report=json.loads((Path(source)/'ShaderCache/shader-build.json').read_text())
    if report['source'] != digest(Path(game)/'Engine/Shaders.pak'):
        raise ValueError('The map shaders belong to another retail shader version. Rebuild KCD1 Map with current setup first.')


def preflight(config):
    if config['action']=='install':
        p=bridge.read_profile(Path(config['package'])/'mp/profile.json')
        if Path(p['game']) != Path(config['kcd2']).resolve():
            raise ValueError('This multiplayer profile was built for a different KCD2 installation.')
        bridge.check_mod(Path(p['mod']),full=False)
    else:
        for key in ('mp_client','mp_server'):
            if not config[key].strip(): raise ValueError('Choose both KCD:MP client and server folders.')
        game=builder.inspect_game(Path(config['kcd2']))
        if game['store']!='steam':
            raise ValueError('KCD1:MP setup currently needs the Steam retail layout for its shader runtime.')
        for key,kind in (('mp_client','client'),('mp_server','server')):
            builder.check_distribution(Path(config[key]),kind)
        if 'map' not in config['mods'] or config['mp_source']:
            source=resolve_source(config['mp_source'],config['kcd2'])
            from setup_campaign import verify_package
            verify_package(source,hashes=False)
            validate_shaders(source,config['kcd2'])
            plan=builder.inspect(options(config,Path(config['workspace'])/('mp-check-'+uuid.uuid4().hex),source))
            required=plan['estimated_output_bytes']+2*1024**3
            from desktop_setup import free_space
            if free_space(Path(config['workspace'])) < required:
                raise ValueError(f'KCD1:MP needs approximately {required/1024**3:.1f} GiB for its separate map snapshot.')
    if config['action']!='build_only':
        bridge.game_stopped()
        if (Path(config['kcd2'])/'.gluemapper-kcdmp/active.json').exists():
            raise ValueError('Restore single-player from KCD1:MP before installing another package.')
    return 'KCD1:MP reuses a completed world, lighting and shaders. It exports scenery without campaign/NPC schedules. Installation activates only KCD1:MP and saves the previous mod order. Use Restore single-player to switch back. Multiplayer runtime validation is pending.'


def configure(profile, raw):
    c=settings(raw)
    path=Path(profile['server_profile'])/'server.kcd1-map-only.toml'
    text=path.read_text(encoding='utf-8')
    replacements={('server','name'):c['mp_server_name'],('server','port'):c['mp_port'],
        ('server','max_players'):c['mp_max_players'],('server','password'):c['mp_password'],
        ('world','time'):c['mp_time'],('world','time_ratio'):c['mp_time_ratio'],('combat','pvp'):c['mp_pvp']}
    section=''; lines=[]; found=set()
    for line in text.splitlines():
        match=re.fullmatch(r'\[([^]]+)\]',line.strip())
        if match: section=match[1]
        key=(section,line.split('=',1)[0].strip())
        if key in replacements:
            line=key[1]+' = '+json.dumps(replacements[key],ensure_ascii=False);found.add(key)
        lines.append(line)
    if found!=set(replacements): raise ValueError('Server settings template is incomplete.')
    revised='\n'.join(lines)+'\n';tomllib.loads(revised)
    bridge.atomic_bytes(path,revised.encode('utf-8'))
    profile.update(name=c['mp_player'],host=c['mp_host'],token=c['mp_password'],setup_settings=c)
    bridge.atomic_json(Path(profile['output'])/'profile.json',profile)
    return profile


def run(config, package, notify, cancelled):
    output=Path(package)/'mp'
    if config['action']=='install':
        p=bridge.read_profile(output/'profile.json')
    elif (output/'profile.json').is_file():
        p=bridge.read_profile(output/'profile.json');bridge.check_mod(Path(p['mod']),full=True)
    else:
        source=(Path(package)/'map' if 'map' in config['mods'] and not config['mp_source']
                else resolve_source(config['mp_source'],config['kcd2']))
        from setup_campaign import verify_package
        notify('Verify completed map, lighting and shaders')
        verify_package(source)
        validate_shaders(source,config['kcd2'])
        if output.exists(): output.rename(output.with_name('mp-incomplete-'+uuid.uuid4().hex[:8]))
        def progress(message):
            if cancelled(): raise InterruptedError('Cancelled KCD1:MP export; source map retained.')
            notify(message)
        def upgrade_level(mod, level):
            from terrain_surface_placement import upgrade_package
            progress('Applying KCD2 surface-tree placement to the multiplayer snapshot...')
            return upgrade_package(mod, level)[1]
        p=builder.build(options(config,output,source),progress,upgrade_level=upgrade_level)
        bridge.check_mod(Path(p['mod']),full=True)
    configure(p,config)
    if cancelled(): raise InterruptedError('Cancelled before multiplayer activation.')
    if config['action']!='build_only': bridge.activate(p,notify)
    return str(output/'profile.json')


def launch_spec(profile, kind):
    """Prepare the same canonical level/shader layout as setup before KCD:MP."""
    args,cwd,env=bridge.launch_spec(profile,kind)
    if kind!='server':
        from setup_launch import launch
        prepared=launch(profile['game'],prepare_only=True,mod_id=MOD_ID)
        args[args.index('--game')+1]=prepared['root']
        env.update(SteamAppId='1771300',SteamGameId='1771300')
        if kind=='client' and profile.get('token'): args.extend(['--token',profile['token']])
    return args,cwd,env


def start_process(profile,kind):
    if kind=='server':
        dotnet=shutil.which('dotnet')
        if not dotnet: raise ValueError('Install the .NET 10 x64 runtime to host a KCD:MP server.')
        probe=subprocess.run([dotnet,'--list-runtimes'],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not re.search(r'^Microsoft.NETCore.App 10\.',probe.stdout,re.M):
            raise ValueError('The KCD:MP server requires the .NET 10 runtime.')
        cfg=tomllib.loads((Path(profile['server_profile'])/'server.kcd1-map-only.toml').read_text())
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            try: sock.bind(('',cfg['server']['port']))
            except OSError as e: raise ValueError('Server port is already in use. Stop that server or choose another port.') from e
    args,cwd,env=launch_spec(profile,kind)
    logfile=Path(profile['output'])/(kind+'-launcher.log')
    with logfile.open('ab') as stream:
        process=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if kind=='server':
        try: code=process.wait(timeout=1)
        except subprocess.TimeoutExpired: pass
        else: raise ValueError(f'The server exited with code {code}. See {logfile}')
    return process,logfile
