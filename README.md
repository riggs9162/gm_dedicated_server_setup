# Garry's Mod Dedicated Server Setup Script

An automated Python script for quickly setting up Garry's Mod dedicated servers on Windows. **This tool is designed for temporary servers and quick testing purposes only.**

## Important Warnings

### This Script is NOT Production-Ready
- **Intended for temporary servers only** - Perfect for quick LAN parties, testing, or short-term private servers
- **No security hardening** - The script does not implement server security best practices
- **Minimal error handling** - Edge cases may not be handled gracefully
- **No persistence** - Server configurations are basic and may need manual tweaking for long-term use
- **Windows-only** - Currently only supports Windows environments

### Known Limitations & Reliability Issues
- **No Steam Guard support** - Anonymous login only; cannot download workshop content requiring authentication
- **Workshop collection issues** - Workshop collection downloads may fail or be incomplete without proper Steam authentication
- **Network configuration not handled** - You must manually configure firewalls and port forwarding
- **No automatic updates** - Server updates must be manually triggered by re-running the script
- **Limited validation** - Input validation is basic; incorrect paths or settings may cause failures
- **SteamCMD quirks** - First-time SteamCMD runs may require multiple attempts or additional setup
- **Resource requirements not checked** - Script doesn't verify if your system has enough disk space or resources

## What This Script Does

This script automates the following tasks:
1. Downloads and installs SteamCMD (Steam's command-line client)
2. Uses SteamCMD to download Garry's Mod Dedicated Server files
3. Creates a basic `server.cfg` configuration file
4. Generates a `start_server.bat` script to launch your server
5. Configures basic server settings (hostname, map, gamemode, max players, workshop collections)

## Prerequisites

### Required
- **Windows** operating system (Windows 10/11 recommended)
- **Python 3.6 or higher** installed on your system
- **At least 10-15 GB of free disk space** for the server files
- **Stable internet connection** for downloading server files (~5-10 GB download)

### Optional
- **Steam account** (if you need to download workshop content manually)
- **Router access** for port forwarding (if hosting public servers)
- **Firewall knowledge** for configuring Windows Firewall

## How to Use (Beginner's Guide)

### Step 1: Install Python

If you don't have Python installed:
1. Go to https://www.python.org/downloads/
2. Download Python 3.11 or later
3. Run the installer and **check "Add Python to PATH"** during installation
4. Verify installation by opening Command Prompt and typing: `python --version`

### Step 2: Download This Script

1. Download `main.py` from this repository
2. Save it to a folder you can easily find (e.g., `C:\GModServerSetup`)

### Step 3: Run the Script

1. Open **Command Prompt** or **PowerShell**
2. Navigate to the folder where you saved `main.py`:
   ```cmd
   cd C:\GModServerSetup
   ```
3. Run the script:
   ```cmd
   python main.py
   ```

### Step 4: Answer the Prompts

The script will ask you several questions. Here's what to enter:

#### Prompt 1: Reinstall SteamCMD?
```
Do you want to reinstall SteamCMD? (yes/no):
```
- Type `yes` if this is your first time running the script
- Type `no` if you already have SteamCMD installed

#### Prompt 2: SteamCMD Path
```
Enter the path where SteamCMD should be installed (e.g., C:\steamcmd):
```
- Provide a path where SteamCMD will be installed (e.g., `C:\steamcmd`)
- Or, if reinstalling is `no`, provide the path to your existing SteamCMD installation

#### Prompt 3: Server Installation Path
```
Enter the folder where you want the server to be installed (absolute path, e.g., C:\gmodserver):
```
- Choose where to install the Garry's Mod server files (e.g., `C:\gmodserver`)
- This will take 10-15 GB of space

#### Prompt 4: Server Name
```
Enter a name for your server (this will be the server's hostname):
```
- Enter a name that players will see in the server browser (e.g., `My Awesome GMod Server`)

#### Prompt 5: Workshop Collection ID
```
Enter the Workshop collection ID (leave blank to ignore):
```
- If you have a Steam Workshop collection, enter its ID (the numbers in the collection URL)
- Leave blank if you don't need workshop addons
- **Note:** This may not work reliably without Steam authentication

#### Prompt 6: Starting Map
```
Enter the map name (default: gm_construct, leave blank to use default):
```
- Enter a map name (e.g., `gm_flatgrass`, `rp_downtown_v4c_v2`)
- Press Enter to use the default (`gm_construct`)

#### Prompt 7: Gamemode
```
Enter the gamemode (default: sandbox, leave blank to use default):
```
- Enter a gamemode (e.g., `darkrp`, `prophunt`, `terrortown`)
- Press Enter to use the default (`sandbox`)

#### Prompt 8: Max Players
```
Enter the maximum number of players (default: 32, leave blank to use default):
```
- Enter a number (e.g., `16`, `24`, `32`)
- Press Enter to use the default (`32`)

### Step 5: Wait for Installation

- The script will download SteamCMD (if needed) and then download ~5-10 GB of server files
- This may take 10-30 minutes depending on your internet speed
- **Don't close the window while it's downloading!**

### Step 6: Start Your Server

1. Navigate to your server folder (e.g., `C:\gmodserver`)
2. Double-click `start_server.bat`
3. A console window will open showing your server starting up
4. Wait for the message: "Connection to Steam servers successful"

### Step 7: Connect to Your Server

#### For Local/LAN Play:
1. Launch Garry's Mod
2. Open the console (press `~`)
3. Type: `connect localhost` or `connect 127.0.0.1`

#### For Internet Play:
1. **Configure port forwarding** on your router:
   - Forward port `27015` (UDP) to your computer's local IP
   - Forward port `27015` (TCP) to your computer's local IP
2. **Configure Windows Firewall**:
   - Allow `srcds.exe` through the firewall
3. Find your public IP at https://whatismyip.com
4. Give your friends your public IP
5. They connect using: `connect YOUR_PUBLIC_IP`

## Troubleshooting

### "Python is not recognized"
- Python is not installed or not in your PATH
- Reinstall Python and check "Add Python to PATH"

### "SteamCMD failed to download"
- Check your internet connection
- Try running the script again
- Manually download SteamCMD from https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip

### Server won't start or crashes immediately
- Make sure you have enough disk space
- Check that port 27015 isn't already in use
- Try a different map or gamemode
- Run `srcds.exe` directly to see detailed error messages

### Players can't connect
- Verify your firewall allows `srcds.exe`
- Check that port forwarding is configured correctly
- Ensure your server is actually running (check the console window)
- Verify you're giving the correct IP address

### Workshop content not loading
- Anonymous SteamCMD login has limited workshop access
- You may need to manually download workshop items
- Consider using a proper server hosting solution for reliable workshop support

### Server stops responding after a while
- This is a known issue with temporary setups
- Restart the server by closing the console and running `start_server.bat` again
- For stable long-term servers, consider professional hosting or more robust configurations

## File Structure After Setup

```
C:\steamcmd\
  ├── steamcmd.exe
  └── ... (SteamCMD files)

C:\gmodserver\
  ├── srcds.exe              (Server executable)
  ├── start_server.bat       (Generated startup script)
  ├── garrysmod\
  │   ├── cfg\
  │   │   └── server.cfg     (Generated server config)
  │   ├── addons\            (Place custom addons here)
  │   └── ... (game files)
  └── ... (other server files)
```

## 🔧 Advanced Configuration

### Editing server.cfg
After setup, you can manually edit `C:\gmodserver\garrysmod\cfg\server.cfg` to add:
```
sv_password "your_password"          // Set a server password
sv_downloadurl "your_fastdl_url"     // Fast download URL
sv_allowupload 1                     // Allow clients to upload
sv_allowdownload 1                   // Allow clients to download
rcon_password "your_rcon_password"   // Remote console password
```

### Editing start_server.bat
You can modify the launch parameters in `start_server.bat`:
- Change `-maxplayers` to adjust player count
- Add `-nohltv` to disable SourceTV
- Add `+sv_pure 0` to allow custom content
- Change `-tickrate` for different server performance

## Quick Reference: Common Server Commands

In the server console:
- `status` - Show connected players
- `maps *` - List available maps
- `changelevel mapname` - Change the map
- `kick playername` - Kick a player
- `ban playername` - Ban a player
- `quit` - Shut down the server

## Contributing

This is a simple script for temporary servers. If you want to improve it:
- Add better error handling
- Implement proper logging
- Add support for authentication
- Create a config file system
- Add Linux support

## License

This script is provided as-is with no warranties. Use at your own risk.

## Useful Resources

- [Garry's Mod Dedicated Server Documentation](https://wiki.facepunch.com/gmod/Hosting_A_Dedicated_Server)
- [SteamCMD Documentation](https://developer.valvesoftware.com/wiki/SteamCMD)
- [Garry's Mod Workshop](https://steamcommunity.com/app/4000/workshop/)
- [Port Forwarding Guide](https://portforward.com/)

---

**Remember: This script is for temporary servers and testing only. For production servers, consider professional hosting services or more robust server management tools.**
