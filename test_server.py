"""Regression tests for file preservation, cancellation, CLI and real Windows links."""

import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import gmod_server as core
import main


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = core.Settings(server_dir=str(self.root / 'server'), steamcmd_dir=str(self.root / 'steamcmd'))
        self.data_patch = patch.object(core, 'DATA_DIR', self.root / 'data')
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        self.temp.cleanup()

    def install_stub(self):
        server = Path(self.settings.server_dir)
        server.mkdir(parents=True, exist_ok=True)
        (server / 'srcds.exe').touch()
        return server

    def test_configuration_preserves_custom_commands_and_backups(self):
        cfg = Path(self.settings.server_dir) / 'garrysmod/cfg/server.cfg'
        cfg.parent.mkdir(parents=True)
        original = '// Custom settings\nrcon_password "secret"\nhostname "old"; sv_cheats 0\n'
        cfg.write_text(original)
        core.write_configuration(self.settings)
        self.assertIn(original, cfg.read_text())
        self.assertEqual(next(cfg.parent.glob('*.bak')).read_text(), original)
        self.assertIn('sv_cheats 0', cfg.read_text())
        self.settings.hostname = 'New name'
        core.write_configuration(self.settings)
        self.assertEqual(cfg.read_text().count('// BEGIN GModServerSetup'), 1)
        self.assertIn('hostname "New name"', cfg.read_text())

    def test_unchanged_configuration_does_not_create_backups(self):
        core.write_configuration(self.settings)
        core.write_configuration(self.settings)
        self.assertEqual(list(Path(self.settings.server_dir).rglob('*.bak')), [])

    def test_script_avoids_password_and_shell_metacharacters(self):
        self.settings.password = 'private&value%'
        script = core.write_configuration(self.settings)
        self.assertNotIn(self.settings.password, script.read_text())
        self.assertIn('cd /d "%~dp0"', script.read_text())
        for key, value in [('map_name', 'gm_construct & calc'), ('gamemode', '%PATH%'), ('port', '0'),
                           ('port', '65536'), ('max_players', '0'), ('hostname', 'bad"\nquit')]:
            with self.subTest(key=key, value=value):
                settings = core.Settings(**vars(self.settings))
                setattr(settings, key, value)
                with self.assertRaises(ValueError):
                    core.validate(settings)

    def test_workshop_url(self):
        self.assertEqual(core.collection_id('https://steamcommunity.com/sharedfiles/filedetails/?id=12345'), '12345')
        for value in ['0', 'abc', 'https://evil.example/?id=123']:
            with self.assertRaises(ValueError):
                core.collection_id(value)

    def test_profile_roundtrip_excludes_secret(self):
        self.settings.password = 'private'
        core.write_configuration(self.settings)
        core.save_profile('Testing', self.settings)
        self.assertNotIn('private', (core.DATA_DIR / 'profiles.json').read_text())
        self.assertEqual(core.load_profile('Testing'), core.validate(self.settings))
        self.assertEqual(core.list_profiles(), ['Testing'])

    def test_update_does_not_write_configuration(self):
        self.install_stub()
        with patch.object(core, 'preflight'), patch.object(core, 'download_steamcmd'), \
                patch.object(core, 'run_steamcmd', return_value=0), patch.object(core, 'install_gmod_server'), \
                patch.object(core, 'write_configuration') as write:
            core.run_operation(self.settings, 'update', log=lambda _: None)
        write.assert_not_called()

    def test_configure_never_calls_steamcmd(self):
        self.install_stub()
        with patch.object(core, 'preflight'), patch.object(core, 'run_steamcmd') as run:
            core.run_operation(self.settings, 'configure', log=lambda _: None)
        run.assert_not_called()

    def test_bootstrap_failure_stops_install(self):
        with patch.object(core, 'preflight'), patch.object(core, 'download_steamcmd'), \
                patch.object(core, 'run_steamcmd', return_value=1), patch.object(core, 'install_gmod_server') as install:
            with self.assertRaisesRegex(RuntimeError, 'self-update failed'):
                core.run_operation(self.settings, log=lambda _: None)
        install.assert_not_called()

    def test_write_failure_never_reports_complete(self):
        output = []
        with patch.object(core, 'preflight'), patch.object(core, 'write_configuration', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                core.run_operation(self.settings, 'configure', log=output.append)
        self.assertFalse(any('Completed' in line for line in output))

    def test_repair_is_only_operation_that_validates(self):
        self.install_stub()
        for operation in ('install', 'update', 'repair'):
            def success(executable, arguments, log, cancel):
                log("Success! App '4020' fully installed.")
                return 0
            with patch.object(core, 'run_steamcmd', side_effect=success) as run:
                core.install_gmod_server(self.settings, operation, log=lambda _: None)
                self.assertEqual('validate' in run.call_args.args[1], operation == 'repair')

    def test_old_executable_cannot_mask_failure(self):
        self.install_stub()
        with patch.object(core, 'run_steamcmd', return_value=0), patch.object(core.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                core.install_gmod_server(self.settings, 'update', log=lambda _: None)

    def test_cancel_prevents_retry_and_cache_purge(self):
        event = threading.Event()
        def cancel(*args):
            event.set()
            return 1
        with patch.object(core, 'run_steamcmd', side_effect=cancel) as run, patch.object(core.shutil, 'rmtree') as remove:
            with self.assertRaises(core.Cancelled):
                core.install_gmod_server(self.settings, 'install', log=lambda _: None, cancel=event)
        self.assertEqual(run.call_count, 1)
        remove.assert_not_called()

    def test_cancel_silent_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        try:
            with self.assertRaises(core.Cancelled):
                core.run_steamcmd(sys.executable, ['-c', 'import time; time.sleep(30)'], cancel=cancel)
        finally:
            timer.cancel()

    def test_cancel_before_download(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(core.urllib.request, 'urlopen') as request:
            with self.assertRaises(core.Cancelled):
                core.download_steamcmd(self.settings.steamcmd_dir, cancel=cancel)
        request.assert_not_called()

    def test_archive_path_traversal_rejected(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('../outside.exe', 'bad')
        response = io.BytesIO(archive.getvalue())
        response.headers = {'Content-Length': str(len(archive.getvalue()))}
        with patch.object(core.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(ValueError):
                core.download_steamcmd(self.settings.steamcmd_dir, log=lambda _: None)
        self.assertFalse((self.root / 'outside.exe').exists())

    def test_log_redacts_and_keeps_full_output(self):
        log = core.OperationLog(lambda _: None, ['secret'])
        for _ in range(510):
            log('test secret')
        text = log.path.read_text()
        self.assertEqual(len(text.splitlines()), 510)
        self.assertNotIn('secret', text)

    def test_preflight_requires_existing_server(self):
        with self.assertRaisesRegex(ValueError, 'existing server'):
            core.preflight(self.settings, 'configure')

    def test_preflight_detects_running_server(self):
        server = self.install_stub()
        result = Mock(returncode=0, stdout=json.dumps(str(server / 'srcds.exe')))
        with patch.object(core.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'Stop this server'):
                core.preflight(self.settings, 'configure')

    def test_preflight_checks_low_disk_space(self):
        result = Mock(returncode=0, stdout='')
        with patch.object(core.subprocess, 'run', return_value=result), \
                patch.object(core.shutil, 'disk_usage', return_value=Mock(free=1)):
            with self.assertRaisesRegex(RuntimeError, 'free space'):
                core.preflight(self.settings, 'install', log=lambda _: None)

    def test_real_junction_roundtrip_and_discovery(self):
        source = self.root / 'source with spaces & (test)!'
        (source / 'maps').mkdir(parents=True)
        (source / 'maps/custom.bsp').write_text('test')
        link = core.create_link(self.settings.server_dir, 'addons', 'development', str(source))
        try:
            self.assertTrue(os.path.isjunction(link))
            self.assertEqual(core.list_links(self.settings.server_dir)[0]['status'], 'linked')
            self.assertIn('custom', core.discover_content(self.settings.server_dir)[0])
            with self.assertRaises(ValueError):
                core.create_link(self.settings.server_dir, 'addons', 'development', str(source))
        finally:
            core.remove_link(self.settings.server_dir, 'addons', 'development')
        self.assertTrue((source / 'maps/custom.bsp').exists())
        self.assertFalse(os.path.lexists(link))

    def test_real_symlink_roundtrip(self):
        source = self.root / 'source'
        source.mkdir()
        try:
            os.symlink(source, self.root / 'privilege-probe', target_is_directory=True)
        except OSError as error:
            if error.winerror == 1314:
                self.skipTest('Windows symlink privileges unavailable')
            raise
        os.rmdir(self.root / 'privilege-probe')
        link = core.create_link(self.settings.server_dir, 'gamemodes', 'development', str(source), 'symlink')
        try:
            self.assertTrue(link.is_symlink())
        finally:
            core.remove_link(self.settings.server_dir, 'gamemodes', 'development')
        self.assertTrue(source.exists())

    def test_unlink_refuses_replaced_directory(self):
        source = self.root / 'source'
        source.mkdir()
        link = core.create_link(self.settings.server_dir, 'addons', 'development', str(source))
        os.rmdir(link)
        link.mkdir()
        (link / 'keep').touch()
        with self.assertRaises(ValueError):
            core.remove_link(self.settings.server_dir, 'addons', 'development')
        self.assertTrue((link / 'keep').exists())

    def test_link_refuses_traversal_and_recursive_target(self):
        source = self.root / 'source'
        source.mkdir()
        with self.assertRaises(ValueError):
            core.create_link(self.settings.server_dir, 'addons', '../outside', str(source))
        with self.assertRaises(ValueError):
            core.create_link(self.settings.server_dir, 'addons', 'cycle', str(self.root))

    def test_cli_profile_update(self):
        core.save_profile('sandbox', self.settings)
        with patch.object(core, 'run_operation') as run:
            self.assertEqual(main.main(['--profile', 'sandbox', '--update']), 0)
        self.assertEqual(run.call_args.args[1], 'update')
        self.assertEqual(run.call_args.args[0].server_dir, self.settings.server_dir)

    def test_cli_bad_input_returns_failure(self):
        self.assertEqual(main.main(['--configure', '--port', '0']), 1)

    def test_directory_lock_excludes_another_operation(self):
        with core.directory_lock(self.settings.server_dir):
            with self.assertRaisesRegex(RuntimeError, 'Another setup operation'):
                with core.directory_lock(self.settings.server_dir):
                    self.fail('The same directory was locked twice')
        with core.directory_lock(self.settings.server_dir):
            pass

    def test_real_windows_preflight_and_configure(self):
        self.install_stub()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.settings.port = str(probe.getsockname()[1])
        core.run_operation(self.settings, 'configure', log=lambda _: None)
        self.assertTrue((Path(self.settings.server_dir) / 'start_server.bat').is_file())

    def test_cancelled_network_timeout_is_cancellation(self):
        event = threading.Event()
        def stalled_request(*args, **kwargs):
            event.set()
            raise TimeoutError('network timed out')
        with patch.object(core.urllib.request, 'urlopen', side_effect=stalled_request):
            with self.assertRaises(core.Cancelled):
                core.download_steamcmd(self.settings.steamcmd_dir, cancel=event)

    def test_broken_junction_can_be_unlinked(self):
        source = self.root / 'source'
        source.mkdir()
        link = core.create_link(self.settings.server_dir, 'addons', 'development', str(source))
        source.rmdir()
        core.remove_link(self.settings.server_dir, 'addons', 'development')
        self.assertFalse(os.path.lexists(link))

    def test_atomic_write_failure_preserves_original(self):
        path = self.root / 'configuration.cfg'
        path.write_text('original')
        with patch.object(core.os, 'replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                core.atomic_write(path, 'replacement')
        self.assertEqual(path.read_text(), 'original')

    def test_symlink_command_uses_directory_switch(self):
        source = self.root / 'source'
        source.mkdir()
        with patch.object(core.subprocess, 'run', return_value=Mock(returncode=1, stdout='', stderr='permission denied')) as run:
            with self.assertRaisesRegex(RuntimeError, 'Developer Mode'):
                core.create_link(self.settings.server_dir, 'addons', 'development', str(source), 'symlink')
        self.assertIn('mklink /D', run.call_args.args[0])

    def test_gui_builds_and_uses_shared_operation(self):
        import gui
        class Page:
            def __init__(self):
                self.services = []
            def update(self):
                pass
        app = gui.SetupApp(Page())
        app.build()
        app.apply_settings(self.settings)
        app.operation.value = 'configure'
        with patch.object(core, 'run_operation') as run:
            asyncio.run(app.run(None))
        self.assertEqual(run.call_args.args[1], 'configure')
        self.assertFalse(app.busy)
        self.assertFalse(app.form.disabled)
        self.assertIn('Completed', app.status.value)


if __name__ == '__main__':
    unittest.main()
