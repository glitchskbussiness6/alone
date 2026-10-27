from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)

# Ultra-low latency SocketIO Config
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=30,
    ping_interval=10,
    max_http_buffer_size=10 * 1024 * 1024
)

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Stream API Remote Controller</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body, html { margin: 0; padding: 0; overflow: hidden; height: 100%; width: 100%; background-color: #000; }
        #video-canvas { display: block; position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; object-fit: contain; cursor: crosshair; }
    </style>
    <script>
        const socket = io({ transports: ['websocket', 'polling'] });
        let canvas, ctx;
        let isProcessingFrame = false;

        window.onload = function() {
            canvas = document.getElementById("video-canvas");
            ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
            canvas.width = 1280;
            canvas.height = 720;
        };

        // Hardware-Accelerated ImageBitmap Pipeline
        socket.on('video_frame', function(data) {
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

        socket.on('stream_paused', function() {
            if(ctx && canvas) {
                ctx.fillStyle = "#0a0a0a";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = "#00ffcc";
                ctx.font = "bold 32px Segoe UI, Arial";
                ctx.textAlign = "center";
                ctx.fillText("STREAM PAUSED (IDLE)", canvas.width/2, canvas.height/2);
            }
        });

        // 1. EXACT ACCURATE CLICK MAPPING (Subtracts Black Letterbox/Pillarbox Bars)
        function sendClick(event) {
            const rect = canvas.getBoundingClientRect();
            
            const elementWidth = rect.width;
            const elementHeight = rect.height;

            const streamWidth = canvas.width;  // Native video width (1280)
            const streamHeight = canvas.height; // Native video height (720)

            const streamAspect = streamWidth / streamHeight;
            const elementAspect = elementWidth / elementHeight;

            let renderWidth, renderHeight;
            let offsetX = 0;
            let offsetY = 0;

            // Display area calculation
            if (elementAspect > streamAspect) {
                // Pillarbox (Black bars on left/right)
                renderHeight = elementHeight;
                renderWidth = elementHeight * streamAspect;
                offsetX = (elementWidth - renderWidth) / 2;
            } else {
                // Letterbox (Black bars on top/bottom)
                renderWidth = elementWidth;
                renderHeight = elementWidth / streamAspect;
                offsetY = (elementHeight - renderHeight) / 2;
            }

            // Calculate precise coordinates inside actual frame area
            const clickX = event.clientX - rect.left - offsetX;
            const clickY = event.clientY - rect.top - offsetY;

            // Ignore clicks made on black bars
            if (clickX < 0 || clickX > renderWidth || clickY < 0 || clickY > renderHeight) {
                return;
            }

            // Normalized 0.0 - 1.0 coordinates
            const normalizedX = clickX / renderWidth;
            const normalizedY = clickY / renderHeight;

            socket.emit('mouse_click', {
                x: normalizedX,
                y: normalizedY,
                button: event.button
            });
        }

        // 2. Smooth Mouse Scroll Handler
        let scrollTimeout;
        window.addEventListener('wheel', function(event) {
            event.preventDefault();
            
            if (!scrollTimeout) {
                scrollTimeout = setTimeout(() => {
                    scrollTimeout = null;
                }, 30);
                
                const deltaY = event.deltaY;
                const direction = deltaY > 0 ? 'down' : 'up';
                const amount = Math.abs(deltaY);
                socket.emit('mouse_scroll', { direction: direction, amount: amount });
            }
        }, { passive: false });

        // 3. Low Latency Keyboard Mapping
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
    <canvas id="video-canvas" onclick="sendClick(event)" oncontextmenu="event.preventDefault(); sendClick(event);"></canvas>
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
    print("Relay Engine (Optimized) listening on port 5000...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
