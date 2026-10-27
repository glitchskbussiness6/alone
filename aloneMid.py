from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>WebRTC Remote</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0"/>
    <style>
        body { margin: 0; background: black; overflow: hidden; }
        
        /* Browser autoplay policy bypass ke liye muted lagana zaruri hai */
        video { width: 100vw; height: 100vh; object-fit: contain; cursor: crosshair; }
        
        /* Virtual Mouse Cursor */
        #remote-cursor {
            position: absolute; width: 22px; height: 22px; z-index: 100;
            pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
            transition: transform 0.05s linear; display: none;
            transform-origin: top left;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <!-- Fake Mouse Pointer -->
    <svg id="remote-cursor" viewBox="0 0 24 24">
        <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
    </svg>
    
    <!-- Video element (muted added) -->
    <!-- iOS support के लिए webkit-playsinline ऐड किया गया है -->
    <video id="video-stream" autoplay playsinline webkit-playsinline muted></video>

    <script>
        const socket = io();
        const video = document.getElementById('video-stream');
        const cursor = document.getElementById('remote-cursor');
        
       let pc = new RTCPeerConnection({
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { 
                    urls: [
                        'turn:openrelay.metered.ca:80',
                        'turn:openrelay.metered.ca:443'
                    ], 
                    username: 'openrelayproject', 
                    credential: 'openrelayproject' 
                }
            ]
        });

        // --- 1. WebRTC Signaling ---
        pc.ontrack = (event) => { 
            video.srcObject = event.streams[0]; 
            
            // मोबाइल ब्राउज़र्स में ज़बरदस्ती प्ले करने के लिए
            video.onloadedmetadata = () => {
                video.play().catch((err) => {
                    console.log("Autoplay blocked by mobile browser:", err);
                    // अगर फोन प्ले करने से रोके, तो एक क्लिक पर प्ले करें
                    document.body.onclick = () => { video.play(); };
                });
            };
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

        socket.on('offer', async (offer) => {
            await pc.setRemoteDescription(new RTCSessionDescription(offer));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            socket.emit('answer', { type: answer.type, sdp: answer.sdp });
        });

        socket.on('ice_candidate', async (data) => {
            try {
                await pc.addIceCandidate(new RTCIceCandidate(data));
            } catch (e) {
                console.error("Error adding ice candidate", e);
            }
        });

        // Tell Python we are ready to view
        socket.emit('viewer_joined');

        // --- 2. Metadata Mouse Trick ---
        socket.on('mouse_move', (data) => {
            const rect = video.getBoundingClientRect();
            const videoRatio = 1280 / 720;
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

            const finalX = rect.left + offsetX + (data.x * drawWidth);
            const finalY = rect.top + offsetY + (data.y * drawHeight);
            
            cursor.style.display = 'block';
            cursor.style.transform = `translate(${finalX}px, ${finalY}px)`;
        });

        // --- 3. Click Sender ---
        video.oncontextmenu = (e) => e.preventDefault(); 
        
        video.onmousedown = (e) => {
            const rect = video.getBoundingClientRect();
            const videoRatio = 1280 / 720;
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

# --- Signaling Relay Events ---
@socketio.on('viewer_joined')
def handle_join(): emit('viewer_joined', broadcast=True, include_self=False)

@socketio.on('offer')
def handle_offer(data): emit('offer', data, broadcast=True, include_self=False)

@socketio.on('answer')
def handle_answer(data): emit('answer', data, broadcast=True, include_self=False)

@socketio.on('ice_candidate')
def handle_ice(data): emit('ice_candidate', data, broadcast=True, include_self=False)

# --- Mouse Relay Events ---
@socketio.on('mouse_move')
def handle_mouse_move(data): emit('mouse_move', data, broadcast=True, include_self=False)

@socketio.on('mouse_click')
def handle_mouse_click(data): emit('mouse_click', data, broadcast=True, include_self=False)


if __name__ == '__main__':
    print("Relay Server Running on port 5000...")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
