from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# Relay Server के लिए SocketIO सेटअप (CORS allowed ताकि कोई भी कनेक्ट कर सके)
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Relay Remote Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body, html { margin: 0; padding: 0; overflow: hidden; height: 100%; width: 100%; background-color: #000; }
        #video-feed { display: none; position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; object-fit: fill; cursor: pointer; z-index: 1; }
        #control-container { position: absolute; top: 40%; left: 50%; transform: translate(-50%, -50%); text-align: center; z-index: 5; }
    </style>
    <script>
        // Another PC से Relay Server को कनेक्ट करना
        const socket = io();

        // 1. Relay Server से वीडियो फ्रेम रिसीव करना
        socket.on('video_frame', function(data) {
            const img = document.getElementById("video-feed");
            img.src = "data:image/jpeg;base64," + data.image;
        });

        // 2. Another PC से क्लिक कमांड Relay Server को भेजना
        function sendClick(event) {
            const img = document.getElementById("video-feed");
            const rect = img.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width;
            const y = (event.clientY - rect.top) / rect.height;
            socket.emit('mouse_click', { x: x, y: y });
        }

        // 3. स्क्रॉल कमांड Relay Server को भेजना
        window.addEventListener('wheel', function(event) {
            event.preventDefault();
            const direction = event.deltaY > 0 ? 'down' : 'up';
            socket.emit('mouse_scroll', { direction: direction });
        }, { passive: false });

        // 4. कीबोर्ड कमांड Relay Server को भेजना
        function sendText(text) {
            socket.emit('keyboard_input', { text: text });
        }

        window.addEventListener('keydown', function(event) {
            const specialKeys = ['Backspace', 'Enter', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape', 'Tab'];
            
            // Backspace से ब्राउज़र को पीछे जाने से रोकना
            if (event.key === 'Backspace') event.preventDefault();
            
            if (event.key.length === 1 || specialKeys.includes(event.key)) {
                sendText(event.key);
            }
        });

        function showScreen() {
            document.getElementById('video-feed').style.display = "block";
            document.getElementById('control-container').style.display = "none";
        }
    </script>
</head>
<body>
    <div id="control-container">
        <h2 style="color:white;">Connected to Relay Server</h2>
        <button onclick="showScreen()" style="width: 150px; height: 70px; border-radius: 35px; background-color: dodgerblue; color: white; font-size: 18px; border: none; cursor: pointer;">Show Screen</button>
    </div>
    <img id="video-feed" onclick="sendClick(event)">
</body>
</html>
'''

@app.route('/bill')
def index():
    return render_template_string(HTML_PAGE)

# --- RELAY LOGIC ---

@socketio.on('video_frame')
def handle_video_frame(data):
    emit('video_frame', data, broadcast=True, include_self=False)

@socketio.on('mouse_click')
def handle_click(data):
    emit('execute_click', data, broadcast=True, include_self=False)

@socketio.on('mouse_scroll')
def handle_scroll(data):
    emit('execute_scroll', data, broadcast=True, include_self=False)

@socketio.on('keyboard_input')
def handle_keyboard(data):
    emit('execute_keyboard', data, broadcast=True, include_self=False)

if __name__ == '__main__':
    print("Relay Server is running on http://0.0.0.0:5000/bill")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
