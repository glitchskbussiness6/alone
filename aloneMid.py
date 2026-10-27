from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    ping_timeout=30,
    ping_interval=10,
    max_http_buffer_size=10 * 1024 * 1024
)

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Relay Remote Controller</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
            user-select: none;
        }
        body, html {
            width: 100vw;
            height: 100vh;
            overflow: hidden;
            background-color: #000;
            font-family: Arial, sans-serif;
        }
        #landing-container {
            position: absolute;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            background-color: #111;
            color: #fff;
            z-index: 20;
            text-align: center;
            padding: 20px;
        }
        #landing-container h2 { color: #28a745; margin-bottom: 10px; }
        #landing-container p { color: #ff4d4d; margin-bottom: 25px; font-weight: bold; }
        .start-btn {
            width: 200px;
            height: 60px;
            border-radius: 30px;
            background-color: #1e90ff;
            color: white;
            font-size: 20px;
            font-weight: bold;
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 15px rgba(30, 144, 255, 0.4);
            transition: transform 0.2s;
        }
        .start-btn:active { transform: scale(0.95); }

        #video-canvas {
            display: none;
            position: absolute;
            top: 0; left: 0;
            width: 100vw;
            height: 100vh;
            object-fit: contain;
            cursor: crosshair;
            z-index: 1;
        }

        #pause-overlay {
            display: none;
            position: absolute;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            background-color: rgba(0, 0, 0, 0.92);
            color: #00ffcc;
            z-index: 10;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
        }
        #pause-overlay h1 { font-size: 3rem; margin-bottom: 10px; text-transform: uppercase; }
        #pause-overlay p { font-size: 1.2rem; color: #aaa; }
    </style>
    <script>
        const socket = io({ transports: ['websocket', 'polling'] });
        let canvas, ctx, pauseOverlay, landingContainer;
        let isProcessingFrame = false;

        window.onload = function() {
            canvas = document.getElementById("video-canvas");
            ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
            pauseOverlay = document.getElementById("pause-overlay");
            landingContainer = document.getElementById("landing-container");

            canvas.width = 1280;
            canvas.height = 720;
            setupTouchAndScrollEvents();
        };

        // 1. Frame Stream Handler
        socket.on('video_frame', function(data) {
            pauseOverlay.style.display = "none";
            
            if (isProcessingFrame) return; 
            isProcessingFrame = true;

            const blob = new Blob([data.image], { type: "image/jpeg" });
            createImageBitmap(blob, { imageOrientation: "none", resizeQuality: "low" }).then(function(imgBitmap) {
                if(canvas.width !== imgBitmap.width || canvas.height !== imgBitmap.height) {
                    canvas.width = imgBitmap.width;
                    canvas.height = imgBitmap.height;
                }
                ctx.drawImage(imgBitmap, 0, 0);
                imgBitmap.close();
                isProcessingFrame = false;
            }).catch(() => { isProcessingFrame = false; });
        });

        // 2. Stream Paused Handler
        socket.on('stream_paused', function() {
            pauseOverlay.style.display = "flex";
        });

        // 3. Launch Fullscreen & Show Video
        function showScreen() {
            enableFullScreen();
            landingContainer.style.display = "none";
            canvas.style.display = "block";
        }

        function enableFullScreen() {
            const doc = document.documentElement;
            if (doc.requestFullscreen) { doc.requestFullscreen(); }
            else if (doc.mozRequestFullScreen) { doc.mozRequestFullScreen(); }
            else if (doc.webkitRequestFullscreen) { doc.webkitRequestFullscreen(); }
            else if (doc.msRequestFullscreen) { doc.msRequestFullscreen(); }
        }

        // 4. Exact Pixel-Accurate Click Mapping (Excludes Black Bars)
        function sendClick(event) {
            const rect = canvas.getBoundingClientRect();
            
            const elementWidth = rect.width;
            const elementHeight = rect.height;

            const streamWidth = canvas.width;  
            const streamHeight = canvas.height; 

            const streamAspect = streamWidth / streamHeight;
            const elementAspect = elementWidth / elementHeight;

            let renderWidth, renderHeight;
            let offsetX = 0;
            let offsetY = 0;

            if (elementAspect > streamAspect) {
                renderHeight = elementHeight;
                renderWidth = elementHeight * streamAspect;
                offsetX = (elementWidth - renderWidth) / 2;
            } else {
                renderWidth = elementWidth;
                renderHeight = elementWidth / streamAspect;
                offsetY = (elementHeight - renderHeight) / 2;
            }

            const clickX = event.clientX - rect.left - offsetX;
            const clickY = event.clientY - rect.top - offsetY;

            if (clickX < 0 || clickX > renderWidth || clickY < 0 || clickY > renderHeight) {
                return;
            }

            const normalizedX = clickX / renderWidth;
            const normalizedY = clickY / renderHeight;

            socket.emit('mouse_click', {
                x: normalizedX,
                y: normalizedY,
                button: event.button
            });
        }

        // 5. Touch Drag / Mouse Wheel Scroll Logic
        function setupTouchAndScrollEvents() {
            let scrollTimeout;
            
            // Mouse Wheel Scroll
            window.addEventListener('wheel', function(event) {
                event.preventDefault();
                if (!scrollTimeout) {
                    scrollTimeout = setTimeout(() => { scrollTimeout = null; }, 30);
                    const direction = event.deltaY > 0 ? 'down' : 'up';
                    socket.emit('mouse_scroll', { direction: direction, amount: Math.abs(event.deltaY) });
                }
            }, { passive: false });

            // Mobile Touch Drag Scroll
            let startY = null;
            window.addEventListener('touchstart', function(e) {
                if (e.touches.length === 1) {
                    startY = e.touches[0].clientY;
                }
            }, { passive: false });

            window.addEventListener('touchmove', function(e) {
                if (startY === null || e.touches.length > 1) return;
                const currentY = e.touches[0].clientY;
                const diffY = startY - currentY;

                if (Math.abs(diffY) > 10) { // Threshold for drag
                    const direction = diffY > 0 ? 'down' : 'up';
                    socket.emit('mouse_scroll', { direction: direction, amount: Math.abs(diffY) });
                    startY = currentY;
                }
            }, { passive: false });

            window.addEventListener('touchend', function() { startY = null; });
        }

        // 6. Keyboard Listener
        window.addEventListener('keydown', function(event) {
            const specialKeys = ['Backspace', 'Enter', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape', 'Tab', 'Delete'];
            if (['Backspace', 'Tab'].includes(event.key)) event.preventDefault();
            
            if (event.key.length === 1 || specialKeys.includes(event.key)) {
                socket.emit('keyboard_input', { text: event.key });
            }
        });
    </script>
</head>
<body>
    <div id="landing-container">
        <h2>Successfully Connected!</h2>
        <p>Keep your device in Landscape Mode for the best experience.</p>
        <button class="start-btn" onclick="showScreen()">Show Screen</button>
    </div>

    <div id="pause-overlay">
        <h1>Stream Paused</h1>
        <p>The PC host has paused broadcasting</p>
    </div>

    <canvas id="video-canvas" 
            onclick="sendClick(event)" 
            ondblclick="enableFullScreen()" 
            oncontextmenu="event.preventDefault(); sendClick(event);">
    </canvas>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@socketio.on('video_frame')
def handle_video_frame(data):
    emit('video_frame', data, broadcast=True, include_self=False)
    return True 

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
    print("Relay Server Running...")
    socketio.run(app, host='0.0.0.0', port=5000)
