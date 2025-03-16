from flask import Flask, render_template, request, jsonify

from wayfire.ipc import WayfireSocket
from wayfire.extra.ipc_utils import WayfireUtils 
from wayfire.extra.stipc import Stipc 
from wayfire.extra.wpe import WPE 
from wayfire.core.template import get_msg_template
sock = WayfireSocket()
utils = WayfireUtils(sock) 
stipc = Stipc(sock)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/move_mouse', methods=['POST'])
def move_mouse():
    data = request.json
    x = data.get('x', 0)
    y = data.get('y', 0)
    stipc.move_cursor(x, y)
    return jsonify({'status': 'Mouse moved'})

@app.route('/keyboard_input', methods=['POST'])
def keyboard_input():
    data = request.json
    key = data.get('key', '')
    print(f'Key pressed: {key}')  
    return jsonify({'status': 'Key received'})

if __name__ == '__main__':
    app.run(debug=True)
