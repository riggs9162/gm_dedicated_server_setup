import os
import shutil
import subprocess
import sys

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

def get_path_input(prompt):
    """Helper function to validate user input for paths."""
    while True:
        path = input(prompt).strip()
        if os.path.exists(path):
            return path
        else:
            print(f"Path '{path}' does not exist. Try again.")

def create_server_cfg(server_name, server_dir):
    """Create or overwrite the server.cfg file."""
    cfg_file = os.path.join(server_dir, 'garrysmod', 'cfg', 'server.cfg')
    
    # Ensure the cfg folder exists
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
        # Ask for SteamCMD installation path
        steamcmd_dir = input("Enter the path where SteamCMD should be installed (e.g., C:\\steamcmd): ").strip()
        os.makedirs(steamcmd_dir, exist_ok=True)
        if not download_steamcmd(steamcmd_dir):
            print("Failed to install SteamCMD. Exiting.")
            sys.exit(1)
    else:
        steamcmd_dir = get_path_input("Enter the existing path to SteamCMD (e.g., C:\\steamcmd): ")
    
    server_dir = input("Enter the folder where you want the server to be installed (absolute path, e.g., C:\\gmodserver): ").strip()
    if not os.path.exists(server_dir):
        try:
            os.makedirs(server_dir)
            print(f"Created server directory at {server_dir}")
        except Exception as e:
            print(f"Failed to create server directory: {e}")
            sys.exit(1)

    server_name = input("Enter a name for your server (this will be the server's hostname): ").strip()

    # New prompts for collection ID, map, gamemode, and max players
    collection_id = input("Enter the Workshop collection ID (leave blank to ignore): ").strip()
    map_name = input("Enter the map name (default: gm_construct, leave blank to use default): ").strip() or "gm_construct"
    gamemode = input("Enter the gamemode (default: sandbox, leave blank to use default): ").strip() or "sandbox"
    max_players = input("Enter the maximum number of players (default: 32, leave blank to use default): ").strip() or "32"

    steamcmd_path = os.path.join(steamcmd_dir, "steamcmd.exe")
    if not os.path.exists(steamcmd_path):
        print(f"SteamCMD not found at {steamcmd_path}. Exiting.")
        sys.exit(1)

    # Run SteamCMD to install the Garry's Mod server
    print("Starting server installation via SteamCMD...")
    try:
        subprocess.run([steamcmd_path, "+login", "anonymous", "+force_install_dir", server_dir, "+app_update", "4020", "validate", "+quit"])
        print("Server installed successfully!")
    except Exception as e:
        print(f"Failed to run SteamCMD: {e}")
        sys.exit(1)

    # Create or update the server.cfg file with the server name
    create_server_cfg(server_name, server_dir)

    # Create the startup script for the server
    start_script = os.path.join(server_dir, "start_server.bat")
    try:
        with open(start_script, "w") as f:
            # Construct the command with the new options
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
