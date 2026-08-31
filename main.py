import os
import shutil
import subprocess
import sys

GMOD_DEDICATED_APP_ID = "4020"
MAX_INSTALL_ATTEMPTS = 3

def download_steamcmd(steamcmd_dir):
    """Download and extract SteamCMD to the specified directory."""
    print("Downloading SteamCMD...")
    steamcmd_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
    zip_file_path = os.path.join(steamcmd_dir, "steamcmd.zip")

    try:
        import urllib.request
        urllib.request.urlretrieve(steamcmd_url, zip_file_path)
        print("Download complete!")
    except Exception as e:
        print(f"Failed to download SteamCMD: {e}")
        return False

    try:
        shutil.unpack_archive(zip_file_path, steamcmd_dir)
        os.remove(zip_file_path)
        print(f"SteamCMD installed at {steamcmd_dir}")
        return True
    except Exception as e:
        print(f"Failed to extract SteamCMD: {e}")
        return False

def clean_path(raw_path):
    """Normalise a user-supplied path: trim whitespace, strip pasted quotes, expand variables and drop trailing separators."""
    path = raw_path.strip().strip('"').strip("'")
    if not path:
        return ""

    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if len(path) > 3:
        path = path.rstrip("\\/")

    return path

def get_path_input(prompt):
    """Prompt until the user supplies a path that exists, returning it normalised."""
    while True:
        path = clean_path(input(prompt))
        if path and os.path.exists(path):
            return path
        print(f"Path '{path}' does not exist. Try again.")

def run_steamcmd(steamcmd_path, arguments):
    """Run SteamCMD with the given argument list and return its exit code."""
    return subprocess.run([steamcmd_path] + arguments).returncode

def purge_appcache(steamcmd_dir):
    """Delete SteamCMD's appcache directory, whose stale contents are the usual cause of 'Missing configuration'."""
    appcache_dir = os.path.join(steamcmd_dir, "appcache")
    if not os.path.isdir(appcache_dir):
        return

    try:
        shutil.rmtree(appcache_dir)
        print("Cleared SteamCMD's appcache.")
    except OSError as e:
        print(f"Could not clear appcache at {appcache_dir}: {e}")

def bootstrap_steamcmd(steamcmd_path):
    """Run SteamCMD on its own so it self-updates first; commands passed on a fresh install's very first run get dropped."""
    print("Updating SteamCMD itself (this can take a minute on a fresh install)...")
    run_steamcmd(steamcmd_path, ["+quit"])

def install_gmod_server(steamcmd_dir, steamcmd_path, server_dir):
    """Install or update the Garry's Mod dedicated server, clearing the appcache and retrying between failed attempts.

    force_install_dir must be passed before login: SteamCMD applies it to the session that follows it, so setting
    it afterwards leaves app_update without a valid install target.
    """
    arguments = [
        "+force_install_dir", server_dir,
        "+login", "anonymous",
        "+app_update", GMOD_DEDICATED_APP_ID, "validate",
        "+quit",
    ]

    for attempt in range(1, MAX_INSTALL_ATTEMPTS + 1):
        print(f"Installing Garry's Mod dedicated server (attempt {attempt} of {MAX_INSTALL_ATTEMPTS})...")
        try:
            exit_code = run_steamcmd(steamcmd_path, arguments)
        except Exception as e:
            print(f"Failed to run SteamCMD: {e}")
            return False

        if exit_code == 0 and os.path.exists(os.path.join(server_dir, "srcds.exe")):
            return True

        print(f"SteamCMD did not complete the install (exit code {exit_code}).")
        if attempt < MAX_INSTALL_ATTEMPTS:
            purge_appcache(steamcmd_dir)

    return False

def create_server_cfg(server_name, server_dir):
    """Create or overwrite the server.cfg file."""
    cfg_file = os.path.join(server_dir, 'garrysmod', 'cfg', 'server.cfg')
    cfg_dir = os.path.dirname(cfg_file)
    os.makedirs(cfg_dir, exist_ok=True)

    try:
        with open(cfg_file, 'w') as cfg:
            cfg.write(f"hostname \"{server_name}\"\n")
            print(f"server.cfg updated with hostname: {server_name}")
    except Exception as e:
        print(f"Failed to create or update server.cfg: {e}")

def main():
    print("===================================")
    print("Garry's Mod Dedicated Server Setup")
    print("===================================")

    reinstall = input("Do you want to reinstall SteamCMD? (yes/no): ").strip().lower()

    steamcmd_dir = ""

    if reinstall == "yes":
        steamcmd_dir = clean_path(input("Enter the path where SteamCMD should be installed (e.g., C:\\steamcmd): "))
        os.makedirs(steamcmd_dir, exist_ok=True)
        if not download_steamcmd(steamcmd_dir):
            print("Failed to install SteamCMD. Exiting.")
            sys.exit(1)
    else:
        steamcmd_dir = get_path_input("Enter the existing path to SteamCMD (e.g., C:\\steamcmd): ")

    server_dir = clean_path(input("Enter the folder where you want the server to be installed (absolute path, e.g., C:\\gmodserver): "))
    if not os.path.exists(server_dir):
        try:
            os.makedirs(server_dir)
            print(f"Created server directory at {server_dir}")
        except Exception as e:
            print(f"Failed to create server directory: {e}")
            sys.exit(1)

    server_name = input("Enter a name for your server (this will be the server's hostname): ").strip()

    collection_id = input("Enter the Workshop collection ID (leave blank to ignore): ").strip()
    map_name = input("Enter the map name (default: gm_construct, leave blank to use default): ").strip() or "gm_construct"
    gamemode = input("Enter the gamemode (default: sandbox, leave blank to use default): ").strip() or "sandbox"
    max_players = input("Enter the maximum number of players (default: 32, leave blank to use default): ").strip() or "32"

    steamcmd_path = os.path.join(steamcmd_dir, "steamcmd.exe")
    if not os.path.exists(steamcmd_path):
        print(f"SteamCMD not found at {steamcmd_path}. Exiting.")
        sys.exit(1)

    bootstrap_steamcmd(steamcmd_path)

    if not install_gmod_server(steamcmd_dir, steamcmd_path, server_dir):
        print("")
        print("The server files were not installed. Things worth checking:")
        print(f"  - Free space on the drive holding {server_dir}; the install needs roughly 15 GB.")
        print("  - Install to a plain local folder, not a network drive or a cloud-synced folder.")
        print(f"  - Run it by hand to read the full output: \"{steamcmd_path}\" +force_install_dir \"{server_dir}\" +login anonymous +app_update {GMOD_DEDICATED_APP_ID} validate +quit")
        sys.exit(1)

    print("Server installed successfully!")

    create_server_cfg(server_name, server_dir)

    start_script = os.path.join(server_dir, "start_server.bat")
    try:
        with open(start_script, "w") as f:
            command = (
                f'start "SRCDS" /B srcds.exe -game garrysmod -conlog -port 27015 '
                f'-console -conclearlog -condebug -tvdisable -maxplayers {max_players} '
                f'+gamemode {gamemode} +r_hunkalloclightmaps 0 +map {map_name} -tickrate 66 +fps_max 66'
            )

            if collection_id:
                command += f' +host_workshop_collection "{collection_id}"'

            command += " +sv_lan 0\n"

            f.write(command)
            print(f"Start script created at {start_script}")
    except Exception as e:
        print(f"Failed to create start script: {e}")
        sys.exit(1)

    print("Setup complete! Run 'start_server.bat' in your server directory to start your server.")

if __name__ == "__main__":
    main()
