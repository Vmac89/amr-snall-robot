# Legacy reference. server.py does not import this file.
# It opens the Kinect once with the libfreenect async API and shares that
# handle for video and tilt, writes JPEGs to /dev/shm/kinect.jpg, and reads
# /dev/shm/tilt_cmd.txt.

import os
import cv2
import numpy as np
import signal
import sys
import time
import freenect

print("--- ROBZONE TACTICAL ENGINE: STABLE STREAM v11.8 (ASYNC COMBINED LOCK FIX) ---")

current_tilt = 0
keep_running = True
last_frame_time = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def cleanup_and_exit(sig, frame):
    global keep_running
    print("\n--- SHUTTING DOWN CLEANLY ---")
    keep_running = False

signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)

def video_callback(dev, video_data, timestamp):
    global last_frame_time
    try:
        frame = cv2.cvtColor(video_data, cv2.COLOR_RGB2BGR)
        tmp_path = '/dev/shm/kinect_tmp.jpg'
        final_path = '/dev/shm/kinect.jpg'
        cv2.imwrite(tmp_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        os.replace(tmp_path, final_path)
        last_frame_time = time.time()
    except Exception as e:
        pass

def process_tilt_commands(dev):
    global current_tilt
    cmd_path = '/dev/shm/tilt_cmd.txt'
    if os.path.exists(cmd_path):
        try:
            with open(cmd_path, 'r') as f:
                cmd = f.read().strip()
            os.remove(cmd_path)
            if cmd == 'up': current_tilt += 3
            elif cmd == 'down': current_tilt -= 3
            current_tilt = max(-30, min(30, current_tilt))
            freenect.set_tilt_degs(dev, current_tilt)
            print(f"[ENGINE] Hardware precision tilt adjusted safely via async loop to {current_tilt}°")
        except Exception as e:
            print(f"[ENGINE ERROR] Async hardware tilt adjustment failed: {e}")
    try:
        with open('/dev/shm/dist.txt', 'w') as f:
            f.write("120.5")
    except:
        pass

def main_engine_loop():
    global keep_running, last_frame_time
    print("[SYSTEM] Initializing asynchronous OpenKinect engine mapping layers...")
    if os.path.exists('/dev/shm/tilt_cmd.txt'):
        os.remove('/dev/shm/tilt_cmd.txt')
    ctx = freenect.init()
    try:
        dev = freenect.open_device(ctx, 0)
    except Exception as e:
        print(f"[FATAL] Cannot open Kinect hardware over USB: {e}")
        print("Please verify that your external wall-outlet power adapter brick is active.")
        sys.exit(1)
    freenect.set_video_callback(dev, video_callback)
    freenect.set_video_mode(dev, freenect.RESOLUTION_MEDIUM, freenect.VIDEO_RGB)
    freenect.start_video(dev)
    print("[SYSTEM] Headless stream link established. Tracking queue operational.")
    bg_matrix = np.zeros((480, 640, 3), dtype=np.uint8)
    while keep_running:
        try:
            freenect.process_events(ctx)
            process_tilt_commands(dev)
            if time.time() - last_frame_time > 1.5:
                frame = bg_matrix.copy()
                cv2.putText(frame, "HARDWARE SENSORS INITIALIZING...", (30, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.putText(frame, time.strftime("%H:%M:%S REALTIME"), (30, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 217, 255), 1)
                tmp_path = '/dev/shm/kinect_tmp.jpg'
                final_path = '/dev/shm/kinect.jpg'
                cv2.imwrite(tmp_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                os.replace(tmp_path, final_path)
            time.sleep(0.005)
        except Exception as loop_err:
            print(f"[ENGINE RUNTIME ERROR] Loop iteration skipped: {loop_err}")
            time.sleep(0.05)
    print("[SYSTEM] Halting data capture interfaces safely...")
    freenect.stop_video(dev)
    freenect.close_device(dev)
    freenect.shutdown(ctx)
    sys.exit(0)

if __name__ == '__main__':
    if os.geteuid() != 0:
        print("\n[CRITICAL] Engine must be launched using sudo over SSH tunnels!")
        print("Run: sudo python3 streamer.py\n")
        sys.exit(1)
    main_engine_loop()
