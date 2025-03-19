from quart import Quart, render_template, request, jsonify, websocket
import json
import socket
import netifaces
import struct
import ipaddress
import tldextract
import time
import shutil
import subprocess
import tomllib
from wayfire.ipc import WayfireSocket
from wayfire.extra.ipc_utils import WayfireUtils
from wayfire.extra.stipc import Stipc

sock = WayfireSocket()
utils = WayfireUtils(sock)
stipc = Stipc(sock)

app = Quart(__name__)

local_network_range = ""
wayremote_port = 5000

file_path = "config/wayremote.ini"
try:
    with open(file_path, "rb") as f:
        config = tomllib.load(f)
    local_network_range = config.get("local_network_range", "Key not found")
except FileNotFoundError:
    print(f"Error: The file '{file_path}' was not found.")
except tomllib.TOMLDecodeError:
    print(f"Error: The file '{file_path}' is not a valid TOML file.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

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
                    ip = link['addr']
                    if not ip.startswith('127.'):  # Skip loopback addresses
                        return ip
        return None
    except Exception as e:
        print(f"Error retrieving local IP: {e}")
        return None

def get_local_network_range():
    local_ip = get_local_ip()
    if not local_ip:
        return None

    netmask = '255.255.255.0'  # Assuming a common local netmask
    ip_bin = struct.unpack('>I', socket.inet_aton(local_ip))[0]
    netmask_bin = struct.unpack('>I', socket.inet_aton(netmask))[0]
    network_bin = ip_bin & netmask_bin
    network_address = socket.inet_ntoa(struct.pack('>I', network_bin))
    cidr_prefix = bin(netmask_bin).count('1')
    return f"{network_address}/{cidr_prefix}"

if not local_network_range:
    local_network_range = get_local_network_range()

# You can allow more than one range. Use the list format: [local_network_range, "192.168.1.0/24"]
ALLOWED_IP_RANGES = [
    local_network_range
]

# Check if IP is within allowed range
def ip_in_allowed_range(ip):
    return any(ipaddress.ip_address(ip) in ipaddress.ip_network(range) for range in ALLOWED_IP_RANGES)

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
            text=True
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


@app.route('/')
async def index():
    return await render_template('index.html')

# Add the /streaming route
@app.route('/streaming')
async def streaming():
    return await render_template('streaming.html')

@app.route('/move_mouse', methods=['POST'])
async def move_mouse():
    try:
        data = await request.get_json()
        x = data.get('x', 0)
        y = data.get('y', 0)
        stipc.move_cursor(x, y)  # Use the correct method to move the cursor
        return jsonify({'status': 'Mouse moved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/keyboard_input', methods=['POST'])
async def keyboard_input():
    try:
        data = await request.get_json()
        key = data.get('key', '')
        print(f'Key pressed: {key}')
        return jsonify({'status': 'Key received'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.websocket('/ws')
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
                    try:
                        cursor_position = stipc.get_cursor_position()
                        print(f"Sending cursor position: {cursor_position}")  # Debugging line
                        await websocket.send(json.dumps(cursor_position))
                    except Exception as e:
                        await websocket.send(json.dumps({"error": f"Failed to get cursor position: {str(e)}"}))
                    continue

                # Handle the move_cursor command
                if command == "move_cursor":
                    if len(args) != 2:
                        await websocket.send(json.dumps({"error": "Invalid arguments for move_cursor"}))
                        continue
                    try:
                        x, y = args
                        stipc.move_cursor(x, y)  # Use the correct method
                        await websocket.send(json.dumps({"status": "Mouse moved"}))
                    except Exception as e:
                        await websocket.send(json.dumps({"error": f"Failed to move cursor: {str(e)}"}))
                    continue

                # Handle the press_key command
                if command == "press_key":
                    if len(args) != 1:
                        await websocket.send(json.dumps({"error": "Invalid arguments for press_key"}))
                        continue
                    try:
                        key = args[0]
                        stipc.press_key(key)  # Use the correct method
                        await websocket.send(json.dumps({"status": f"Key pressed: {key}"}))
                    except Exception as e:
                        await websocket.send(json.dumps({"error": f"Failed to press key: {str(e)}"}))
                    continue

                if command == "shutdown":
                    stipc.run_cmd("shutdown -h now")

                if command == "open_url":
                    if len(args) != 1:
                        await websocket.send(json.dumps({"error": "Invalid arguments for open_url"}))
                        continue
                    url = args[0]  
                    already_open = focus_if_already_open(url)
                    if not already_open:
                        try:
                            edge = "microsoft-edge-stable --app={0}".format(url)
                            if shutil.which("mullvad-exclude"):
                                edge = "mullvad-exclude microsoft-edge-stable --app={0}".format(url)
                            stipc.run_cmd("killall -9 msedge")
                            stipc.run_cmd(edge)
                            time.sleep(2)
                            focused_view_id = sock.get_focused_view()["id"]
                            sock.set_view_fullscreen(focused_view_id, True)
                            await websocket.send(json.dumps({"status": f"Opened URL: {url}"}))
                        except Exception as e:
                            await websocket.send(json.dumps({"error": f"Failed to open URL: {str(e)}"}))
                        continue

                if command == "open_custom_url":
                    if len(args) != 1:
                        await websocket.send(json.dumps({"error": "Invalid arguments for open_url"}))
                        continue
                    url = args[0]  
                    try:
                            edge = "microsoft-edge-stable --app={0}".format(url)
                            stipc.run_cmd("killall -9 msedge")
                            stipc.run_cmd(edge)
                            time.sleep(2)
                            focused_view_id = sock.get_focused_view()["id"]
                            sock.set_view_fullscreen(focused_view_id, True)
                            await websocket.send(json.dumps({"status": f"Opened URL: {url}"}))
                    except Exception as e:
                            await websocket.send(json.dumps({"error": f"Failed to open URL: {str(e)}"}))
                    continue

                # Handle the click_button command
                if command == "click_button":
                    if len(args) != 2:
                        await websocket.send(json.dumps({"error": "Invalid arguments for click_button"}))
                        continue
                    try:
                        button, action = args
                        stipc.click_button(button, action)  # Use the correct method
                        await websocket.send(json.dumps({"status": f"Button clicked: {button} ({action})"}))
                    except Exception as e:
                        await websocket.send(json.dumps({"error": f"Failed to click button: {str(e)}"}))
                    continue

                if command == "volup":
                    vol = VolumeControl()
                    vol.volup()
                if command == "voldown":
                    vol = VolumeControl()
                    vol.voldown()

                # Handle other commands
                if not hasattr(sock, command):
                    await websocket.send(json.dumps({"error": f"Unknown command: {command}"}))
                    continue

                method = getattr(sock, command)

                if not callable(method):
                    await websocket.send(json.dumps({"error": f"{command} is not a callable method"}))
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
