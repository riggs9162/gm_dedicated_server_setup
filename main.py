"""Interactive and unattended command-line server management."""

import argparse
import getpass
import json
import signal
import sys
import threading
from dataclasses import asdict

import gmod_server as core


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    operations = result.add_mutually_exclusive_group()
    for operation in core.OPERATIONS:
        operations.add_argument('--' + operation, dest='operation', action='store_const', const=operation)
    result.add_argument('--profile', help='Load a saved profile')
    result.add_argument('--save-profile', metavar='NAME')
    result.add_argument('--list-profiles', action='store_true')
    for key in asdict(core.Settings()):
        if key not in ('lan', 'password'):
            result.add_argument('--' + key.replace('_', '-'))
    network = result.add_mutually_exclusive_group()
    network.add_argument('--lan', action='store_true', default=None)
    network.add_argument('--internet', dest='lan', action='store_false')
    result.add_argument('--ask-password', action='store_true', help='Prompt securely; an empty value removes the password')
    result.add_argument('--discover', action='store_true', help='List installed loose maps and gamemodes')
    result.add_argument('--start', action='store_true', help='Start after the selected operation, or start only')
    result.add_argument('--list-links', action='store_true')
    result.add_argument('--link', nargs=3, metavar=('CATEGORY', 'NAME', 'SOURCE'), help='Create a managed addon/gamemode link')
    result.add_argument('--link-type', choices=('junction', 'symlink'), default='junction')
    result.add_argument('--unlink', nargs=2, metavar=('CATEGORY', 'NAME'), help='Remove a managed link, preserving its source')
    return result


def interactive():
    """Collect settings without starting downloads before validation."""
    names = core.list_profiles()
    print('Garry\'s Mod Dedicated Server Setup')
    if names:
        print('Profiles: ' + ', '.join(names))
    name = input('Profile to load (blank for a new server): ').strip()
    settings = core.load_profile(name) if name else core.Settings()
    operation = input('Operation [install/update/repair/configure] (install): ').strip().lower() or 'install'
    if operation not in core.OPERATIONS:
        raise ValueError('Choose install, update, repair, or configure.')
    for key, value in asdict(settings).items():
        if key not in ('password', 'lan'):
            answer = input(f"{key.replace('_', ' ').capitalize()} [{value}]: ").strip()
            if answer:
                setattr(settings, key, answer)
    answer = input(f'LAN only [{"yes" if settings.lan else "no"}]: ').strip().lower()
    if answer:
        settings.lan = answer in ('yes', 'y')
    if input('Change server password? [y/N]: ').strip().lower() == 'y':
        settings.password = getpass.getpass('Password (blank removes it): ')
    name = input(f'Save profile as [{name or "default"}]: ').strip() or name or 'default'
    return settings, operation, name


def main(argv=None):
    args = parser().parse_args(argv)
    cancel = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    log = None
    try:
        if args.list_profiles:
            print('\n'.join(core.list_profiles()) or 'No saved profiles.')
            return 0
        if not (sys.argv[1:] if argv is None else argv):
            settings, operation, save_name = interactive()
        else:
            settings = core.load_profile(args.profile) if args.profile else core.Settings()
            for key in asdict(settings):
                if key != 'password' and getattr(args, key, None) is not None:
                    setattr(settings, key, getattr(args, key))
            if args.ask_password:
                settings.password = getpass.getpass('Server password (blank removes it): ')
            operation, save_name = args.operation, args.save_profile
        settings = core.validate(settings)
        if save_name:
            core.save_profile(save_name, settings)
        if args.discover:
            maps, modes = core.discover_content(settings.server_dir)
            print(json.dumps(dict(maps=maps, gamemodes=modes), indent=2))
        if args.list_links:
            print(json.dumps(core.list_links(settings.server_dir), indent=2))
        if args.link:
            category, name, source = args.link
            print(core.create_link(settings.server_dir, category, name, source, args.link_type))
        if args.unlink:
            core.remove_link(settings.server_dir, *args.unlink)
            print('Link removed; source files preserved.')
        if operation:
            log = core.OperationLog(secrets=[settings.password])
            print(f'Full log: {log.path}')
            core.run_operation(settings, operation, log, cancel)
        core.check_cancel(cancel)
        if args.start:
            core.start_server(settings.server_dir)
        if not any((operation, save_name, args.discover, args.list_links, args.link, args.unlink, args.start)):
            parser().print_help()
        return 0
    except core.Cancelled as error:
        (log or print)(str(error))
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        (log or print)(f'Failed: {error}')
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == '__main__':
    sys.exit(main())
