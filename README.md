# Garry's Mod Server Setup

A Windows tool for temporary Garry's Mod servers, LAN sessions and local development. The desktop GUI and command line share the same validation and operation runner.

## Run

Requires **Windows and Python 3.12 or newer**.

```powershell
python -m pip install -r requirements.txt
python gui.py
```

The console interface uses only the Python standard library:

```powershell
python main.py
python main.py --help
```

## Operations

| Mode | What it does |
| --- | --- |
| Install | Downloads SteamCMD if missing, updates SteamCMD, installs the server and writes configuration. Existing server downloads can be continued. |
| Update | Updates an existing server without rewriting its configuration or launcher. |
| Repair | Runs SteamCMD file validation on an existing server. Configuration and launcher generation are skipped. Steam-managed files may be restored by validation. |
| Configure | Updates settings and the launcher without downloading anything or running SteamCMD. Requires an installed server. |

Preflight checks verify writable directories, available disk space, the selected port and whether the selected server is running. The initial installation requires 15 GiB free; updates and repairs require a 2 GiB working margin. These are estimates, and Workshop content may require more space. File locks prevent concurrent setup operations using the same server or SteamCMD folder.

SteamCMD is bootstrapped before installation. Its exit status and installation confirmation are checked. Failed installs retry up to three times; a stale appcache is cleared only when output reports `Missing configuration`. Cancel stops the workflow and running SteamCMD process tree, without retrying. Network reads have a ten-second timeout, so stopping a stalled ZIP download may take that long. Server download files are kept for the next attempt.

## Configuration and profiles

The GUI saves the current profile before running and restores the last saved profile on startup. Use **Save** to save a named profile without running an operation. Both interfaces store profiles under `%LOCALAPPDATA%\GModServerSetup`.

Configure manages hostname, server password and LAN mode in a marked block at the end of `garrysmod\cfg\server.cfg`. Existing custom commands and comments are retained. The later managed settings take precedence over earlier values. The launcher contains map, gamemode, port, player count and the optional Workshop collection.

Changed configuration and launcher files receive timestamped `.bak` copies beside the originals. Writes are atomic per file. A failure stops the operation and is reported; if an earlier stage completed, its changes remain and its backups are available.

Passwords are stored in `server.cfg`, as required by the server, and are omitted from profile JSON and launch commands. Loading a profile reads its configured password from `server.cfg`. Use the masked GUI field or `--ask-password`; an empty password removes password protection when you Configure or Install.

Examples:

```powershell
python main.py --install --server-dir C:\servers\sandbox --hostname "Sandbox testing" --save-profile sandbox
python main.py --profile sandbox --update
python main.py --profile sandbox --repair
python main.py --profile sandbox --configure --map-name gm_flatgrass --lan --save-profile sandbox
python main.py --profile sandbox --configure --ask-password
python main.py --list-profiles
```

Update and Repair keep the server's current configuration. Edited form settings take effect when you select Configure or Install. Profiles are saved explicitly in unattended CLI runs with `--save-profile`.

## Development folders and mklink

Link a local addon or gamemode directly into the server without copying it. In the GUI, choose the source folder, destination category, folder name and link type, then select **Create link**.

- **Junction** uses `mklink /J` and is the default for local development folders.
- **Directory symlink** uses `mklink /D`. Windows may require Developer Mode or an elevated process; failures are shown without automatically elevating.

The destination is `<server>\garrysmod\addons\<name>` or `<server>\garrysmod\gamemodes\<name>`. Choose the actual addon or gamemode root as the source, not its parent directory. Editing files through either path edits the same source files.

```powershell
python main.py --profile sandbox --link addons my_addon "D:\Development\my_addon"
python main.py --profile sandbox --link gamemodes my_mode "D:\Development\my_mode" --link-type symlink
python main.py --profile sandbox --list-links
python main.py --profile sandbox --unlink addons my_addon
```

A `.setup-links.json` file in the server folder tracks managed links. The GUI lists their source, type and status. Existing destinations are never replaced. Removal checks that a registered destination is still a link to the original source, then removes only that link. Missing links can have their stale records removed; changed destinations are left untouched. Unregistered links are not removed by this tool.

Source and destination cannot contain one another. Content directories redirected outside the server are rejected. Link paths containing percent signs, quotes or control characters are rejected because `mklink` runs through the Windows command interpreter.

See [Microsoft's mklink documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink) for the Windows link types.

## Content, launch actions and logs

**Refresh installed content** discovers loose `.bsp` maps and gamemode folders, including linked development addons. Select a result to fill the map or gamemode field, or type a custom name. Packed Workshop `.gma` archives are not indexed.

The Workshop field accepts either a numeric collection ID or its Steam Community URL. The collection is passed to the server at launch; setup does not download or authenticate Workshop content separately.

GUI actions open the server folder, edit `server.cfg`, launch the server, copy a local connect command, or open the latest log. CLI equivalents include:

```powershell
python main.py --profile sandbox --discover
python main.py --profile sandbox --start
python main.py --profile sandbox --update --start
```

The GUI displays the current stage, elapsed time and percentage when download output supplies one. It keeps the last 500 lines visible while saving the complete timestamped log under `%LOCALAPPDATA%\GModServerSetup\logs`. Known server passwords are redacted from operation logs. The CLI prints the full log path before running.

Connect locally with `connect 127.0.0.1:27015`, substituting the configured port. Other PCs need a reachable address for the server PC. Firewall and router configuration remain manual; the tool does not test internet reachability or change networking rules.

## Development and verification

```powershell
python -m unittest -v
python -m py_compile main.py gui.py gmod_server.py
```

Tests use temporary directories and mock SteamCMD downloads. They cover configuration preservation, backups, validation, cancellation, stage failures, profile handling, diagnostics, CLI/GUI integration and real Windows junction creation/removal. The real directory symlink test is skipped when Windows denies symlink privileges. Tests do not install or launch Garry's Mod.

Files:

- `gmod_server.py`: shared operations, profiles, validation, logs and managed links.
- `gui.py`: Flet desktop front end with queued worker output.
- `main.py`: interactive prompts and unattended CLI arguments.
- `test_server.py`: regression tests.

The supported GUI dependency series is pinned in `requirements.txt`. This remains a local setup utility, with no service manager, crash restarter, remote administration or automatic scheduling.
