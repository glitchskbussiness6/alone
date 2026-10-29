
import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import socket
import struct
import threading
import time

from flask import Flask, jsonify, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=20,
    ping_timeout=60,
    max_http_buffer_size=20 * 1024 * 1024,
)

# Sirf ek active viewer aur ek host track hota hai
viewer_sid = None
host_sid = None

# =====================================================================
#  TURN SERVER (pure Python, UDP)  -- RFC 5766 ka zaruri hissa
#
#  IMPORTANT: Render UDP allow nahi karta, isliye Render par ye AUTO-OFF rehta hai.
#  Delhi VPS par chalao (UDP 3478 + relay ports ka range firewall mein kholo).
#
#  Env variables:
#    TURN_ENABLE      1/0   (default: VPS par 1, Render par 0)
#    TURN_PUBLIC_IP   VPS ka public IP (zaruri, warna local IP guess hota hai)
#    TURN_PORT        default 3478 (UDP)
#    TURN_MIN_PORT / TURN_MAX_PORT   relay ports ka range, default 49160-49200 (UDP)
#    TURN_SECRET      shared secret (na do to har start par random; viewer/host /ice se lete hain)
#    ICE_EXTRA        JSON list, external TURN ke liye (Render par use karo), e.g.
#                     [{"urls":["turn:x:80"],"username":"u","credential":"p"}]
# =====================================================================
TURN_ENABLE = os.environ.get('TURN_ENABLE', '0' if os.environ.get('RENDER') else '1') == '1'
TURN_PORT = int(os.environ.get('TURN_PORT', 3478))
TURN_MIN_PORT = int(os.environ.get('TURN_MIN_PORT', 49160))
TURN_MAX_PORT = int(os.environ.get('TURN_MAX_PORT', 49200))
TURN_REALM = os.environ.get('TURN_REALM', 'remote')
TURN_SECRET = os.environ.get('TURN_SECRET') or secrets.token_hex(16)
TURN_PUBLIC_IP = os.environ.get('TURN_PUBLIC_IP', '')

DEFAULT_EXTRA = [{
    'urls': ['turn:openrelay.metered.ca:80', 'turn:openrelay.metered.ca:443',
             'turns:openrelay.metered.ca:443?transport=tcp'],
    'username': 'openrelayproject',
    'credential': 'openrelayproject',
}]
try:
    ICE_EXTRA = json.loads(os.environ['ICE_EXTRA']) if os.environ.get('ICE_EXTRA') else None
except Exception as _e:
    print('ICE_EXTRA parse error:', _e)
    ICE_EXTRA = None
if ICE_EXTRA is None:
    ICE_EXTRA = [] if TURN_ENABLE else DEFAULT_EXTRA

MAGIC = 0x2112A442
A_MAPPED, A_USER, A_MI, A_ERR = 0x0001, 0x0006, 0x0008, 0x0009
A_CHANNEL, A_LIFETIME, A_XPEER, A_DATA = 0x000C, 0x000D, 0x0012, 0x0013
A_REALM, A_NONCE, A_RELAYED, A_TRANSPORT = 0x0014, 0x0015, 0x0016, 0x0019
A_XMAPPED = 0x0020


def guess_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


if TURN_ENABLE and not TURN_PUBLIC_IP:
    TURN_PUBLIC_IP = guess_local_ip()
    print(f'[TURN] TURN_PUBLIC_IP set nahi hai, local IP use ho raha hai: {TURN_PUBLIC_IP}')


def attr_pack(t, v):
    return struct.pack('!HH', t, len(v)) + v + b'\x00' * ((-len(v)) % 4)


def build_msg(mtype, txid, attrs, key=None):
    body = b''.join(attr_pack(t, v) for t, v in attrs)
    if key:
        hdr = struct.pack('!HHI12s', mtype, len(body) + 24, MAGIC, txid)
        body += attr_pack(A_MI, hmac.new(key, hdr + body[:], hashlib.sha1).digest())
    return struct.pack('!HHI12s', mtype, len(body), MAGIC, txid) + body


def parse_msg(data):
    if len(data) < 20:
        return None
    mtype, length, cookie, txid = struct.unpack('!HHI12s', data[:20])
    if cookie != MAGIC or length + 20 > len(data) or length % 4:
        return None
    attrs, mi_off, off, end = [], None, 20, 20 + length
    while off + 4 <= end:
        t, l = struct.unpack('!HH', data[off:off + 4])
        v = data[off + 4:off + 4 + l]
        if len(v) < l:
            return None
        if t == A_MI and mi_off is None:
            mi_off = off
        attrs.append((t, v))
        off += 4 + l + ((-l) % 4)
    return mtype, txid, attrs, mi_off


def xor_addr_pack(ip, port):
    a = struct.unpack('!I', socket.inet_aton(ip))[0] ^ MAGIC
    return struct.pack('!BBH', 0, 1, port ^ (MAGIC >> 16)) + struct.pack('!I', a)


def xor_addr_unpack(v):
    if len(v) < 8 or v[1] != 1:
        return None
    port = struct.unpack('!H', v[2:4])[0] ^ (MAGIC >> 16)
    ip = socket.inet_ntoa(struct.pack('!I', struct.unpack('!I', v[4:8])[0] ^ MAGIC))
    return ip, port


def err_attr(code, reason):
    return (A_ERR, struct.pack('!HBB', 0, code // 100, code % 100) + reason.encode())


def make_nonce():
    ts = format(int(time.time()), 'x')
    return ts + hmac.new(TURN_SECRET.encode(), ts.encode(), hashlib.sha1).hexdigest()[:16]


def nonce_ok(n):
    try:
        ts, sig = n[:-16], n[-16:]
        good = hmac.new(TURN_SECRET.encode(), ts.encode(), hashlib.sha1).hexdigest()[:16]
        return hmac.compare_digest(sig, good) and time.time() - int(ts, 16) < 600
    except Exception:
        return False


def turn_password(user):
    return base64.b64encode(hmac.new(TURN_SECRET.encode(), user.encode(), hashlib.sha1).digest()).decode()


def make_turn_credentials(ttl=12 * 3600):
    user = f'{int(time.time()) + ttl}:remote'
    return user, turn_password(user)


def authenticate(mtype, txid, raw, attrs, mi_off):
    """returns (key, reason). key None => reason 'challenge' / 'stale' / 'unauth'"""
    d = dict(attrs)
    if mi_off is None or A_USER not in d:
        return None, 'challenge'
    if not nonce_ok(d.get(A_NONCE, b'').decode(errors='ignore')):
        return None, 'stale'
    user = d[A_USER].decode(errors='ignore')
    try:
        if int(user.split(':')[0]) < time.time():
            return None, 'unauth'
    except Exception:
        return None, 'unauth'
    key = hashlib.md5(f'{user}:{TURN_REALM}:{turn_password(user)}'.encode()).digest()
    hdr = struct.pack('!HHI12s', mtype, mi_off - 20 + 24, MAGIC, txid)
    good = hmac.new(key, hdr + raw[20:mi_off], hashlib.sha1).digest()
    if not hmac.compare_digest(good, d[A_MI]):
        return None, 'unauth'
    return key, None


class Allocation:
    def __init__(self, client):
        self.client = client
        self.transport = None
        self.port = 0
        self.expires = time.time() + 600
        self.perms = {}          # peer ip -> expiry
        self.ch_to_peer = {}     # channel -> (ip, port)
        self.peer_to_ch = {}     # (ip, port) -> channel


class RelayProtocol(asyncio.DatagramProtocol):
    def __init__(self, server, alloc):
        self.server, self.alloc = server, alloc

    def datagram_received(self, data, addr):
        self.server.from_peer(self.alloc, data, addr)


class TurnServer(asyncio.DatagramProtocol):
    def __init__(self, loop):
        self.loop = loop
        self.transport = None
        self.allocs = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if not data:
            return
        top = data[0] >> 6
        if top == 0:
            self.loop.create_task(self.handle_stun(data, addr))
        elif top == 1:
            self.handle_channel(data, addr)

    # ---- peer -> client ----
    def from_peer(self, alloc, data, peer):
        if alloc.perms.get(peer[0], 0) < time.time():
            return
        ch = alloc.peer_to_ch.get(peer)
        if ch:
            self.transport.sendto(struct.pack('!HH', ch, len(data)) + data, alloc.client)
        else:
            msg = build_msg(0x0017, os.urandom(12),
                            [(A_XPEER, xor_addr_pack(*peer)), (A_DATA, data)])
            self.transport.sendto(msg, alloc.client)

    # ---- client -> peer (ChannelData) ----
    def handle_channel(self, data, addr):
        if len(data) < 4:
            return
        ch, ln = struct.unpack('!HH', data[:4])
        alloc = self.allocs.get(addr)
        if not alloc:
            return
        peer = alloc.ch_to_peer.get(ch)
        if peer and alloc.transport and alloc.perms.get(peer[0], 0) >= time.time():
            alloc.transport.sendto(data[4:4 + ln], peer)

    async def open_relay(self, alloc):
        for _ in range(60):
            port = random.randint(TURN_MIN_PORT, TURN_MAX_PORT)
            try:
                tr, _p = await self.loop.create_datagram_endpoint(
                    lambda: RelayProtocol(self, alloc), local_addr=('0.0.0.0', port))
                alloc.transport, alloc.port = tr, port
                return True
            except OSError:
                continue
        return False

    def close_alloc(self, addr):
        a = self.allocs.pop(addr, None)
        if a and a.transport:
            a.transport.close()

    async def handle_stun(self, raw, addr):
        try:
            await self._handle_stun(raw, addr)
        except Exception as e:
            print('[TURN] error:', e)

    async def _handle_stun(self, raw, addr):
        p = parse_msg(raw)
        if not p:
            return
        mtype, txid, attrs, mi_off = p
        send = lambda m: self.transport.sendto(m, addr)

        if mtype == 0x0001:  # Binding
            send(build_msg(0x0101, txid, [(A_XMAPPED, xor_addr_pack(*addr))]))
            return

        if mtype == 0x0016:  # Send indication
            alloc = self.allocs.get(addr)
            peer = next((xor_addr_unpack(v) for t, v in attrs if t == A_XPEER), None)
            data = next((v for t, v in attrs if t == A_DATA), None)
            if alloc and peer and data is not None and alloc.perms.get(peer[0], 0) >= time.time():
                alloc.transport.sendto(data, peer)
            return

        if mtype not in (0x0003, 0x0004, 0x0008, 0x0009):
            return
        err_type = mtype | 0x0110
        ok_type = mtype | 0x0100

        key, why = authenticate(mtype, txid, raw, attrs, mi_off)
        if key is None:
            code, text = (438, 'Stale Nonce') if why == 'stale' else (401, 'Unauthorized')
            send(build_msg(err_type, txid, [
                err_attr(code, text),
                (A_REALM, TURN_REALM.encode()),
                (A_NONCE, make_nonce().encode()),
            ]))
            return

        now = time.time()
        alloc = self.allocs.get(addr)

        if mtype == 0x0003:  # Allocate
            if alloc:
                send(build_msg(err_type, txid, [err_attr(437, 'Allocation Mismatch')], key))
                return
            tr = next((v for t, v in attrs if t == A_TRANSPORT), None)
            if not tr or tr[0] != 17:
                send(build_msg(err_type, txid, [err_attr(442, 'Unsupported Transport')], key))
                return
            alloc = Allocation(addr)
            if not await self.open_relay(alloc):
                send(build_msg(err_type, txid, [err_attr(508, 'Insufficient Capacity')], key))
                return
            self.allocs[addr] = alloc
            print(f'[TURN] allocation {addr} -> relay port {alloc.port}')
            send(build_msg(ok_type, txid, [
                (A_RELAYED, xor_addr_pack(TURN_PUBLIC_IP, alloc.port)),
                (A_LIFETIME, struct.pack('!I', 600)),
                (A_XMAPPED, xor_addr_pack(*addr)),
            ], key))
            return

        if not alloc:
            send(build_msg(err_type, txid, [err_attr(437, 'Allocation Mismatch')], key))
            return

        if mtype == 0x0004:  # Refresh
            lt = next((struct.unpack('!I', v[:4])[0] for t, v in attrs if t == A_LIFETIME and len(v) >= 4), 600)
            lt = min(lt, 3600)
            if lt == 0:
                self.close_alloc(addr)
            else:
                alloc.expires = now + lt
            send(build_msg(ok_type, txid, [(A_LIFETIME, struct.pack('!I', lt))], key))

        elif mtype == 0x0008:  # CreatePermission
            peers = [xor_addr_unpack(v) for t, v in attrs if t == A_XPEER]
            peers = [x for x in peers if x]
            if not peers:
                send(build_msg(err_type, txid, [err_attr(400, 'Bad Request')], key))
                return
            for ip, _port in peers:
                alloc.perms[ip] = now + 300
            send(build_msg(ok_type, txid, [], key))

        elif mtype == 0x0009:  # ChannelBind
            chv = next((v for t, v in attrs if t == A_CHANNEL), None)
            peer = next((xor_addr_unpack(v) for t, v in attrs if t == A_XPEER), None)
            if not chv or len(chv) < 2 or not peer:
                send(build_msg(err_type, txid, [err_attr(400, 'Bad Request')], key))
                return
            ch = struct.unpack('!H', chv[:2])[0]
            old = alloc.ch_to_peer.get(ch)
            if not (0x4000 <= ch <= 0x7FFF) or (old and old != peer) or \
                    (peer in alloc.peer_to_ch and alloc.peer_to_ch[peer] != ch):
                send(build_msg(err_type, txid, [err_attr(400, 'Bad Request')], key))
                return
            alloc.ch_to_peer[ch] = peer
            alloc.peer_to_ch[peer] = ch
            alloc.perms[peer[0]] = now + 300
            send(build_msg(ok_type, txid, [], key))

    async def cleanup(self):
        while True:
            await asyncio.sleep(15)
            now = time.time()
            for addr in [a for a, al in self.allocs.items() if al.expires < now]:
                print('[TURN] allocation expired', addr)
                self.close_alloc(addr)


def run_turn():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    srv = TurnServer(loop)
    try:
        loop.run_until_complete(loop.create_datagram_endpoint(
            lambda: srv, local_addr=('0.0.0.0', TURN_PORT)))
    except Exception as e:
        print('[TURN] start nahi hua:', e)
        return
    loop.create_task(srv.cleanup())
    print(f'[TURN] chal raha hai udp://{TURN_PUBLIC_IP}:{TURN_PORT} '
          f'(relay ports {TURN_MIN_PORT}-{TURN_MAX_PORT})')
    loop.run_forever()


def ice_servers():
    servers = [{'urls': 'stun:stun.l.google.com:19302'}]
    if TURN_ENABLE:
        u, c = make_turn_credentials()
        servers.append({
            'urls': [f'turn:{TURN_PUBLIC_IP}:{TURN_PORT}?transport=udp'],
            'username': u, 'credential': c,
        })
    servers.extend(ICE_EXTRA)
    return servers


# =====================================================================

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
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <button id="fs-btn">⛶ Full Screen (Landscape)</button>
    <textarea id="kb-input" autocapitalize="off" autocomplete="off"
              autocorrect="off" spellcheck="false"></textarea>
    <div id="toast"></div>
    <div id="loader"><div class="spinner"></div><div id="loader-text">Connecting to server...</div></div>

    <svg id="remote-cursor" viewBox="0 0 24 24">
        <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2.9-3.2-7.4-4.4 4.7z"/>
    </svg>

    <video id="video-stream" autoplay playsinline webkit-playsinline muted></video>
    <img id="fb-img" alt="" draggable="false">

    <script>
        // ====== ICE CONFIG ======
        // Ab server se /ice endpoint se aata hai (server ka apna TURN ya ICE_EXTRA).
        let ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }];
        async function loadIce() {
            try {
                const ctl = new AbortController();
                const t = setTimeout(() => ctl.abort(), 4000);
                const r = await fetch('/ice', { cache: 'no-store', signal: ctl.signal });
                clearTimeout(t);
                const j = await r.json();
                if (Array.isArray(j) && j.length) ICE_SERVERS = j;
            } catch (e) { console.log('ICE fetch fail', e); }
        }
        loadIce();
        // =========================

        const socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 500,
            reconnectionDelayMax: 3000,
            timeout: 20000
        });
        const video = document.getElementById('video-stream');
        const cursor = document.getElementById('remote-cursor');
        const statusEl = { style: {}, textContent: '' };  // status UI hata diya

        let pc = null;
        let pendingCandidates = [];

        // ====== RELAY FALLBACK ======
        const FALLBACK_AFTER_MS = 6000;
        const forceRelay = new URLSearchParams(location.search).get('mode') === 'relay';
        const fbImg = document.getElementById('fb-img');
        let useFallback = false;
        let fbFrames = 0;
        let fbUrl = null;
        let connWatch = null;

        // ====== LOADER (connection progress) ======
        let serverUp = false, hostAlive = false, mediaLive = false;
        let lastFrameAt = 0;
        const loaderEl = document.getElementById('loader');
        const loaderTextEl = document.getElementById('loader-text');

        function refreshLoader() {
            if (serverUp && hostAlive && mediaLive) {
                loaderEl.style.display = 'none';
                return;
            }
            loaderEl.style.display = 'flex';
            loaderTextEl.textContent = !serverUp ? 'Connecting to server...'
                : !hostAlive ? 'Host offline - waiting for host...'
                : 'Host online - connecting...';
        }
        // ==========================================

        fbImg.onload = () => { fbFrames++; mediaLive = true; refreshLoader(); };

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
            lastFrameAt = Date.now();
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
                    if (!forceRelay) { mediaLive = true; refreshLoader(); }
                    if (!forceRelay) stopFallback();
                    setTimeout(() => { if (!useFallback) statusEl.style.display = 'none'; }, 2000);
                } else {
                    statusEl.style.display = 'block';
                    if (pc.connectionState === 'failed') startFallback();
                    if (pc.connectionState === 'disconnected') {
                        setTimeout(() => {
                            if (pc && pc.connectionState !== 'connected') startFallback();
                        }, 5000);
                    }
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
            hostAlive = true;
            mediaLive = false;
            refreshLoader();
            resetFallbackUI();   // naya handshake: purana relay state saaf
            try {
                await loadIce();  // taaza TURN credentials
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

        socket.on('host_status', (d) => {
            hostAlive = !!(d && d.alive);
            if (!hostAlive) mediaLive = false;
            refreshLoader();
        });
        socket.on('disconnect', () => {
            serverUp = false; hostAlive = false; mediaLive = false;
            refreshLoader();
        });
        socket.on('connect_error', () => {
            serverUp = false; refreshLoader();
        });

        socket.on('connect', () => {
            serverUp = true; hostAlive = false; mediaLive = false;
            refreshLoader();
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

        // --- 3. Click / Tap sender ---
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
            setTimeout(() => kbInput.focus(), 0);
        }
        video.onpointerdown = onPointerDown;
        fbImg.onpointerdown = onPointerDown;

        // --- 4. Keyboard sender ---
        const kbInput = document.getElementById('kb-input');
        kbInput.focus();

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
        });

        kbInput.addEventListener('beforeinput', (e) => {
            if (e.inputType === 'deleteContentBackward') {
                socket.emit('key_press', { key: 'Backspace' });
            } else if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') {
                e.preventDefault();
                socket.emit('key_press', { key: 'Enter' });
            }
        });

        kbInput.addEventListener('input', (e) => {
            if (e.isComposing) return;
            if (e.inputType === 'insertText' && e.data) {
                socket.emit('key_text', { text: e.data });
            }
            kbInput.value = '';
        });
        kbInput.addEventListener('compositionend', (e) => {
            if (e.data) socket.emit('key_text', { text: e.data });
            kbInput.value = '';
        });

        // --- 5. Robustness ---
        setInterval(() => {
            if (!socket.connected) return;
            if (useFallback && mediaLive) {
                const idle = Date.now() - lastFrameAt;
                if (idle > 6000) socket.emit('fallback_start');
                if (idle > 15000) {
                    mediaLive = false;
                    refreshLoader();
                    lastFrameAt = Date.now();
                    socket.emit('viewer_joined');
                }
            }
        }, 2000);

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                if (!socket.connected) socket.connect();
                requestWakeLock();
            }
        });
        window.addEventListener('online', () => { if (!socket.connected) socket.connect(); });

        let wakeLock = null;
        async function requestWakeLock() {
            try {
                if ('wakeLock' in navigator && !wakeLock) {
                    wakeLock = await navigator.wakeLock.request('screen');
                    wakeLock.addEventListener('release', () => { wakeLock = null; });
                }
            } catch (e) {}
        }
        requestWakeLock();
        document.addEventListener('pointerdown', requestWakeLock);
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


@app.route('/ice')
def ice():
    resp = jsonify(ice_servers())
    resp.headers['Cache-Control'] = 'no-store'
    return resp


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
        if host_sid:
            socketio.emit('viewer_left', to=host_sid)
    if request.sid == host_sid:
        host_sid = None
        if viewer_sid:
            socketio.emit('host_status', {'alive': False}, to=viewer_sid)


# --- Host presence ---
@socketio.on('host_hello')
def handle_host_hello():
    global host_sid
    host_sid = request.sid
    if viewer_sid:
        emit('host_status', {'alive': True}, to=viewer_sid)
        emit('viewer_joined', to=host_sid)


@socketio.on('host_ping')
def handle_host_ping():
    global host_sid
    changed = host_sid != request.sid
    host_sid = request.sid
    if changed and viewer_sid:
        emit('host_status', {'alive': True}, to=viewer_sid)


# --- Viewer -> Host ---
@socketio.on('viewer_joined')
def handle_join():
    global viewer_sid
    viewer_sid = request.sid
    emit('host_status', {'alive': host_sid is not None})
    emit('viewer_joined', broadcast=True, include_self=False)


@socketio.on('answer')
def handle_answer(data):
    if request.sid == viewer_sid:
        to_host('answer', data)


@socketio.on('mouse_click')
def handle_mouse_click(data):
    if request.sid == viewer_sid:
        to_host('mouse_click', data)


@socketio.on('key_text')
def handle_key_text(data):
    if request.sid == viewer_sid:
        to_host('key_text', data)


@socketio.on('key_press')
def handle_key_press(data):
    if request.sid == viewer_sid:
        to_host('key_press', data)


# --- Relay fallback ---
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
    if TURN_ENABLE:
        threading.Thread(target=run_turn, daemon=True).start()
    else:
        print('[TURN] built-in TURN band hai (Render par UDP nahi chalta). '
              'ICE_EXTRA ya default openrelay use hoga.')
    print(f"Relay Server Running on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
