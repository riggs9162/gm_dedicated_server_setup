"""Flet desktop interface for shared server operations and mklink management."""

import asyncio
import os
import queue
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path

import flet as ft
import gmod_server as core


class SetupApp:
    """Keep UI mutations on the event loop and blocking work on a worker thread."""

    def __init__(self, page):
        self.page = page
        self.cancel = threading.Event()
        self.busy = False
        self.last_log = None
        self.picker = ft.FilePicker()
        self.clipboard = ft.Clipboard()
        page.services.extend([self.picker, self.clipboard])
        self.fields = {}
        for key, value in asdict(core.Settings()).items():
            if key != 'lan':
                self.fields[key] = ft.TextField(label=key.replace('_', ' ').capitalize(), value=value,
                                               dense=True, expand=True, password=key == 'password',
                                               can_reveal_password=key == 'password')
        self.fields['collection_id'].label = 'Workshop collection ID or URL'
        self.lan = ft.Checkbox(label='LAN only', value=False)
        self.profile_name = ft.TextField(label='Profile name', value='default', dense=True, expand=True)
        self.profiles = ft.Dropdown(label='Saved profiles', options=[], expand=True, on_select=self.load_profile)
        self.operation = ft.Dropdown(label='Operation', value='install', expand=True,
                                     options=[ft.DropdownOption(key=o, text=o.capitalize()) for o in core.OPERATIONS])
        self.status = ft.Text('Ready.', selectable=True)
        self.progress = ft.ProgressBar(visible=False)
        self.log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        self.run_button = ft.FilledButton('Run operation', on_click=self.run)
        self.cancel_button = ft.OutlinedButton('Cancel', disabled=True, on_click=self.stop)
        self.category = ft.Dropdown(label='Destination', value='addons', expand=True,
                                    options=[ft.DropdownOption(key=v) for v in ('addons', 'gamemodes')])
        self.link_kind = ft.Dropdown(label='Link type', value='junction', expand=True,
                                     options=[ft.DropdownOption(key='junction', text='Junction (mklink /J)'),
                                              ft.DropdownOption(key='symlink', text='Symlink (mklink /D)')])
        self.link_name = ft.TextField(label='Folder name in server', dense=True, expand=True)
        self.link_source = ft.TextField(label='Development source folder', dense=True, expand=True)
        self.links = ft.Column(spacing=6)
        self.map_choices = ft.Dropdown(label='Installed maps', expand=True, on_select=self.select_map)
        self.mode_choices = ft.Dropdown(label='Installed gamemodes', expand=True, on_select=self.select_mode)
        self.form = None
        try:
            self.refresh_profiles()
            last = core.DATA_DIR / 'last-profile.txt'
            if last.exists():
                name = last.read_text(encoding='utf-8').strip()
                self.apply_settings(core.load_profile(name))
                self.profile_name.value = name
                self.profiles.value = name
        except (OSError, ValueError) as error:
            self.status.value = f'Could not restore profile: {error}'

    def apply_settings(self, settings):
        for key, field in self.fields.items():
            field.value = str(getattr(settings, key))
        self.lan.value = settings.lan

    def settings(self):
        return core.validate(core.Settings(**{key: field.value or '' for key, field in self.fields.items()}, lan=bool(self.lan.value)))

    def refresh_profiles(self):
        self.profiles.options = [ft.DropdownOption(key=name) for name in core.list_profiles()]

    def report(self, message):
        self.status.value = message
        self.page.update()

    async def load_profile(self, e):
        try:
            self.apply_settings(core.load_profile(self.profiles.value))
            self.profile_name.value = self.profiles.value
            await self.refresh_content()
            self.report('Profile loaded.')
        except (OSError, ValueError) as error:
            self.report(str(error))

    async def save_profile(self, e):
        try:
            core.save_profile(self.profile_name.value or '', self.settings())
            self.refresh_profiles()
            self.profiles.value = self.profile_name.value.strip()
            self.report('Profile saved. Password remains in server.cfg after configuration.')
        except (OSError, ValueError) as error:
            self.report(str(error))

    async def browse(self, field):
        value = await self.picker.get_directory_path(dialog_title='Select folder')
        if value and not self.busy:
            field.value = value
            self.page.update()

    async def browse_steamcmd(self, e):
        await self.browse(self.fields['steamcmd_dir'])

    async def browse_server(self, e):
        await self.browse(self.fields['server_dir'])
        await self.refresh_content()

    async def browse_source(self, e):
        await self.browse(self.link_source)

    def folder_row(self, field, handler):
        return ft.Row([field, ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip='Browse', on_click=handler)])

    def section(self, title, controls):
        return ft.Container(content=ft.Column([ft.Text(title, size=17, weight=ft.FontWeight.BOLD), *controls], spacing=12,
                                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                            padding=16, border_radius=10, bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE))

    def build(self):
        self.form = ft.Column([
            self.section('Profiles', [self.profiles, ft.Row([self.profile_name, ft.OutlinedButton('Save', on_click=self.save_profile)])]),
            self.section('Server setup', [self.operation,
                ft.Text('Install creates configuration. Update keeps it. Repair validates game files. Configure changes settings only.', size=12),
                self.folder_row(self.fields['steamcmd_dir'], self.browse_steamcmd),
                self.folder_row(self.fields['server_dir'], self.browse_server), self.fields['hostname'],
                ft.Row([self.fields['map_name'], self.fields['gamemode']]),
                ft.Row([self.fields['max_players'], self.fields['port']]), self.fields['collection_id'],
                self.fields['password'], self.lan,
                ft.OutlinedButton('Refresh installed content', on_click=self.refresh_content),
                ft.Row([self.map_choices, self.mode_choices]),
                ft.Text('Discovery includes loose files and linked folders; packed Workshop archives are not indexed.', size=12)]),
            self.section('Development links', [ft.Row([self.category, self.link_kind]), self.link_name,
                self.folder_row(self.link_source, self.browse_source),
                ft.Text('The source stays in your development folder. Removing a managed link preserves its source files.', size=12),
                ft.Row([ft.OutlinedButton('Create link', on_click=self.add_link),
                        ft.OutlinedButton('Refresh links', on_click=self.refresh_content)]), self.links]),
            self.section('Server actions', [ft.Row([
                ft.OutlinedButton('Start server', on_click=self.start_server),
                ft.OutlinedButton('Open folder', on_click=self.open_folder)], wrap=True),
                ft.Row([ft.OutlinedButton('Edit configuration', on_click=self.edit_config),
                        ft.OutlinedButton('Copy connect command', on_click=self.copy_connect)], wrap=True),
                ft.OutlinedButton('Open latest log', on_click=self.open_log)])
        ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        return ft.Column([
            ft.Text("Garry's Mod Server Setup", size=24, weight=ft.FontWeight.BOLD),
            ft.Row([ft.Container(self.form, width=500),
                    ft.Container(ft.Column([ft.Text('Operation output'), self.progress, self.log_view], expand=True),
                                 expand=True, padding=12)], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([self.run_button, self.cancel_button]), self.status
        ], expand=True)

    async def refresh_content(self, e=None):
        try:
            directory = core.clean_path(self.fields['server_dir'].value or '')
            if not directory:
                return
            maps, modes = core.discover_content(directory)
            self.map_choices.options = [ft.DropdownOption(key=m) for m in maps]
            self.mode_choices.options = [ft.DropdownOption(key=m) for m in modes]
            self.links.controls.clear()
            for record in core.list_links(directory):
                button = ft.TextButton('Remove link', data=(directory, record['category'], record['name']), on_click=self.delete_link)
                self.links.controls.append(ft.Column([ft.Text(f"{record['category']}/{record['name']} ({record['kind']}, {record['status']})"),
                                                       ft.Text(record['source'], selectable=True, size=12), button]))
            self.page.update()
        except (OSError, ValueError) as error:
            self.report(str(error))

    async def select_map(self, e):
        self.fields['map_name'].value = self.map_choices.value
        self.page.update()

    async def select_mode(self, e):
        self.fields['gamemode'].value = self.mode_choices.value
        self.page.update()

    async def add_link(self, e):
        try:
            directory = self.settings().server_dir
            path = core.create_link(directory, self.category.value, self.link_name.value or '',
                                    self.link_source.value or '', self.link_kind.value)
            await self.refresh_content()
            self.report(f'Created {path}')
        except (OSError, ValueError, RuntimeError) as error:
            self.report(str(error))

    async def delete_link(self, e):
        try:
            core.remove_link(*e.control.data)
            await self.refresh_content()
            self.report('Link removed; source files preserved.')
        except (OSError, ValueError, RuntimeError) as error:
            self.report(str(error))

    async def run(self, e):
        if self.busy:
            return
        try:
            settings = self.settings()
            core.save_profile(self.profile_name.value or 'default', settings)
            self.refresh_profiles()
            messages = queue.Queue()
            log = core.OperationLog(messages.put, [settings.password])
        except (OSError, ValueError) as error:
            self.report(str(error))
            return
        self.last_log = log.path
        self.busy = True
        self.cancel.clear()
        self.form.disabled = True
        self.run_button.disabled = True
        self.cancel_button.disabled = False
        self.progress.visible = True
        self.progress.value = None
        self.log_view.controls.clear()
        self.status.value = 'Starting...'
        self.page.update()
        task = asyncio.create_task(asyncio.to_thread(core.run_operation, settings, self.operation.value, log, self.cancel))
        stage = 'Starting'
        try:
            while not task.done() or not messages.empty():
                for _ in range(200):
                    try:
                        line = messages.get_nowait()
                    except queue.Empty:
                        break
                    self.log_view.controls.append(ft.Text(line, size=12, font_family='Consolas', selectable=True))
                    if 'Stage:' in line:
                        stage = line.split('Stage:', 1)[1].strip()
                        self.progress.value = None
                    match = re.search(r'(?:download:|progress:)\s*([0-9.]+)', line, re.IGNORECASE)
                    if match:
                        self.progress.value = min(float(match[1]) / 100, 1)
                del self.log_view.controls[:-500]
                self.status.value = f'{"Stopping" if self.cancel.is_set() else stage} | {time.monotonic() - log.started:.0f}s'
                self.page.update()
                await asyncio.sleep(0.1)
            await task
            self.report(f'Completed. Full log: {log.path}')
        except core.Cancelled as error:
            log(str(error))
            self.report(str(error))
        except Exception as error:
            log(f'Failed: {error}')
            self.report(f'Failed: {error}. Log: {log.path}')
        finally:
            self.busy = False
            self.form.disabled = False
            self.run_button.disabled = False
            self.cancel_button.disabled = True
            self.progress.visible = False
            self.page.update()

    async def stop(self, e):
        self.cancel.set()
        self.report('Stopping...')

    async def start_server(self, e):
        try:
            core.start_server(self.settings().server_dir)
            self.report('Server launcher opened.')
        except (OSError, ValueError) as error:
            self.report(str(error))

    async def open_folder(self, e):
        self.open_path(Path(core.clean_path(self.fields['server_dir'].value or '')))

    async def edit_config(self, e):
        self.open_path(Path(core.clean_path(self.fields['server_dir'].value or '')) / 'garrysmod/cfg/server.cfg', edit=True)

    async def open_log(self, e):
        if self.last_log:
            self.open_path(self.last_log, edit=True)
        else:
            self.report('No operation log yet.')

    def open_path(self, path, edit=False):
        try:
            if not path.exists():
                raise ValueError(f'Not found: {path}')
            if edit:
                import subprocess
                subprocess.Popen(['notepad.exe', str(path)])
            else:
                os.startfile(path)
        except (OSError, ValueError) as error:
            self.report(str(error))

    async def copy_connect(self, e):
        try:
            settings = self.settings()
            await self.clipboard.set(f'connect 127.0.0.1:{settings.port}')
            self.report('Copied local connect command. Other computers need this server PC\'s reachable IP address.')
        except (OSError, ValueError) as error:
            self.report(str(error))


async def main(page: ft.Page):
    page.title = "Garry's Mod Server Setup"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window.width = 1180
    page.window.height = 840
    page.window.min_width = 1000
    page.window.min_height = 650
    app = SetupApp(page)
    page.add(app.build())
    await app.refresh_content()
    page.on_disconnect = app.stop


if __name__ == '__main__':
    ft.run(main)
