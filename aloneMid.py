# from flask import Flask, render_template_string
# from flask_socketio import SocketIO, emit

# app = Flask(__name__)
# socketio = SocketIO(app, cors_allowed_origins="*")

# HTML_PAGE = '''
# <!DOCTYPE html>
# <html>
# <head>
#     <title>WebRTC Remote</title>
#     <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
#     <style>
#         body { margin: 0; background: black; overflow: hidden; }
        
#         /* Browser autoplay policy bypass ke liye muted lagana zaruri hai */
#         video { width: 100vw; height: 100vh; object-fit: contain; cursor: crosshair; }
        
#         /* Virtual Mouse Cursor */
#         #remote-cursor {
#             position: absolute; width: 22px; height: 22px; z-index: 100;
#             pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
#             transition: transform 0.05s linear; display: none;
#             transform-origin: top left;
#         }
#     </style>
#     <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
# </head>
# <body>
#     <!-- Fake Mouse Pointer -->
#     <svg id="remote-cursor" viewBox="0 0 24 24">
#         <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
#     </svg>
    
#     <!-- Video element (muted added) -->
#     <!-- iOS support के लिए webkit-playsinline ऐड किया गया है -->
#     <video id="video-stream" autoplay playsinline webkit-playsinline muted></video>

#     <script>
#         const socket = io();
#         const video = document.getElementById('video-stream');
#         const cursor = document.getElementById('remote-cursor');
        
#        let pc = new RTCPeerConnection({
#             iceServers: [
#                 { urls: 'stun:stun.l.google.com:19302' },
#                 { 
#                     urls: [
#                         'turn:openrelay.metered.ca:80',
#                         'turn:openrelay.metered.ca:443'
#                     ], 
#                     username: 'openrelayproject', 
#                     credential: 'openrelayproject' 
#                 }
#             ]
#         });

#         // --- 1. WebRTC Signaling ---
#         pc.ontrack = (event) => { 
#             video.srcObject = event.streams[0]; 
            
#             // मोबाइल ब्राउज़र्स में ज़बरदस्ती प्ले करने के लिए
#             video.onloadedmetadata = () => {
#                 video.play().catch((err) => {
#                     console.log("Autoplay blocked by mobile browser:", err);
#                     // अगर फोन प्ले करने से रोके, तो एक क्लिक पर प्ले करें
#                     document.body.onclick = () => { video.play(); };
#                 });
#             };
#         };
        
#         pc.onicecandidate = (event) => {
#             if (event.candidate) {
#                 socket.emit('ice_candidate', {
#                     candidate: event.candidate.candidate,
#                     sdpMid: event.candidate.sdpMid,
#                     sdpMLineIndex: event.candidate.sdpMLineIndex
#                 });
#             }
#         };

#         socket.on('offer', async (offer) => {
#             await pc.setRemoteDescription(new RTCSessionDescription(offer));
#             const answer = await pc.createAnswer();
#             await pc.setLocalDescription(answer);
#             socket.emit('answer', { type: answer.type, sdp: answer.sdp });
#         });

#         socket.on('ice_candidate', async (data) => {
#             try {
#                 await pc.addIceCandidate(new RTCIceCandidate(data));
#             } catch (e) {
#                 console.error("Error adding ice candidate", e);
#             }
#         });

#         // Tell Python we are ready to view
#         socket.emit('viewer_joined');

#         // --- 2. Metadata Mouse Trick ---
#         socket.on('mouse_move', (data) => {
#             const rect = video.getBoundingClientRect();
#             const videoRatio = 1280 / 720;
#             const windowRatio = rect.width / rect.height;
            
#             let drawWidth, drawHeight, offsetX = 0, offsetY = 0;
            
#             if (windowRatio > videoRatio) {
#                 drawHeight = rect.height;
#                 drawWidth = rect.height * videoRatio;
#                 offsetX = (rect.width - drawWidth) / 2;
#             } else {
#                 drawWidth = rect.width;
#                 drawHeight = rect.width / videoRatio;
#                 offsetY = (rect.height - drawHeight) / 2;
#             }

#             const finalX = rect.left + offsetX + (data.x * drawWidth);
#             const finalY = rect.top + offsetY + (data.y * drawHeight);
            
#             cursor.style.display = 'block';
#             cursor.style.transform = `translate(${finalX}px, ${finalY}px)`;
#         });

#         // --- 3. Click Sender ---
#         video.oncontextmenu = (e) => e.preventDefault(); 
        
#         video.onmousedown = (e) => {
#             const rect = video.getBoundingClientRect();
#             const videoRatio = 1280 / 720;
#             const windowRatio = rect.width / rect.height;
            
#             let drawWidth, drawHeight, offsetX = 0, offsetY = 0;
#             if (windowRatio > videoRatio) {
#                 drawHeight = rect.height;
#                 drawWidth = rect.height * videoRatio;
#                 offsetX = (rect.width - drawWidth) / 2;
#             } else {
#                 drawWidth = rect.width;
#                 drawHeight = rect.width / videoRatio;
#                 offsetY = (rect.height - drawHeight) / 2;
#             }

#             const clickX = e.clientX - rect.left - offsetX;
#             const clickY = e.clientY - rect.top - offsetY;

#             if (clickX >= 0 && clickX <= drawWidth && clickY >= 0 && clickY <= drawHeight) {
#                 socket.emit('mouse_click', { 
#                     x: clickX / drawWidth, 
#                     y: clickY / drawHeight,
#                     button: e.button
#                 });
#             }
#         };
#     </script>
# </body>
# </html>
# '''

# @app.route('/')
# def index(): 
#     return render_template_string(HTML_PAGE)

# # --- Signaling Relay Events ---
# @socketio.on('viewer_joined')
# def handle_join(): emit('viewer_joined', broadcast=True, include_self=False)

# @socketio.on('offer')
# def handle_offer(data): emit('offer', data, broadcast=True, include_self=False)

# @socketio.on('answer')
# def handle_answer(data): emit('answer', data, broadcast=True, include_self=False)

# @socketio.on('ice_candidate')
# def handle_ice(data): emit('ice_candidate', data, broadcast=True, include_self=False)

# # --- Mouse Relay Events ---
# @socketio.on('mouse_move')
# def handle_mouse_move(data): emit('mouse_move', data, broadcast=True, include_self=False)

# @socketio.on('mouse_click')
# def handle_mouse_click(data): emit('mouse_click', data, broadcast=True, include_self=False)


# if __name__ == '__main__':
#     print("Relay Server Running on port 5000...")
#     socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)















import os
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Sirf ek active viewer aur ek host track hota hai
viewer_sid = None
host_sid = None

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>WebRTC Remote</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <style>
        html, body { margin: 0; height: 100%; background: black; overflow: hidden; }
        video {
            width: 100vw; height: 100vh; object-fit: contain;
            cursor: crosshair; touch-action: none;
        }
        #remote-cursor {
            position: fixed; top: 0; left: 0; width: 22px; height: 22px; z-index: 100;
            pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
            transition: transform 0.05s linear; display: none;
            transform-origin: top left;
        }
        #status {
            position: fixed; top: 6px; left: 6px; z-index: 200;
            color: #0f0; font: 12px monospace; background: rgba(0,0,0,0.6);
            padding: 3px 6px; border-radius: 4px; pointer-events: none;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <div id="status">starting...</div>

    <svg id="remote-cursor" viewBox="0 0 24 24">
        <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
    </svg>

    <video id="video-stream" autoplay playsinline webkit-playsinline muted></video>

    <script>
        // ====== TURN CONFIG ======
        // Phone (mobile data) ke liye REAL TURN server zaruri hai.
        // Metered.ca / Cloudflare TURN ke free credentials yahan daalo
        // aur SAME credentials host.py mein bhi daalo.
        const ICE_SERVERS = [
            { urls: 'stun:stun.l.google.com:19302' },
            {
                urls: [
                    'turn:openrelay.metered.ca:80',
                    'turn:openrelay.metered.ca:443',
                    'turns:openrelay.metered.ca:443?transport=tcp'
                ],
                username: 'openrelayproject',
                credential: 'openrelayproject'
            }
        ];
        // =========================

        const socket = io();
        const video = document.getElementById('video-stream');
        const cursor = document.getElementById('remote-cursor');
        const statusEl = document.getElementById('status');

        let pc = null;
        let pendingCandidates = [];

        function setStatus(t) { statusEl.textContent = t; console.log(t); }

        function createPC() {
            if (pc) { try { pc.close(); } catch (e) {} }
            pendingCandidates = [];
            pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

            pc.ontrack = (event) => {
                video.srcObject = event.streams[0];
                const tryPlay = () => {
                    video.play().catch(() => {
                        setStatus('Tap screen to play video');
                        document.addEventListener('pointerdown', () => video.play(), { once: true });
                    });
                };
                video.onloadedmetadata = tryPlay;
                tryPlay();
            };

            pc.onicecandidate = (event) => {
                if (event.candidate) {
                    socket.emit('ice_candidate', {
                        candidate: event.candidate.candidate,
                        sdpMid: event.candidate.sdpMid,
                        sdpMLineIndex: event.candidate.sdpMLineIndex
                    });
                }
            };

            pc.oniceconnectionstatechange = () => setStatus('ICE: ' + pc.iceConnectionState);
            pc.onconnectionstatechange = () => {
                setStatus('PC: ' + pc.connectionState);
                if (pc.connectionState === 'connected') {
                    setTimeout(() => { statusEl.style.display = 'none'; }, 2000);
                } else {
                    statusEl.style.display = 'block';
                }
            };
        }

        async function drainCandidates() {
            for (const c of pendingCandidates) {
                try { await pc.addIceCandidate(c); } catch (e) { console.error('ICE add error', e); }
            }
            pendingCandidates = [];
        }

        // --- 1. WebRTC Signaling ---
        socket.on('offer', async (offer) => {
            try {
                createPC();
                await pc.setRemoteDescription(new RTCSessionDescription(offer));
                await drainCandidates();
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                socket.emit('answer', { type: answer.type, sdp: answer.sdp });
                setStatus('Answer sent...');
            } catch (e) {
                setStatus('Offer error: ' + e);
            }
        });

        socket.on('ice_candidate', async (data) => {
            if (!pc || !data || !data.candidate) return;
            const cand = new RTCIceCandidate(data);
            if (pc.remoteDescription) {
                try { await pc.addIceCandidate(cand); } catch (e) { console.error(e); }
            } else {
                pendingCandidates.push(cand);
            }
        });

        // Socket connect / reconnect hone par host ko batao
        socket.on('connect', () => {
            setStatus('Connected to relay, waiting for host...');
            socket.emit('viewer_joined');
        });

        // --- 2. Remote cursor ---
        function getDrawRect() {
            const rect = video.getBoundingClientRect();
            const vw = video.videoWidth || 1280;
            const vh = video.videoHeight || 720;
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

        // --- 3. Click / Tap sender (pointer events = mouse + touch dono) ---
        video.oncontextmenu = (e) => e.preventDefault();

        video.onpointerdown = (e) => {
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
        };
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


def to_viewer(event, data=None):
    if viewer_sid:
        emit(event, data, to=viewer_sid)


def to_host(event, data=None):
    if host_sid:
        emit(event, data, to=host_sid)


@socketio.on('disconnect')
def handle_disconnect():
    global viewer_sid, host_sid
    if request.sid == viewer_sid:
        viewer_sid = None
    if request.sid == host_sid:
        host_sid = None


# --- Viewer -> Host ---
@socketio.on('viewer_joined')
def handle_join():
    global viewer_sid
    viewer_sid = request.sid  # sabse latest viewer active hoga
    emit('viewer_joined', broadcast=True, include_self=False)


@socketio.on('answer')
def handle_answer(data):
    if request.sid == viewer_sid:
        to_host('answer', data)


@socketio.on('mouse_click')
def handle_mouse_click(data):
    if request.sid == viewer_sid:
        to_host('mouse_click', data)


# --- Host -> Viewer ---
@socketio.on('offer')
def handle_offer(data):
    global host_sid
    host_sid = request.sid
    to_viewer('offer', data)


@socketio.on('mouse_move')
def handle_mouse_move(data):
    global host_sid
    host_sid = request.sid
    to_viewer('mouse_move', data)


# --- ICE: dono taraf ---
@socketio.on('ice_candidate')
def handle_ice(data):
    if request.sid == viewer_sid:
        to_host('ice_candidate', data)
    else:
        to_viewer('ice_candidate', data)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Relay Server Running on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
