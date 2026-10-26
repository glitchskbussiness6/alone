import time
import cv2
import numpy as np
import threading
import pyautogui
from pynput import keyboard
import mss
import socketio

pyautogui.FAILSAFE = False

sio = socketio.Client()
RELAY_SERVER_URL = 'https://alone-nni7.onrender.com' 
is_streaming = False

ready_to_send = True

def on_frame_ack(*args):
    """सर्वर से सिग्नल मिलते ही पाइप को फिर से ओपन कर दो"""
    global ready_to_send
    ready_to_send = True

def capture_screen():
    global is_streaming, ready_to_send
    
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            if not sio.connected or not is_streaming:
                time.sleep(0.1)
                continue

            try:
                # 🚀 THE MAGIC TRICK: "FIRE AND FORGET"
                # अगर पुराना फ्रेम अभी तक रास्ते में है, तो इस नए फ्रेम को स्टोर मत करो, सीधा DROP (नष्ट) कर दो!
                if not ready_to_send:
                    time.sleep(0.005) # बस हल्का सा स्लीप ताकि CPU क्रैश न हो
                    continue # फ्रेम ड्रॉप हो गया! कोई लैग नहीं जुड़ेगा।

                # जब नेटवर्क एकदम खाली हो, तभी ताज़ा फ्रेम कैप्चर करो
                sct_img = sct.grab(monitor)
                frame = np.array(sct_img)
                
                # हल्का रिज़ॉल्यूशन और मीडियम क्वालिटी (ताकि झटके से ट्रांसफर हो)
                frame = cv2.resize(frame, (1024, 576))
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                _, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 45])
                
                # पाइप को लॉक करो और डेटा फायर करो
                ready_to_send = False
                sio.emit('video_frame', {'image': buffer.tobytes()}, callback=on_frame_ack)
                
            except Exception as e:
                print(f"[!] Streaming Error: {e}")
                ready_to_send = True 
                time.sleep(1)

@sio.on('execute_click')
def on_click(data):
    if not is_streaming: return
    x, y = data['x'], data['y']
    screen_width, screen_height = pyautogui.size()
    pyautogui.click(int(x * screen_width), int(y * screen_height))

@sio.on('execute_scroll')
def on_scroll(data):
    if not is_streaming: return
    direction = data['direction']
    pyautogui.scroll(-100 if direction == "down" else 100)

@sio.on('execute_keyboard')
def on_keyboard(data):
    if not is_streaming: return
    key = data.get('text', '')
    if not key: return

    special_keys = {
        'Enter': 'enter', 'Backspace': 'backspace', 'Tab': 'tab',
        'Escape': 'esc', 'ArrowUp': 'up', 'ArrowDown': 'down',
        'ArrowLeft': 'left', 'ArrowRight': 'right', ' ': 'space'
    }
    
    try:
        if key in special_keys:
            pyautogui.press(special_keys[key])
        elif len(key) == 1:
            pyautogui.write(key)
        else:
            pyautogui.press(key.lower())
    except:
        pass

def on_press(key):
    global is_streaming
    if key == keyboard.Key.media_volume_down:
        is_streaming = True
        print(" -> Stream Started (Fire & Forget Mode)")
    elif key == keyboard.Key.media_volume_up:
        is_streaming = False
        print(" -> Stream Paused")

if __name__ == '__main__':
    print(f"Connecting to Relay Server at {RELAY_SERVER_URL} ...")
    try:
        sio.connect(RELAY_SERVER_URL)
        print("Successfully connected!")
    except Exception as e:
        print(f"Connection failed: {e}")
    
    threading.Thread(target=capture_screen, daemon=True).start()

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
