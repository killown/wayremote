import base64
import ipaddress
import json
import os
import re
import secrets  # For secret key generation
import shutil
import socket
import struct
import subprocess
import threading
import time
import tomllib
import vdf
import requests
from concurrent.futures import ThreadPoolExecutor
import netifaces
import tldextract
from quart import (
    Quart,
    flash,
    jsonify,
    redirect,
    Response,
    render_template,
    request,
    session,
    url_for,
    websocket,
)
import gi
from pathlib import Path

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf
from quart.helpers import flash
from wayfire.extra.ipc_utils import WayfireUtils
from wayfire.extra.stipc import Stipc
from wayfire.ipc import WayfireSocket
from werkzeug.security import check_password_hash

sock = WayfireSocket()
utils = WayfireUtils(sock)
stipc = Stipc(sock)

app = Quart(__name__)
app.secret_key = secrets.token_hex(32)
app.config["SESSION_TYPE"] = "redis"  # Or 'filesystem' for simpler setup
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1 hour session lifetime

local_network_range = ""
wayremote_port = 5000

# Define the upload directory
UPLOAD_DIR = os.path.expanduser("~/Downloads")

MENU_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates/menu")

config_paths = [
    os.path.expanduser("~/.config/wayremote.ini"),  # First priority
    "config/wayremote.ini",  # Fallback
]

local_network_range = "Key not found"  # Default value

for file_path in config_paths:
    try:
        with open(file_path, "rb") as f:
            config = tomllib.load(f)
            local_network_range = config.get("local_network_range", "Key not found")
            break  # Stop after the first successful read
    except FileNotFoundError:
        print(f"Info: The file '{file_path}' was not found.")
    except tomllib.TOMLDecodeError:
        print(f"Error: The file '{file_path}' is not a valid TOML file.")
    except Exception as e:
        print(f"An unexpected error occurred while reading '{file_path}': {e}")


def get_temporary_cursor_size():
    config_path = os.path.expanduser("~/.config/wayremote.ini")

    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return config.get("temporary_cursor_size", 64)  # Default to 64 if not found
    except FileNotFoundError:
        print(f"Config file not found at {config_path}")
        return 64
    except tomllib.TOMLDecodeError:
        print("Invalid TOML format in config file")
        return 64


def get_cursor_size():
    try:
        result = subprocess.run(
            "gsettings get org.gnome.desktop.interface cursor-size".split(),
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError) as e:
        print(f"Error getting cursor size: {e}")
        return 32  # Fallback to default size


DEFAULT_CURSOR_SIZE = get_cursor_size()
TEMPORARY_CURSOR_SIZE = get_temporary_cursor_size()
RESET_DELAY_SECONDS = 10

# Global timer object (None initially)
reset_timer = None


def launch_steam_game_hidden(app_id):
    try:
        # This is the most reliable method to launch without showing Steam UI
        subprocess.Popen(
            [
                "steam",
                "-silent",  # Prevents Steam UI from showing
                "-applaunch",  # Direct game launch parameter
                app_id,
                "-novid",  # Skip game splash screens (if supported by game)
            ]
        )
        return True
    except Exception as e:
        print(f"Error launching game: {e}")
        return False


def get_steam_installed_games():
    steam_path = ""
    # Common Steam installation locations
    possible_paths = [
        os.path.expanduser("~/.local/share/Steam"),  # Linux
        os.path.expanduser("~/.steam/steam"),  # Alternative Linux
        "C:/Program Files (x86)/Steam",  # Windows
        "C:/Program Files/Steam",  # Alternative Windows
    ]

    # Find Steam installation path
    for path in possible_paths:
        if os.path.exists(path):
            steam_path = path
            break

    if not steam_path:
        return {}

    # Improved exclusion patterns
    exclude_patterns = [
        r"^Proton.*",  # All Proton versions
        r"^Steam Linux Runtime.*",
        r"^Steamworks Common Redist.*",
        r"^Steam Client.*",
        r"^Steam Controller.*",
        r"^SteamVR.*",
        r"^Vulkan.*",
        r"^Pressure Vessel.*",
        r"^Mesa.*",
        r"^DXVK.*",
        r"^BattleEye.*",
        r"^EasyAntiCheat.*",
    ]

    # Parse libraryfolders.vdf
    libraryfolders_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.exists(libraryfolders_path):
        return {}

    with open(libraryfolders_path, "r", encoding="utf-8") as f:
        library_data = vdf.load(f)

    games_dict = {}
    appids = []

    # Check each library folder
    for folder_id, folder_data in library_data.get("libraryfolders", {}).items():
        if not folder_id.isdigit():
            continue

        apps_path = os.path.join(folder_data["path"], "steamapps")

        # Check for appmanifest files
        for filename in os.listdir(apps_path):
            if filename.startswith("appmanifest_") and filename.endswith(".acf"):
                app_id = filename[12:-4]
                appmanifest_path = os.path.join(apps_path, filename)

                with open(appmanifest_path, "r", encoding="utf-8") as f:
                    app_data = vdf.load(f)["AppState"]

                game_name = app_data.get("name", "Unknown")

                # Skip if no name or matches exclusion patterns
                if not game_name or game_name == "Unknown":
                    continue

                # Check against all exclusion patterns
                if any(
                    re.match(pattern, game_name, re.IGNORECASE)
                    for pattern in exclude_patterns
                ):
                    continue

                # Add to dictionary and collect appid for API call
                games_dict[game_name] = {
                    "appid": app_id,
                    "image_url": None,  # Will be filled by API call
                }
                appids.append(app_id)

    # Fetch image URLs from Steam API in batches
    def fetch_game_image(appid):
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get(appid, {}).get("success", False):
                    game_data = data[appid]["data"]
                    # Try multiple image fields in order of preference
                    for image_field in [
                        "header_image",
                        "capsule_image",
                        "capsule_imagev5",
                        "background",
                    ]:
                        if image_field in game_data and game_data[image_field]:
                            return {"appid": appid, "image_url": game_data[image_field]}
        except Exception as e:
            print(f"Error fetching data for appid {appid}: {e}")
        return None

    # Use threading to speed up API calls
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_game_image, appids))

    # Update games_dict with image URLs
    for result in results:
        if result:
            for game_name, game_data in games_dict.items():
                if game_data["appid"] == result["appid"]:
                    games_dict[game_name]["image_url"] = result["image_url"]
                    break
    return {
        game_name: {"appid": data["appid"], "image_url": data["image_url"]}
        for game_name, data in games_dict.items()
    }


def set_cursor_size(size):
    """Set cursor size using gsettings (or wayfire-msg)."""
    subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(size)]
    )


def schedule_cursor_reset():
    """Cancel any pending reset and schedule a new one."""
    global reset_timer

    # Cancel previous timer (if active)
    if reset_timer:
        reset_timer.cancel()

    # Schedule new reset
    reset_timer = threading.Timer(
        RESET_DELAY_SECONDS, set_cursor_size, args=[DEFAULT_CURSOR_SIZE]
    )
    reset_timer.start()


def get_local_ip():
    try:
        # Get all network interfaces
        interfaces = netifaces.interfaces()
        for interface in interfaces:
            # Skip common VPN interface names (adjust as needed)
            if "tun" in interface or "tap" in interface or "vpn" in interface.lower():
                continue  # Skip VPN interfaces

            # Get addresses for the interface
            addresses = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addresses:
                for link in addresses[netifaces.AF_INET]:
                    ip = link["addr"]
                    if not ip.startswith("127."):  # Skip loopback addresses
                        return ip
        return None
    except Exception as e:
        print(f"Error retrieving local IP: {e}")
        return None


def get_local_network_range():
    local_ip = get_local_ip()
    if not local_ip:
        return None

    netmask = "255.255.255.0"  # Assuming a common local netmask
    ip_bin = struct.unpack(">I", socket.inet_aton(local_ip))[0]
    netmask_bin = struct.unpack(">I", socket.inet_aton(netmask))[0]
    network_bin = ip_bin & netmask_bin
    network_address = socket.inet_ntoa(struct.pack(">I", network_bin))
    cidr_prefix = bin(netmask_bin).count("1")
    return f"{network_address}/{cidr_prefix}"


if not local_network_range:
    local_network_range = get_local_network_range()

# You can allow more than one range. Use the list format: [local_network_range, "192.168.1.0/24"]
ALLOWED_IP_RANGES = [local_network_range]

# Check if IP is within allowed range


def ip_in_allowed_range(ip):
    return any(
        ipaddress.ip_address(ip) in ipaddress.ip_network(range)
        for range in ALLOWED_IP_RANGES
    )


def get_domain_name(url):
    extracted = tldextract.extract(url)
    return f"{extracted.domain}"


def focus_if_already_open(streaming):
    streaming = get_domain_name(streaming)
    if streaming == "paramountplus":
        streaming = "paramount"
    print(streaming)
    for view in sock.list_views():
        title = view["title"].lower()
        if len(title.split()) > 1:
            pass
        else:
            continue
        app_id = view["app-id"]
        if "microsoft-edge" in app_id.lower():
            if streaming in title:
                sock.set_focus(view["id"])
                sock.set_view_fullscreen(view["id"], True)
                return True
    return False


class VolumeControl:
    def __init__(self):
        self.volume_step = 25  # Volume change step in percentage
        self.max_volume = 200  # Maximum volume level
        self.min_volume = 0  # Minimum volume level

    def _get_current_volume(self):
        """Get the current volume percentage."""
        result = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True,
            text=True,
        )
        # Extract the volume percentage from the output
        volume_line = result.stdout.splitlines()[0]
        volume_percent = int(volume_line.split("/")[1].strip().replace("%", ""))
        return volume_percent

    def _set_volume(self, volume):
        """Set the volume to a specific percentage."""
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"])

    def volup(self):
        """Increase the volume by the volume step."""
        current_volume = self._get_current_volume()
        new_volume = min(self.max_volume, current_volume + self.volume_step)
        self._set_volume(new_volume)
        print(f"Volume increased to {new_volume}%")

    def voldown(self):
        """Decrease the volume by the volume step."""
        current_volume = self._get_current_volume()
        new_volume = max(self.min_volume, current_volume - self.volume_step)
        self._set_volume(new_volume)
        print(f"Volume decreased to {new_volume}%")


@app.route("/")
async def index():
    return await render_template("index.html")


SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")


@app.route("/apps")
async def apps():
    apps = []
    for app_info in Gio.AppInfo.get_all():
        icon = app_info.get_icon()
        apps.append(
            {
                "name": app_info.get_name(),
                "command": app_info.get_commandline(),
                "icon": icon.get_names()[0]
                if hasattr(icon, "get_names")
                else "application-default-icon",
            }
        )
    return await render_template("apps.html", apps=apps)


def get_icon_path(icon_name, size=64):
    """Get the full path of an icon from its name in GTK4."""
    try:
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display)

        # Handle both string names and Gio.ThemedIcon objects
        if isinstance(icon_name, Gio.ThemedIcon):
            icon = icon_name
        else:
            icon = Gio.ThemedIcon.new(icon_name)

        paintable = theme.lookup_by_gicon(
            icon=icon,
            size=size,
            scale=1,
            direction=Gtk.TextDirection.LTR,
            flags=Gtk.IconLookupFlags.FORCE_REGULAR,
        )

        if paintable:
            icon_file = paintable.get_file()
            if icon_file:
                return icon_file.get_path()

        # Fallback to manual search
        for theme_dir in theme.get_search_path():
            for ext in ["png", "svg"]:
                paths_to_try = [
                    f"{icon_name}.{ext}",
                    f"{size}x{size}/apps/{icon_name}.{ext}",
                    f"scalable/apps/{icon_name}.{ext}",
                ]
                for rel_path in paths_to_try:
                    full_path = os.path.join(theme_dir, rel_path)
                    if os.path.exists(full_path):
                        return full_path

        return None

    except Exception as e:
        print(f"Error in get_icon_path: {e}")
        return None


def load_icon_to_pixbuf(file_path):
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)
        return pixbuf
    except Exception as e:
        print(f"Error loading icon: {e}")
        return None


def pixbuf_to_response(pixbuf):
    try:
        success, buffer = pixbuf.save_to_bufferv("png", [], [])
        if success:
            return Response(buffer, content_type="image/png")
    except Exception as e:
        print(f"Error converting pixbuf to response: {e}")
    return None


@app.route("/app_icon/<icon_name>")
async def app_icon(icon_name):
    try:
        # Handle ThemedIcon objects
        if icon_name.startswith("GThemedIcon") or icon_name.startswith("ThemedIcon"):
            icon_names = []
            if "icon-names=" in icon_name:
                start = icon_name.find("icon-names=") + len("icon-names=")
                end = icon_name.find("]", start)
                icon_names = [
                    n.strip().strip("'\"") for n in icon_name[start:end].split(",")
                ]

            for name in icon_names:
                path = get_icon_path(name)
                if path:
                    pixbuf = load_icon_to_pixbuf(path)
                    if pixbuf:
                        response = pixbuf_to_response(pixbuf)
                        if response:
                            return response

            icon_name = icon_names[0] if icon_names else "application-x-executable"

        # Regular icon lookup
        path = get_icon_path(icon_name)
        if path:
            pixbuf = load_icon_to_pixbuf(path)
            if pixbuf:
                response = pixbuf_to_response(pixbuf)
                if response:
                    return response

        # Fallback SVG (same as before)
        fallback_svg = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <rect width="100" height="100" fill="#333130"/>
            <rect x="10" y="10" width="80" height="80" rx="15" fill="#458588"/>
            <text x="50" y="65" font-family="Arial" font-size="50" 
                  fill="#ebdbb2" text-anchor="middle">{icon_name[0].upper() if icon_name else "?"}</text>
        </svg>
        """
        return Response(fallback_svg, content_type="image/svg+xml")

    except Exception as e:
        print(f"Error in app_icon endpoint: {e}")
        return Response(status=404)


async def serve_fallback_icon():
    """Serve a generic fallback icon"""
    fallback_icon = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
        <path fill="#ebdbb2" d="M2.5 0A.5.5 0 0 0 2 .5V10a.5.5 0 0 0 .5.5h3v1H5a1 1 0 0 0 0 2h6a1 1 0 1 0 0-2h-.5v-1H11a.5.5 0 0 0 .5-.5V.5A.5.5 0 0 0 11 0h-1v-.5A.5.5 0 0 0 9 -.5H7A.5.5 0 0 0 6.5 0V0H2.5zm1 1h7v9H3.5V1zm6.5 0a.5.5 0 0 1 .5.5V3h-1V1.5a.5.5 0 0 1 .5-.5z"/>
    </svg>
    """
    return Response(fallback_icon, mimetype="image/svg+xml")


@app.route("/launch_app", methods=["POST"])
async def launch_app():
    try:
        data = await request.get_json()
        command = data.get("command")

        if command:
            subprocess.Popen(command, shell=True)
            return jsonify({"status": "success"})
        return jsonify({"error": "No command provided"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/login", methods=["GET", "POST"])
async def login():
    if request.method == "POST":
        form = await request.form
        username = form.get("username", "").strip()
        password = form.get("password", "").strip()

        # Load config file
        for config_path in config_paths:
            try:
                with open(config_path, "rb") as f:
                    config = tomllib.load(f)

                # Get credentials from config
                cfg_username = config.get("username", "")
                cfg_password_hash = config.get("password_hash", "")

                if username == cfg_username and check_password_hash(
                    cfg_password_hash, password
                ):
                    session["logged_in"] = True
                    session.permanent = True
                    return redirect(url_for("index"))

            except FileNotFoundError:
                continue  # Try the next path
            except Exception as e:
                print(f"Error loading config: {e}")
                await flash("System error - please try again")
                return await render_template("login.html", error=True)

        await flash("Invalid credentials")
        return await render_template("login.html", error=True)

        await flash("Invalid credentials")
        return await render_template("login.html", error=True)

    return await render_template("login.html", error=False)


@app.route("/logout")
async def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


# Add this before_request handler


@app.before_request
async def check_auth():
    # Allow login page and static files
    if request.path in ["/login"] or request.path.startswith("/static/"):
        return

    # Redirect to login if not authenticated
    if not session.get("logged_in"):
        return redirect(url_for("login"))


@app.route("/scripts")
def list_scripts():
    scripts = []
    for filename in os.listdir(SCRIPTS_DIR):
        if filename.endswith(".py"):
            script_path = os.path.join(SCRIPTS_DIR, filename)
            with open(script_path, "r") as file:
                content = file.read()
                # Extract the label from the template
                label_match = re.search(r"LABEL:\s*(.*)", content)
                label = (
                    label_match.group(1).strip()
                    if label_match
                    else filename.replace(".py", "")
                )
                scripts.append({"filename": filename, "label": label})
    return scripts


# Route to serve the commands.html page


# Route to display Steam games
@app.route("/steam")
async def steam_games():
    # Get installed Steam games (using the function we created earlier)
    games = get_steam_installed_games()
    return await render_template("steam.html", games=games)


@app.route("/commands")
async def commands():
    return await render_template("commands.html")


@app.route("/menu")
async def menu():
    custom_cards = []
    card_scripts = []

    menu_dir = Path("templates/menu")
    print(f"DEBUG: Scanning menu directory: {menu_dir.absolute()}")

    if menu_dir.exists():
        for file in menu_dir.glob("*.html"):
            try:
                with open(file, "r") as f:
                    content = f.read()

                # Extract all metadata
                metadata = {
                    "title": re.search(r"<!--\s*TITLE:\s*(.*?)\s*-->", content),
                    "icon": re.search(r"<!--\s*ICON:\s*(.*?)\s*-->", content),
                    "url": re.search(r"<!--\s*URL:\s*(.*?)\s*-->", content),
                    "position": re.search(r"<!--\s*POSITION:\s*(\d+)\s*-->", content),
                    "handler": re.search(r"<!--\s*HANDLER:\s*(.*?)\s*-->", content),
                }

                # Extract JavaScript if exists
                js_match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
                if js_match:
                    card_scripts.append(js_match.group(1))
                    content = re.sub(
                        r"<script>.*?</script>", "", content, flags=re.DOTALL
                    )

                # Skip if required metadata is missing
                if not all([metadata["title"], metadata["icon"], metadata["url"]]):
                    print(f"WARNING: Missing required metadata in {file.name}")
                    continue

                card_data = {
                    "name": metadata["title"].group(1).strip(),
                    "icon": metadata["icon"].group(1).strip(),
                    "url": metadata["url"].group(1).strip(),
                    "content": content,
                    "position": int(metadata["position"].group(1))
                    if metadata["position"]
                    else None,
                }
                print(
                    f"DEBUG: Loaded card - {card_data['name']} (Position: {card_data['position']})"
                )
                custom_cards.append(card_data)

            except Exception as e:
                print(f"ERROR: Failed to process {file.name}: {str(e)}")
                continue

    # Sort cards by position (None positions go last)
    custom_cards.sort(
        key=lambda x: x["position"] if x["position"] is not None else float("inf")
    )
    print(f"DEBUG: Loaded {len(custom_cards)} cards (sorted)")

    return await render_template(
        "menu.html", custom_cards=custom_cards, card_scripts=card_scripts
    )


@app.route("/move_mouse", methods=["POST"])
async def move_mouse():
    try:
        data = await request.get_json()
        x = data.get("x", 0)
        y = data.get("y", 0)
        stipc.move_cursor(x, y)  # Use the correct method to move the cursor
        return jsonify({"status": "Mouse moved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/keyboard_input", methods=["POST"])
async def keyboard_input():
    try:
        data = await request.get_json()
        key = data.get("key", "")
        print(f"Key pressed: {key}")
        return jsonify({"status": "Key received"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.websocket("/ws")
async def handle_client():
    client_ip = websocket.remote_addr

    # close the connection if the ip isn't whitin the allowed range
    if not ip_in_allowed_range(client_ip):
        await websocket.close(code=1000)
        return

    while True:
        try:
            # Receive a message from the WebSocket client
            message = await websocket.receive()
            print(f"Received message: {message}")

            try:
                data = json.loads(message)
                command = data.get("command")
                args = data.get("args", [])

                if command is None:
                    await websocket.send(json.dumps({"error": "Command not specified"}))
                    continue

                # Handle the get_cursor_position command
                if command == "get_cursor_position":
                    set_cursor_size(TEMPORARY_CURSOR_SIZE)
                    # Reset after delay (cancels any pending reset)
                    schedule_cursor_reset()
                    try:
                        cursor_position = sock.get_cursor_position()
                        print(
                            f"Sending cursor position: {cursor_position}"
                        )  # Debugging line
                        await websocket.send(json.dumps(cursor_position))
                    except Exception as e:
                        await websocket.send(
                            json.dumps(
                                {"error": f"Failed to get cursor position: {str(e)}"}
                            )
                        )
                    continue

                # Handle the move_cursor command
                if command == "move_cursor":
                    if len(args) != 2:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for move_cursor"})
                        )
                        continue
                    try:
                        x, y = args
                        stipc.move_cursor(x, y)  # Use the correct method
                        await websocket.send(json.dumps({"status": "Mouse moved"}))
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to move cursor: {str(e)}"})
                        )
                    continue

                # Handle the press_key command
                if command == "press_key":
                    if len(args) != 1:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for press_key"})
                        )
                        continue
                    try:
                        key = args[0]
                        stipc.press_key(key)  # Use the correct method
                        await websocket.send(
                            json.dumps({"status": f"Key pressed: {key}"})
                        )
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to press key: {str(e)}"})
                        )
                    continue

                # set window fullscreen
                if command == "set_fullscreen":
                    focused_view_id = sock.get_focused_view()["id"]
                    sock.set_view_fullscreen(focused_view_id, True)

                # Handle the execute_script command
                if command == "execute_script":
                    script = args[0] if args else None
                    if not script:
                        await websocket.send(
                            json.dumps({"error": "Script not specified"})
                        )
                        continue

                    script_path = os.path.join(SCRIPTS_DIR, script)

                    if not os.path.exists(script_path):
                        await websocket.send(json.dumps({"error": "Script not found"}))
                        continue

                    try:
                        # Execute the script
                        os.system(f"python {script_path}")
                        await websocket.send(
                            json.dumps({"message": f"Executed script: {script}"})
                        )
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to execute script: {str(e)}"})
                        )
                    continue

                if command == "open_steam_game":
                    sock.close_view(sock.get_focused_view()["id"])
                    app_id = args[0] if args else None
                    if app_id:
                        launch_steam_game_hidden(app_id)
                        await websocket.send(
                            json.dumps(
                                {
                                    "status": "success",
                                    "message": f"Launching Steam game {app_id}",
                                }
                            )
                        )

                if command == "shutdown":
                    stipc.run_cmd("shutdown -h now")

                # Handle the upload_file command
                if command == "upload_file":
                    if not args or "filename" not in args or "file_data" not in args:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for upload_file"})
                        )
                        continue

                    filename = args["filename"]
                    file_data = args["file_data"]

                    try:
                        # Decode the base64 file data
                        file_bytes = base64.b64decode(file_data)
                        file_path = os.path.join(UPLOAD_DIR, filename)

                        # Save the file to the upload directory
                        with open(file_path, "wb") as file:
                            file.write(file_bytes)

                        await websocket.send(
                            json.dumps(
                                {"message": f"File uploaded successfully: {filename}"}
                            )
                        )
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to upload file: {str(e)}"})
                        )
                    continue

                if command == "close_view":
                    focused_view_id = None
                    try:
                        focused_view_id = sock.get_focused_view()["id"]
                    except Exception as e:
                        print(e)
                    if focused_view_id:
                        sock.close_view(focused_view_id)

                if command == "open_url":
                    if len(args) != 1:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for open_url"})
                        )
                        continue
                    url = args[0]
                    already_open = focus_if_already_open(url)
                    if not already_open:
                        try:
                            edge = f"XDG_SESSION_TYPE=wayland MOZ_ENABLE_WAYLAND=1 GDK_BACKEND=wayland microsoft-edge-stable --enable-features=UseOzonePlatform --ozone-platform=wayland --gtk-version=4 --app={url}"
                            if shutil.which("mullvad-exclude"):
                                edge = f"XDG_SESSION_TYPE=wayland MOZ_ENABLE_WAYLAND=1 GDK_BACKEND=wayland mullvad-exclude microsoft-edge-stable --enable-features=UseOzonePlatform --ozone-platform=wayland --gtk-version=4 --app={url}"
                            stipc.run_cmd("killall -9 msedge")
                            stipc.run_cmd(edge)
                            time.sleep(2)
                            focused_view_id = sock.get_focused_view()["id"]
                            sock.set_view_fullscreen(focused_view_id, True)
                            await websocket.send(
                                json.dumps({"status": f"Opened URL: {url}"})
                            )
                        except Exception as e:
                            await websocket.send(
                                json.dumps({"error": f"Failed to open URL: {str(e)}"})
                            )
                        continue

                if command == "open_custom_url":
                    if len(args) != 1:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for open_url"})
                        )
                        continue
                    url = args[0]
                    try:
                        edge = f"XDG_SESSION_TYPE=wayland MOZ_ENABLE_WAYLAND=1 GDK_BACKEND=wayland microsoft-edge-stable --enable-features=UseOzonePlatform --ozone-platform=wayland --gtk-version=4 --app={url}"
                        if shutil.which("mullvad-exclude"):
                            edge = f"XDG_SESSION_TYPE=wayland MOZ_ENABLE_WAYLAND=1 GDK_BACKEND=wayland mullvad-exclude microsoft-edge-stable --enable-features=UseOzonePlatform --ozone-platform=wayland --gtk-version=4 --app={url}"
                        stipc.run_cmd("killall -9 msedge")
                        stipc.run_cmd(edge)
                        time.sleep(2)
                        focused_view_id = sock.get_focused_view()["id"]
                        sock.set_view_fullscreen(focused_view_id, True)
                        await websocket.send(
                            json.dumps({"status": f"Opened URL: {url}"})
                        )
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to open URL: {str(e)}"})
                        )
                    continue

                # Handle the click_button command
                if command == "click_button":
                    if len(args) != 2:
                        await websocket.send(
                            json.dumps({"error": "Invalid arguments for click_button"})
                        )
                        continue
                    try:
                        button, action = args
                        stipc.click_button(button, action)  # Use the correct method
                        await websocket.send(
                            json.dumps(
                                {"status": f"Button clicked: {button} ({action})"}
                            )
                        )
                    except Exception as e:
                        await websocket.send(
                            json.dumps({"error": f"Failed to click button: {str(e)}"})
                        )
                    continue

                if command == "volup":
                    vol = VolumeControl()
                    vol.volup()
                if command == "voldown":
                    vol = VolumeControl()
                    vol.voldown()

                # Handle other commands
                if not hasattr(sock, command):
                    await websocket.send(
                        json.dumps({"error": f"Unknown command: {command}"})
                    )
                    continue

                method = getattr(sock, command)

                if not callable(method):
                    await websocket.send(
                        json.dumps({"error": f"{command} is not a callable method"})
                    )
                    continue

                if not isinstance(args, (list, tuple)):
                    args = [args]

                try:
                    result = method(*args)
                    json_result = json.dumps(result, default=str)
                    await websocket.send(json_result)
                except Exception as e:
                    await websocket.send(json.dumps({"error": str(e)}))

            except json.JSONDecodeError as e:
                await websocket.send(json.dumps({"error": f"Invalid JSON: {str(e)}"}))

        except Exception as e:
            print(f"WebSocket error: {e}")
            await websocket.close(code=1000)
            break


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=wayremote_port)
