"""Shared Windows server operations, profiles, diagnostics and development links."""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager, ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

STEAMCMD_URL = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DEFAULT_MAP = 'gm_construct'
DEFAULT_GAMEMODE = 'sandbox'
DEFAULT_MAX_PLAYERS = '32'
DEFAULT_PORT = '27015'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'GModServerSetup'
OPERATIONS = ('install', 'update', 'repair', 'configure')


class Cancelled(Exception):
    """The user stopped the current operation."""


@dataclass
class Settings:
    steamcmd_dir: str = r'C:\steamcmd'
    server_dir: str = r'C:\gmodserver'
    hostname: str = "My Garry's Mod Server"
    map_name: str = DEFAULT_MAP
    gamemode: str = DEFAULT_GAMEMODE
    max_players: str = DEFAULT_MAX_PLAYERS
    port: str = DEFAULT_PORT
    collection_id: str = ''
    lan: bool = False
    password: str = ''


def clean_path(value):
    """Normalize pasted paths without removing drive roots."""
    value = str(value).strip().strip('"').strip("'")
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value))) if value else ''


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('Cancelled. Downloaded server files are kept for the next run.')


@contextmanager
def directory_lock(directory):
    """Prevent simultaneous operations on the same server or SteamCMD installation."""
    import msvcrt
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.setup.lock').open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError(f'Another setup operation is using {directory}.') from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def collection_id(value):
    """Accept a numeric Workshop ID or Steam Community collection URL."""
    value = value.strip()
    if not value:
        return ''
    if re.fullmatch(r'[0-9]+', value) and int(value) > 0:
        return value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in ('http', 'https') and parsed.hostname in ('steamcommunity.com', 'www.steamcommunity.com'):
        candidate = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
        if re.fullmatch(r'[0-9]+', candidate) and int(candidate) > 0:
            return candidate
    raise ValueError('Workshop collection must be a positive ID or Steam Community URL.')


def validate(settings):
    """Return normalized settings shared by both front ends."""
    result = Settings(**asdict(settings))
    for key in ('steamcmd_dir', 'server_dir'):
        value = clean_path(getattr(result, key))
        if not value or any(c in value for c in '\r\n\x00'):
            raise ValueError(f"Choose a valid {key.replace('_', ' ')}.")
        setattr(result, key, value)
    if Path(result.steamcmd_dir).resolve() == Path(result.server_dir).resolve():
        raise ValueError('SteamCMD and the server need separate folders.')
    for key, low, high in (('port', 1, 65535), ('max_players', 1, 128)):
        value = str(getattr(result, key)).strip()
        if not re.fullmatch(r'[0-9]+', value) or not low <= int(value) <= high:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} must be between {low} and {high}.")
        setattr(result, key, str(int(value)))
    for key in ('map_name', 'gamemode'):
        value = getattr(result, key).strip()
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', value):
            raise ValueError(f"{key.replace('_', ' ').capitalize()} must use letters, numbers, underscores, dots or hyphens.")
        setattr(result, key, value)
    for key in ('hostname', 'password'):
        if any(ord(c) < 32 or c in '"\\;' for c in getattr(result, key)):
            raise ValueError(f'{key.capitalize()} cannot contain quotes, backslashes, semicolons or control characters.')
    if not result.hostname.strip():
        raise ValueError('Server name cannot be empty.')
    result.collection_id = collection_id(result.collection_id)
    return result


def atomic_write(path, content, backup=True):
    """Atomically replace text, retaining a uniquely named backup when changed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding='utf-8-sig') == content:
        return
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + datetime.now().strftime('.%Y%m%d-%H%M%S-%f.bak')))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as output:
            temporary = output.name
            output.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def list_profiles():
    return sorted(read_json(DATA_DIR / 'profiles.json', {}).keys())


def save_profile(name, settings):
    """Save settings without copying passwords into the profile store."""
    if not name.strip():
        raise ValueError('Enter a profile name.')
    profiles = read_json(DATA_DIR / 'profiles.json', {})
    data = asdict(validate(settings))
    data.pop('password')
    profiles[name.strip()] = data
    atomic_write(DATA_DIR / 'profiles.json', json.dumps(profiles, indent=2), backup=False)
    atomic_write(DATA_DIR / 'last-profile.txt', name.strip(), backup=False)


def load_profile(name):
    profiles = read_json(DATA_DIR / 'profiles.json', {})
    if name not in profiles:
        raise ValueError(f"Profile '{name}' does not exist.")
    settings = Settings(**profiles[name])
    cfg = Path(settings.server_dir) / 'garrysmod/cfg/server.cfg'
    if cfg.exists():
        matches = re.findall(r'^\s*sv_password\s+"([^"\r\n]*)"', cfg.read_text(encoding='utf-8-sig'), re.MULTILINE)
        if matches:
            settings.password = matches[-1]
    return settings


def steamcmd_executable(directory):
    return str(Path(directory) / 'steamcmd.exe')


def download_steamcmd(directory, log=print, cancel=None):
    """Download with bounded network waits and cancellation between chunks."""
    try:
        _download_steamcmd(directory, log, cancel)
    except Exception:
        check_cancel(cancel)
        raise


def _download_steamcmd(directory, log, cancel):
    Path(directory).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gmod-steamcmd-') as temporary:
        archive = Path(temporary) / 'steamcmd.zip'
        check_cancel(cancel)
        with urllib.request.urlopen(STEAMCMD_URL, timeout=10) as response, archive.open('wb') as output:
            total = int(response.headers.get('Content-Length', 0))
            received = 0
            last_report = 0
            while True:
                check_cancel(cancel)
                chunk = response.read(65536)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if time.monotonic() - last_report >= 0.5:
                    log(f'SteamCMD download: {received * 100 / total:.0f}%' if total else f'SteamCMD download: {received // 1024} KiB')
                    last_report = time.monotonic()
        check_cancel(cancel)
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                check_cancel(cancel)
                destination = (Path(directory) / member.filename).resolve()
                if not destination.is_relative_to(Path(directory).resolve()):
                    raise ValueError('SteamCMD archive contains an invalid path.')
                package.extract(member, directory)
    log('SteamCMD downloaded.')


def stop_process(process):
    """Stop SteamCMD and its updater children on Windows."""
    if process.poll() is None:
        if os.name == 'nt':
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW, timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_steamcmd(executable, arguments, log=print, cancel=None):
    """Stream output without blocking cancellation when SteamCMD is silent."""
    check_cancel(cancel)
    process = subprocess.Popen([executable, *arguments], cwd=str(Path(executable).parent), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace', creationflags=NO_WINDOW)
    lines = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line.rstrip())
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while True:
            check_cancel(cancel)
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            if line:
                log(line)
        while process.poll() is None:
            check_cancel(cancel)
            time.sleep(0.1)
        check_cancel(cancel)
        return process.returncode
    finally:
        stop_process(process)
        reader.join(timeout=5)
        process.stdout.close()


def install_gmod_server(settings, operation, log=print, cancel=None):
    """Update without validation; repair explicitly validates existing files."""
    arguments = ['+force_install_dir', settings.server_dir, '+login', 'anonymous', '+app_update', '4020']
    if operation == 'repair':
        arguments.append('validate')
    arguments.append('+quit')
    for attempt in range(1, 4):
        check_cancel(cancel)
        output = []

        def capture(line):
            output.append(line)
            log(line)

        log(f'{operation.capitalize()}: attempt {attempt}/3')
        code = run_steamcmd(steamcmd_executable(settings.steamcmd_dir), arguments, capture, cancel)
        check_cancel(cancel)
        success = any("Success! App '4020'" in line for line in output)
        if code == 0 and success and (Path(settings.server_dir) / 'srcds.exe').is_file():
            return
        if attempt < 3:
            if any('Missing configuration' in line for line in output):
                cache = Path(settings.steamcmd_dir) / 'appcache'
                root = Path(settings.steamcmd_dir).resolve()
                if cache.exists() and cache.resolve().parent == root and not is_link(cache):
                    shutil.rmtree(cache)
                    log('Cleared stale SteamCMD appcache.')
            log(f'SteamCMD failed (exit {code}); retrying in {attempt * 2} seconds.')
            if cancel is not None:
                cancel.wait(attempt * 2)
            else:
                time.sleep(attempt * 2)
    raise RuntimeError('SteamCMD did not confirm installation. Check the saved log and available disk space.')


def write_configuration(settings):
    """Preserve unrelated configuration and back up changed generated files."""
    settings = validate(settings)
    cfg = Path(settings.server_dir) / 'garrysmod/cfg/server.cfg'
    existing = cfg.read_text(encoding='utf-8-sig') if cfg.exists() else ''
    begin, end = '// BEGIN GModServerSetup', '// END GModServerSetup'
    if existing.count(begin) != existing.count(end) or existing.count(begin) > 1:
        raise ValueError('The managed configuration block is damaged. Restore its backup before configuring.')
    existing = re.sub(r'(?m)^// BEGIN GModServerSetup\r?\n.*?^// END GModServerSetup\r?\n?', '', existing, flags=re.DOTALL)
    lines = existing.rstrip('\n').splitlines()
    lines.extend([begin, f'hostname "{settings.hostname}"', f'sv_password "{settings.password}"', f'sv_lan {int(settings.lan)}', end])
    atomic_write(cfg, '\n'.join(lines) + '\n')
    script = Path(settings.server_dir) / 'start_server.bat'
    atomic_write(script, '@echo off\nsetlocal DisableDelayedExpansion\ncd /d "%~dp0"\n' + build_start_command(settings) + '\npause\n')
    return script


def build_start_command(settings):
    settings = validate(settings)
    command = (f'srcds.exe -game garrysmod -console -condebug -port {settings.port} '
               f'-maxplayers {settings.max_players} +gamemode {settings.gamemode} +map {settings.map_name}')
    if settings.collection_id:
        command += f' +host_workshop_collection {settings.collection_id}'
    return command


def preflight(settings, operation, log=print):
    """Check folders, running server processes, disk space and the chosen port."""
    if os.name != 'nt':
        raise RuntimeError('This tool currently supports Windows only.')
    if operation not in OPERATIONS:
        raise ValueError('Unknown operation.')
    server = Path(settings.server_dir)
    if operation != 'install' and not (server / 'srcds.exe').is_file():
        raise ValueError('Select an existing server for Update, Repair, or Configure.')
    for directory in ([server] if operation == 'configure' else [server, Path(settings.steamcmd_dir)]):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    command = "Get-CimInstance Win32_Process -Filter \"Name='srcds.exe'\" | Select-Object -ExpandProperty ExecutablePath | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=20)
    if result.returncode:
        raise RuntimeError('Could not check running servers: ' + result.stderr.strip())
    paths = (json.loads(result.stdout) or []) if result.stdout.strip() else []
    paths = [paths] if isinstance(paths, str) else paths
    if any(p and Path(p).resolve() == (server / 'srcds.exe').resolve() for p in paths):
        raise RuntimeError('Stop this server before modifying its files.')
    if operation != 'configure':
        free = shutil.disk_usage(server).free / (1024 ** 3)
        log(f'Available disk space: {free:.1f} GiB')
        required = 15 if not (server / 'srcds.exe').exists() else 2
        if free < required:
            raise RuntimeError(f'At least {required} GiB of free space is required for this operation.')
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        with socket.socket(socket.AF_INET, kind) as probe:
            try:
                probe.bind(('0.0.0.0', int(settings.port)))
            except OSError:
                raise RuntimeError(f'Port {settings.port} is unavailable. Stop the server using it or choose another port.') from None
    log('Preflight checks passed.')


class OperationLog:
    """Write complete timestamped diagnostics while forwarding redacted output."""

    def __init__(self, callback=print, secrets=()):
        directory = DATA_DIR / 'logs'
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / datetime.now().strftime('setup-%Y%m%d-%H%M%S-%f.log')
        self.callback = callback
        self.secrets = [value for value in secrets if value]
        self.started = time.monotonic()

    def __call__(self, message):
        for secret in self.secrets:
            message = message.replace(secret, '[redacted]')
        line = f'[{time.monotonic() - self.started:7.1f}s] {message}'
        with self.path.open('a', encoding='utf-8') as output:
            output.write(line + '\n')
        self.callback(line)


def run_operation(settings, operation='install', log=print, cancel=None):
    """Execute stages consistently; failures never become a success status."""
    settings = validate(settings)
    if os.name != 'nt':
        raise RuntimeError('This tool currently supports Windows only.')
    if operation not in OPERATIONS:
        raise ValueError('Unknown operation.')
    directories = [settings.server_dir] if operation == 'configure' else [settings.server_dir, settings.steamcmd_dir]
    with ExitStack() as stack:
        for directory in sorted(directories):
            check_cancel(cancel)
            stack.enter_context(directory_lock(directory))
        _run_operation(settings, operation, log, cancel)


def _run_operation(settings, operation, log, cancel):
    check_cancel(cancel)
    log('Stage: preflight')
    preflight(settings, operation, log)
    check_cancel(cancel)
    if operation != 'configure':
        executable = steamcmd_executable(settings.steamcmd_dir)
        if not Path(executable).is_file():
            log('Stage: download SteamCMD')
            download_steamcmd(settings.steamcmd_dir, log, cancel)
        log('Stage: update SteamCMD')
        if run_steamcmd(executable, ['+quit'], log, cancel) != 0:
            raise RuntimeError('SteamCMD self-update failed. See the saved log.')
        log(f'Stage: {operation} server')
        install_gmod_server(settings, operation, log, cancel)
    check_cancel(cancel)
    if operation in ('install', 'configure'):
        log('Stage: write configuration')
        write_configuration(settings)
    log(f'Completed: {operation}.')


def discover_content(server_dir):
    """List loose installed maps and gamemodes, including development links."""
    root = Path(server_dir) / 'garrysmod'
    maps = {p.stem for p in (root / 'maps').glob('*.bsp')}
    modes = {p.name for p in (root / 'gamemodes').glob('*') if p.is_dir()}
    for addon in (root / 'addons').glob('*'):
        if addon.is_dir():
            maps.update(p.stem for p in (addon / 'maps').glob('*.bsp'))
            modes.update(p.name for p in (addon / 'gamemodes').glob('*') if p.is_dir())
    return sorted(maps), sorted(modes)


def is_link(path):
    return Path(path).is_symlink() or os.path.isjunction(path)


def link_destination(server_dir, category, name):
    if category not in ('addons', 'gamemodes') or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name) or name.endswith('.'):
        raise ValueError('Use an addon/gamemode name with letters, numbers, underscores, dots or hyphens.')
    root = Path(server_dir).resolve()
    parent = root / 'garrysmod' / category
    if not parent.resolve().is_relative_to(root):
        raise ValueError('The content directory points outside the server folder.')
    return parent / name


def list_links(server_dir):
    """Return registered links with their current on-disk status."""
    records = read_json(Path(server_dir) / '.setup-links.json', [])
    for record in records:
        destination = link_destination(server_dir, record['category'], record['name'])
        record['status'] = 'linked' if is_link(destination) and destination.resolve() == Path(record['source']).resolve() and destination.exists() else 'missing or changed'
    return records


def create_link(server_dir, category, name, source, kind='junction'):
    """Create a managed mklink junction or directory symlink without replacing content."""
    if os.name != 'nt':
        raise RuntimeError('mklink is available on Windows only.')
    if kind not in ('junction', 'symlink'):
        raise ValueError('Link type must be junction or symlink.')
    if not source.strip():
        raise ValueError('Choose a source folder.')
    source = Path(clean_path(source)).resolve()
    destination = link_destination(server_dir, category, name)
    if not source.is_dir():
        raise ValueError('The source folder does not exist.')
    if source.is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(source):
        raise ValueError('Source and destination must not contain one another.')
    if any(ord(c) < 32 or c in '\"%' for c in str(source) + str(destination)):
        raise ValueError('Link paths cannot contain quotes, percent signs or control characters.')
    if os.path.lexists(destination):
        raise ValueError('The destination already exists. Existing folders and links are never replaced.')
    records = read_json(Path(server_dir) / '.setup-links.json', [])
    if any(r['category'] == category and r['name'].casefold() == name.casefold() for r in records):
        raise ValueError('This name is already registered. Remove its managed record first.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    switch = '/J' if kind == 'junction' else '/D'
    command = f'mklink {switch} "{destination}" "{source}"'
    executable = os.environ.get('COMSPEC', 'cmd.exe')
    result = subprocess.run(f'"{executable}" /d /v:off /c {command}', capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip() + (' Enable Windows Developer Mode or run elevated for symlinks.' if kind == 'symlink' else ''))
    records.append(dict(category=category, name=name, source=str(source), kind=kind))
    try:
        atomic_write(Path(server_dir) / '.setup-links.json', json.dumps(records, indent=2))
    except Exception:
        if is_link(destination):
            os.rmdir(destination)
        raise
    return destination


def remove_link(server_dir, category, name):
    """Unlink only a verified managed link, never recursively delete its source."""
    destination = link_destination(server_dir, category, name)
    manifest = Path(server_dir) / '.setup-links.json'
    records = read_json(manifest, [])
    record = next((r for r in records if r['category'] == category and r['name'] == name), None)
    if record is None:
        raise ValueError('This link is not managed by the tool.')
    if os.path.lexists(destination):
        if not is_link(destination) or destination.resolve() != Path(record['source']).resolve():
            raise ValueError('The destination changed; refusing to remove it.')
        os.rmdir(destination)
    records.remove(record)
    atomic_write(manifest, json.dumps(records, indent=2))


def start_server(server_dir):
    """Open the generated launcher for an explicitly requested interactive server."""
    script = Path(clean_path(server_dir)) / 'start_server.bat'
    if not script.is_file():
        raise ValueError('Configure the server first to generate start_server.bat.')
    os.startfile(script)
