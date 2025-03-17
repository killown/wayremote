from quart import Quart, render_template, request, jsonify, websocket
import json
import socket
import struct
import ipaddress
import os
from wayfire.ipc import WayfireSocket
from wayfire.extra.ipc_utils import WayfireUtils
from wayfire.extra.stipc import Stipc

sock = WayfireSocket()
utils = WayfireUtils(sock)
stipc = Stipc(sock)

app = Quart(__name__)

# Helper function to get local network range
def get_local_network_range():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    netmask = '255.255.255.0'  # Assuming a common local netmask
    ip_bin = struct.unpack('>I', socket.inet_aton(local_ip))[0]
    netmask_bin = struct.unpack('>I', socket.inet_aton(netmask))[0]
    network_bin = ip_bin & netmask_bin
    network_address = socket.inet_ntoa(struct.pack('>I', network_bin))
    cidr_prefix = bin(netmask_bin).count('1')
    return f"{network_address}/{cidr_prefix}"

local_network_range = get_local_network_range()

ALLOWED_IP_RANGES = [
    local_network_range
]

# Check if IP is within allowed range
def ip_in_allowed_range(ip):
    return any(ipaddress.ip_address(ip) in ipaddress.ip_network(range) for range in ALLOWED_IP_RANGES)

@app.route('/')
async def index():
    return await render_template('index.html')

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

    ip_check_enabled = os.getenv('WAYFIRE_IPC_LAN_ONLY', '').lower() in ('true', '1', 't')

    if ip_check_enabled and not ip_in_allowed_range(client_ip):
        await websocket.close(code=1000)  # Normal closure
        return

    while True:
        try:
            # Receive a message from the WebSocket client
            message = await websocket.receive()
            print(f"Received message: {message}")  # Debugging line

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
                    # Pass arguments to the method
                    result = method(*args)
                    json_result = json.dumps(result, default=str)
                    await websocket.send(json_result)
                except Exception as e:
                    await websocket.send(json.dumps({"error": str(e)}))

            except json.JSONDecodeError as e:
                await websocket.send(json.dumps({"error": f"Invalid JSON: {str(e)}"}))

        except Exception as e:
            print(f"WebSocket error: {e}")
            await websocket.close(code=1000)  # Normal closure
            break

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)  # Port remains 5000
