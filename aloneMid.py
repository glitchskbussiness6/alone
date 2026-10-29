import os
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=20,
    ping_timeout=60,
    max_http_buffer_size=20 * 1024 * 1024,
    http_compression=False,  # JPEG already compressed, dobara compress karna CPU waste
)

viewer_sid = None
host_sid = None

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Direct Screen Remote</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <style>
        html, body { margin: 0; height: 100%; background: black; overflow: hidden; }
        #stream-img {
            position: fixed; inset: 0; width: 100%; height: 100%; object-fit: contain;
            cursor: crosshair; touch-action: none; display: block;
            user-select: none; -webkit-user-drag: none;
        }
        #remote-cursor {
            position: fixed; top: 0; left: 0; width: 22px; height: 22px; z-index: 100;
            pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
            transition: transform 0.05s linear; display: none; overflow: visible;
            transform-origin: top left;
        }
        #fs-btn {
            position: fixed; top: 8px; right: 8px; z-index: 300;
            background: rgba(30,30,30,0.75); color: #fff; border: 1px solid #888;
            border-radius: 8px; padding: 8px 12px; font: 14px sans-serif;
            opacity: 0.8; touch-action: manipulation;
        }
        #kb-input {
            position: fixed; bottom: 0; left: 0; width: 1px; height: 1px;
            opacity: 0; border: 0; padding: 0; font-size: 16px;
        }
        #loader {
            position: fixed; inset: 0; z-index: 150; display: flex;
            flex-direction: column; align-items: center; justify-content: center;
            background: rgba(0,0,0,0.88); color: #ddd; font: 15px sans-serif;
            pointer-events: none; text-align: center; padding: 0 20px;
        }
        .spinner {
            width: 46px; height: 46px; border-radius: 50%;
            border: 4px solid rgba(255,255,255,0.2); border-top-color: #fff;
            animation: spin 0.9s linear infinite; margin-bottom: 16px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
</head>
<body>
    <button id="fs-btn">⛶ Full Screen</button>
    <textarea id="kb-input" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false"></textarea>
    <div id="loader"><div class="spinner"></div><div id="loader-text">Connecting...</div></div>

    <svg id="remote-cursor" viewBox="0 0 24 24">
        <path d="M1 1l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
    </svg>

    <img id="stream-img" alt="" draggable="false">

    <script>
        const socket = io({
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 500,
            reconnectionDelayMax: 3000
        });

        const img = document.getElementById('stream-img');
        const cursor = document.getElementById('remote-cursor');
        const loaderEl = document.getElementById('loader');
        const loaderTextEl = document.getElementById('loader-text');
        let currentUrl = null;
        let seq = 0, shown = 0;

        socket.on('connect', () => {
            loaderTextEl.textContent = 'Connected. Waiting for host...';
            socket.emit('viewer_joined');
        });

        socket.on('host_status', (d) => {
            if (d && d.alive) {
                loaderEl.style.display = 'none';
            } else {
                loaderEl.style.display = 'flex';
                loaderTextEl.textContent = 'Host Offline...';
            }
        });

        socket.on('frame', (data) => {
            loaderEl.style.display = 'none';
            // Decode off-thread, newest frame wins, ack tab bhejo jab frame sach me decode ho jaye
            // (isse slow phone/network par host khud slow ho jata hai, lag build nahi hota)
            const my = ++seq;
            const url = URL.createObjectURL(new Blob([data], { type: 'image/jpeg' }));
            const tmp = new Image();
            tmp.src = url;
            tmp.decode().then(() => {
                if (my > shown) {
                    shown = my;
                    img.src = url;
                    if (currentUrl) URL.revokeObjectURL(currentUrl);
                    currentUrl = url;
                } else {
                    URL.revokeObjectURL(url);
                }
            }).catch(() => URL.revokeObjectURL(url))
              .finally(() => socket.emit('frame_ack'));
        });

        function getDrawRect() {
            const rect = img.getBoundingClientRect();
            const vw = img.naturalWidth || 1280;
            const vh = img.naturalHeight || 720;
            const videoRatio = vw / vh;
            const windowRatio = rect.width / rect.height;

            let drawWidth, drawHeight, offsetX = 0, offsetY = 0;
            if (windowRatio > videoRatio) {
                drawHeight = rect.height;
                drawWidth = rect.height * videoRatio;
                offsetX = (rect.width - drawWidth) / 2;
            } else {
                drawWidth = rect.width;
                drawHeight = rect.width / videoRatio;
                offsetY = (rect.height - drawHeight) / 2;
            }
            return { rect, drawWidth, drawHeight, offsetX, offsetY };
        }

        socket.on('mouse_move', (data) => {
            const { rect, drawWidth, drawHeight, offsetX, offsetY } = getDrawRect();
            const finalX = rect.left + offsetX + (data.x * drawWidth);
            const finalY = rect.top + offsetY + (data.y * drawHeight);
            cursor.style.display = 'block';
            cursor.style.transform = `translate(${finalX}px, ${finalY}px)`;
        });

        img.oncontextmenu = (e) => e.preventDefault();
        img.onpointerdown = (e) => {
            e.preventDefault();
            const { rect, drawWidth, drawHeight, offsetX, offsetY } = getDrawRect();
            const clickX = e.clientX - rect.left - offsetX;
            const clickY = e.clientY - rect.top - offsetY;

            if (clickX >= 0 && clickX <= drawWidth && clickY >= 0 && clickY <= drawHeight) {
                socket.emit('mouse_click', {
                    x: clickX / drawWidth,
                    y: clickY / drawHeight,
                    button: e.button
                });
            }
            document.getElementById('kb-input').focus();
        };

        const kbInput = document.getElementById('kb-input');
        document.addEventListener('keydown', (e) => {
            if (e.isComposing) return;
            if (['Shift', 'Control', 'Alt', 'Meta', 'Unidentified'].includes(e.key) || e.keyCode === 229) return;
            if (e.key.length > 1 || e.ctrlKey || e.altKey) {
                e.preventDefault();
                socket.emit('key_press', {
                    key: e.key, ctrl: e.ctrlKey, alt: e.altKey,
                    shift: e.shiftKey, meta: e.metaKey
                });
            }
        });

        kbInput.addEventListener('beforeinput', (e) => {
            if (e.inputType === 'deleteContentBackward') socket.emit('key_press', { key: 'Backspace' });
            else if (e.inputType.includes('LineBreak')) socket.emit('key_press', { key: 'Enter' });
        });

        kbInput.addEventListener('input', (e) => {
            if (e.inputType === 'insertText' && e.data) {
                socket.emit('key_text', { text: e.data });
            }
            kbInput.value = '';
        });

        document.getElementById('fs-btn').onclick = () => {
            if (!document.fullscreenElement) document.documentElement.requestFullscreen();
            else document.exitFullscreen();
        };
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/health')
def health():
    return 'ok'

@socketio.on('disconnect')
def handle_disconnect():
    global viewer_sid, host_sid
    if request.sid == viewer_sid:
        viewer_sid = None
    if request.sid == host_sid:
        host_sid = None
        if viewer_sid:
            socketio.emit('host_status', {'alive': False}, to=viewer_sid)

@socketio.on('host_hello')
def handle_host_hello():
    global host_sid
    host_sid = request.sid
    if viewer_sid:
        emit('host_status', {'alive': True}, to=viewer_sid)

@socketio.on('viewer_joined')
def handle_join():
    global viewer_sid
    viewer_sid = request.sid
    emit('host_status', {'alive': host_sid is not None})
    if host_sid:
        socketio.emit('request_frame', to=host_sid)

@socketio.on('frame')
def handle_frame(data):
    if viewer_sid:
        socketio.emit('frame', data, to=viewer_sid)
    else:
        # viewer nahi hai -> frame drop, par host ko ack do warna uska inflight counter full hoke stream ruk jata hai
        emit('frame_ack')

@socketio.on('frame_ack')
def handle_frame_ack():
    if host_sid:
        socketio.emit('frame_ack', to=host_sid)

@socketio.on('mouse_move')
def handle_mouse_move(data):
    if viewer_sid:
        socketio.emit('mouse_move', data, to=viewer_sid)

@socketio.on('mouse_click')
def handle_mouse_click(data):
    if host_sid:
        socketio.emit('mouse_click', data, to=host_sid)

@socketio.on('key_text')
def handle_key_text(data):
    if host_sid:
        socketio.emit('key_text', data, to=host_sid)

@socketio.on('key_press')
def handle_key_press(data):
    if host_sid:
        socketio.emit('key_press', data, to=host_sid)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
