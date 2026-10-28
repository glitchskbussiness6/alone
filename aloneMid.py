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
        video, #fb-img {
            width: 100vw; height: 100vh; object-fit: contain;
            cursor: crosshair; touch-action: none;
        }
        #fb-img {
            display: none; position: fixed; top: 0; left: 0; z-index: 1;
            background: black; user-select: none; -webkit-user-drag: none;
        }
        #remote-cursor {
            position: fixed; top: 0; left: 0; width: 22px; height: 22px; z-index: 100;
            pointer-events: none; fill: white; stroke: black; stroke-width: 1px;
            transition: transform 0.05s linear; display: none;
            transform-origin: top left;
        }
        #fs-btn {
            position: fixed; top: 8px; right: 8px; z-index: 300;
            background: rgba(30,30,30,0.75); color: #fff; border: 1px solid #888;
            border-radius: 8px; padding: 8px 12px; font: 14px sans-serif;
            opacity: 0.8; touch-action: manipulation;
        }
        #fs-btn:active { opacity: 1; }
        #kb-input {
            position: fixed; bottom: 0; left: 0; width: 1px; height: 1px;
            opacity: 0; border: 0; padding: 0; font-size: 16px; /* 16px: iOS zoom roakta hai */
        }
        #toast {
            position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
            z-index: 300; background: rgba(0,0,0,0.8); color: #fff;
            font: 13px sans-serif; padding: 8px 12px; border-radius: 8px;
            display: none; max-width: 85vw; text-align: center;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <button id="fs-btn">⛶ Full Screen (Landscape)</button>
    <textarea id="kb-input" autocapitalize="off" autocomplete="off"
              autocorrect="off" spellcheck="false"></textarea>
    <div id="toast"></div>

    <svg id="remote-cursor" viewBox="0 0 24 24">
        <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
    </svg>

    <video id="video-stream" autoplay playsinline webkit-playsinline muted></video>
    <img id="fb-img" alt="" draggable="false">

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
        const statusEl = { style: {}, textContent: '' };  // status UI hata diya

        let pc = null;
        let pendingCandidates = [];

        // ====== RELAY FALLBACK ======
        // WebRTC (ICE) 6 second mein connect na ho ya fail ho jaye to screen frames
        // Render relay server ke through aate hain (TURN ki zarurat nahi).
        // URL ke end mein ?mode=relay lagao to seedha relay mode chalega.
        const FALLBACK_AFTER_MS = 6000;
        const forceRelay = new URLSearchParams(location.search).get('mode') === 'relay';
        const fbImg = document.getElementById('fb-img');
        let useFallback = false;
        let fbFrames = 0;
        let fbUrl = null;
        let connWatch = null;

        fbImg.onload = () => { fbFrames++; };

        function startFallback() {
            if (useFallback) return;
            useFallback = true;
            fbFrames = 0;
            fbImg.style.display = 'block';
            video.style.visibility = 'hidden';
            statusEl.style.display = 'block';
            setStatus('Relay mode (WebRTC connect nahi hua)');
            socket.emit('fallback_start');
        }

        function resetFallbackUI() {
            useFallback = false;
            fbImg.style.display = 'none';
            video.style.visibility = 'visible';
            if (fbUrl) { URL.revokeObjectURL(fbUrl); fbUrl = null; }
        }

        function stopFallback() {
            if (!useFallback) return;
            resetFallbackUI();
            socket.emit('fallback_stop');
        }

        socket.on('frame', (data) => {
            if (!useFallback) return;
            const url = URL.createObjectURL(new Blob([data], { type: 'image/jpeg' }));
            fbImg.src = url;
            if (fbUrl) URL.revokeObjectURL(fbUrl);
            fbUrl = url;
            socket.emit('frame_ack');
        });
        // ============================

        function setStatus(t) { statusEl.textContent = t; console.log(t); }

        function createPC() {
            if (pc) { try { pc.close(); } catch (e) {} }
            pendingCandidates = [];
            pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

            pc.ontrack = (event) => {
                setStatus('Track received');
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
                    if (!forceRelay) stopFallback();
                    setTimeout(() => { if (!useFallback) statusEl.style.display = 'none'; }, 2000);
                } else {
                    statusEl.style.display = 'block';
                    if (pc.connectionState === 'failed') startFallback();
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
                clearTimeout(connWatch);
                if (forceRelay) {
                    startFallback();
                } else {
                    connWatch = setTimeout(() => {
                        if (!pc || pc.connectionState !== 'connected') startFallback();
                    }, FALLBACK_AFTER_MS);
                }
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
            clearTimeout(connWatch);
            resetFallbackUI();
            setStatus('Connected to relay, waiting for host...');
            socket.emit('viewer_joined');
        });

        // --- 2. Remote cursor ---
        function getDrawRect() {
            const el = useFallback ? fbImg : video;
            const rect = el.getBoundingClientRect();
            const vw = (useFallback ? fbImg.naturalWidth : video.videoWidth) || 1280;
            const vh = (useFallback ? fbImg.naturalHeight : video.videoHeight) || 720;
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

        // --- Fullscreen + Landscape ---
        const fsBtn = document.getElementById('fs-btn');
        const toastEl = document.getElementById('toast');

        function toast(msg) {
            toastEl.textContent = msg;
            toastEl.style.display = 'block';
            setTimeout(() => { toastEl.style.display = 'none'; }, 3500);
        }

        function isFullscreen() {
            return !!(document.fullscreenElement || document.webkitFullscreenElement);
        }

        async function enterFullscreen() {
            const el = document.documentElement;
            try {
                if (el.requestFullscreen) {
                    await el.requestFullscreen({ navigationUI: 'hide' });
                } else if (el.webkitRequestFullscreen) {
                    el.webkitRequestFullscreen();
                } else if (video.webkitEnterFullscreen) {
                    // iPhone Safari: sirf video fullscreen hoti hai
                    video.webkitEnterFullscreen();
                    return;
                } else {
                    toast('Is browser mein fullscreen support nahi hai');
                    return;
                }
            } catch (e) {
                toast('Fullscreen fail: ' + e.message);
                return;
            }

            // Landscape lock (Android Chrome mein fullscreen ke baad hi chalta hai)
            try {
                await screen.orientation.lock('landscape');
            } catch (e) {
                toast('Auto-landscape nahi hua. Phone ko aadha ghumao (auto-rotate ON rakho).');
            }
        }

        async function exitFullscreen() {
            try { screen.orientation.unlock(); } catch (e) {}
            if (document.exitFullscreen) await document.exitFullscreen();
            else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
        }

        fsBtn.onclick = () => { isFullscreen() ? exitFullscreen() : enterFullscreen(); };

        function onFsChange() {
            if (isFullscreen()) {
                fsBtn.textContent = '✕ Exit Full Screen';
            } else {
                fsBtn.textContent = '⛶ Full Screen (Landscape)';
                try { screen.orientation.unlock(); } catch (e) {}
            }
        }
        document.addEventListener('fullscreenchange', onFsChange);
        document.addEventListener('webkitfullscreenchange', onFsChange);

        // --- 3. Click / Tap sender (pointer events = mouse + touch dono) ---
        video.oncontextmenu = (e) => e.preventDefault();
        fbImg.oncontextmenu = (e) => e.preventDefault();

        function onPointerDown(e) {
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
            // Keyboard hamesha ON: hidden input par focus rakho
            setTimeout(() => kbInput.focus(), 0);
        }
        video.onpointerdown = onPointerDown;
        fbImg.onpointerdown = onPointerDown;

        // --- 4. Keyboard sender (hamesha ON, koi toggle button nahi) ---
        const kbInput = document.getElementById('kb-input');
        kbInput.focus();

        // Special keys aur shortcuts (Enter, arrows, Ctrl+C, F-keys...)
        document.addEventListener('keydown', (e) => {
            if (e.isComposing) return;
            if (e.key === 'Unidentified' || e.key === 'Process') return;
            if (['Shift', 'Control', 'Alt', 'Meta', 'Dead'].includes(e.key)) return;

            const isSpecial = e.key.length > 1;
            const hasShortcut = e.ctrlKey || e.altKey || e.metaKey;
            if (isSpecial || hasShortcut) {
                e.preventDefault();
                socket.emit('key_press', {
                    key: e.key, ctrl: e.ctrlKey, alt: e.altKey,
                    shift: e.shiftKey, meta: e.metaKey
                });
            }
            // Normal printable characters neeche 'input' event se jaate hain.
        });

        // Phone virtual keyboard: Backspace / Enter
        kbInput.addEventListener('beforeinput', (e) => {
            if (e.inputType === 'deleteContentBackward') {
                socket.emit('key_press', { key: 'Backspace' });
            } else if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') {
                e.preventDefault();
                socket.emit('key_press', { key: 'Enter' });
            }
        });

        // Printable text
        kbInput.addEventListener('input', (e) => {
            if (e.isComposing) return;   // compositionend ka intezar
            if (e.inputType === 'insertText' && e.data) {
                socket.emit('key_text', { text: e.data });
            }
            kbInput.value = '';
        });
        kbInput.addEventListener('compositionend', (e) => {
            if (e.data) socket.emit('key_text', { text: e.data });
            kbInput.value = '';
        });
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


def to_viewer(event, data=None):
    if viewer_sid:
        if data is None:
            emit(event, to=viewer_sid)
        else:
            emit(event, data, to=viewer_sid)


def to_host(event, data=None):
    if host_sid:
        if data is None:
            emit(event, to=host_sid)
        else:
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


# --- Keyboard events: Viewer -> Host ---
@socketio.on('key_text')
def handle_key_text(data):
    if request.sid == viewer_sid:
        to_host('key_text', data)


@socketio.on('key_press')
def handle_key_press(data):
    if request.sid == viewer_sid:
        to_host('key_press', data)


# --- Relay fallback (TURN ke bina video) ---
@socketio.on('fallback_start')
def handle_fallback_start():
    if request.sid == viewer_sid:
        to_host('fallback_start')


@socketio.on('fallback_stop')
def handle_fallback_stop():
    if request.sid == viewer_sid:
        to_host('fallback_stop')


@socketio.on('frame_ack')
def handle_frame_ack():
    if request.sid == viewer_sid:
        to_host('frame_ack')


@socketio.on('frame')
def handle_frame(data):
    global host_sid
    host_sid = request.sid
    to_viewer('frame', data)


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
