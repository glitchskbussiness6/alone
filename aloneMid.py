from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>WebRTC Remote</title>
    <style>
        body { margin: 0; background: black; overflow: hidden; }
        video { width: 100vw; height: 100vh; object-fit: contain; }
        #remote-cursor {
            position: absolute; width: 20px; height: 20px; z-index: 100;
            pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
            transition: transform 0.05s linear;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <svg id="remote-cursor" viewBox="0 0 24 24"><path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/></svg>
    <video id="video-stream" autoplay playsinline></video>

    <script>
        const socket = io();
        const video = document.getElementById('video-stream');
        const cursor = document.getElementById('remote-cursor');
        
        let pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] // Google's free STUN
        });

        // 1. WebRTC Signaling
        pc.ontrack = (event) => { video.srcObject = event.streams[0]; };
        pc.onicecandidate = (event) => {
            if (event.candidate) socket.emit('ice_candidate', event.candidate);
        };

        socket.on('offer', async (offer) => {
            await pc.setRemoteDescription(new RTCSessionDescription(offer));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            socket.emit('answer', answer);
        });

        socket.on('ice_candidate', async (candidate) => {
            await pc.addIceCandidate(new RTCIceCandidate(candidate));
        });

        socket.emit('viewer_joined'); // Tell Python we are ready

        // 2. Mouse Metadata
        socket.on('mouse_move', (data) => {
            const rect = video.getBoundingClientRect();
            // Basic coordinate mapping (you can add the aspect ratio math here)
            const finalX = rect.left + (data.x * rect.width);
            const finalY = rect.top + (data.y * rect.height);
            cursor.style.transform = `translate(${finalX}px, ${finalY}px)`;
        });

        // 3. Send Clicks back to Python
        video.onclick = (e) => {
            const rect = video.getBoundingClientRect();
            socket.emit('mouse_click', { x: (e.clientX - rect.left)/rect.width, y: (e.clientY - rect.top)/rect.height });
        };
    </script>
</body>
</html>
'''

@app.route('/')
def index(): return render_template_string(HTML_PAGE)

# --- Signaling Relay ---
@socketio.on('viewer_joined')
def handle_join(): emit('viewer_joined', broadcast=True, include_self=False)

@socketio.on('offer')
def handle_offer(data): emit('offer', data, broadcast=True, include_self=False)

@socketio.on('answer')
def handle_answer(data): emit('answer', data, broadcast=True, include_self=False)

@socketio.on('ice_candidate')
def handle_ice(data): emit('ice_candidate', data, broadcast=True, include_self=False)

# --- Mouse Relay ---
@socketio.on('mouse_move')
def handle_mouse_move(data): emit('mouse_move', data, broadcast=True, include_self=False)

@socketio.on('mouse_click')
def handle_mouse_click(data): emit('mouse_click', data, broadcast=True, include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
