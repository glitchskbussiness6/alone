from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# ping_timeout और ping_interval
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=15, ping_interval=5)

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Relay Remote Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body, html { margin: 0; padding: 0; overflow: hidden; height: 100%; width: 100%; background-color: #000; }
        #video-canvas { display: none; position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; object-fit: contain; cursor: crosshair; z-index: 1; }
        #control-container { position: absolute; top: 40%; left: 50%; transform: translate(-50%, -50%); text-align: center; z-index: 5; }
    </style>
    <script>
        const socket = io();
        let canvas, ctx;

        window.onload = function() {
            canvas = document.getElementById("video-canvas");
            ctx = canvas.getContext("2d");
            // डिफ़ॉल्ट रूप से Canvas का रिज़ॉल्यूशन सेट कर दें
            canvas.width = 1280;
            canvas.height = 720;
        };

        // 1. Receive & Draw Frame Instantly
        socket.on('video_frame', function(data) {
            if (!data.image) return;
            const blob = new Blob([data.image], { type: "image/jpeg" });
            createImageBitmap(blob).then(function(imgBitmap) {
                if(canvas.width !== imgBitmap.width) {
                    canvas.width = imgBitmap.width;
                    canvas.height = imgBitmap.height;
                }
                ctx.drawImage(imgBitmap, 0, 0);
            }).catch(e => console.log(e));
        });

        // 2. Black Screen on Pause Feature
        socket.on('stream_paused', function() {
            if(ctx && canvas) {
                ctx.fillStyle = "black";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = "white";
                ctx.font = "40px Arial";
                ctx.textAlign = "center";
                ctx.fillText("Stream Paused", canvas.width/2, canvas.height/2);
            }
        });

        // 3. Controls (Mouse & Keyboard)
        function sendClick(event) {
            const rect = canvas.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width;
            const y = (event.clientY - rect.top) / rect.height;
            socket.emit('mouse_click', { x: x, y: y });
        }

        window.addEventListener('wheel', function(event) {
            event.preventDefault();
            const direction = event.deltaY > 0 ? 'down' : 'up';
            socket.emit('mouse_scroll', { direction: direction });
        }, { passive: false });

        function sendText(text) {
            socket.emit('keyboard_input', { text: text });
        }

        window.addEventListener('keydown', function(event) {
            const specialKeys = ['Backspace', 'Enter', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape', 'Tab'];
            if (event.key === 'Backspace') event.preventDefault();
            if (event.key.length === 1 || specialKeys.includes(event.key)) {
                sendText(event.key);
            }
        });

        function showScreen() {
            document.getElementById('video-canvas').style.display = "block";
            document.getElementById('control-container').style.display = "none";
        }
    </script>
</head>
<body>
    <div id="control-container">
        <h2 style="color:white;">Connected to Relay Server</h2>
        <button onclick="showScreen()" style="width: 150px; height: 70px; border-radius: 35px; background-color: dodgerblue; color: white; font-size: 18px; border: none; cursor: pointer;">Show Screen</button>
    </div>
    <canvas id="video-canvas" onclick="sendClick(event)"></canvas>
</body>
</html>
'''

@app.route('/bill')
def index():
    return render_template_string(HTML_PAGE)

@socketio.on('video_frame')
def handle_video_frame(data):
    emit('video_frame', data, broadcast=True, include_self=False)
    return True # ACK to Host

# नया इवेंट: जब होस्ट पीसी पॉज़ करेगा, तो यह कॉल होगा
@socketio.on('stream_paused')
def handle_stream_pause():
    emit('stream_paused', broadcast=True, include_self=False)

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
    print("Relay Server is running...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
