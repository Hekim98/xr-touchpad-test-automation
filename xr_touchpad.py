#!/usr/bin/env python3
"""
XR Touchpad Reliability Test Automation Suite
============================================
Automates hardware device discovery, Wi-Fi TCP/IP pairing, live gesture capture,
in-terminal prompt orchestration, multi-layer log filtering (Android MotionEvents + Linux evdev),
spatial-temporal touch alignment, and automated test session bundling.

Author: Hekim (https://github.com/Hekim98)
License: MIT
"""

import os
import sys
import time
import re
import csv
import glob
import signal
import select
import threading
import subprocess
import argparse
from datetime import datetime

# --- ANSI Terminal Styling ---
class Color:
    RESET = '\033[0m'
    GREEN = '\033[0;32m'
    CYAN = '\033[0;36m'
    YELLOW = '\033[1;33m'
    BOLD = '\033[1m'
    PINK = '\033[1;35m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'

def log_info(msg):
    print(f"{Color.CYAN}ℹ️  {msg}{Color.RESET}")

def log_success(msg):
    print(f"{Color.GREEN}✅ {msg}{Color.RESET}")

def log_warning(msg):
    print(f"{Color.YELLOW}⚠️  {msg}{Color.RESET}")

def log_error(msg):
    print(f"{Color.RED}❌ {msg}{Color.RESET}")

def log_header(msg):
    print(f"\n{Color.BOLD}{Color.PINK}=== {msg} ==={Color.RESET}\n")

# --- ADB Helper Functions ---
def run_adb(cmd_args, serial=None, timeout=30):
    """Executes an ADB command with optional target serial and timeout."""
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(cmd_args)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout expired"
    except Exception as e:
        return -1, "", str(e)

def run_adb_phone(cmd_args, timeout=30):
    """Target USB phone directly using adb -d."""
    cmd = ["adb", "-d"] + cmd_args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def detect_devices():
    """
    Scans attached ADB devices and classifies them as Companion Phone vs Smart Glass / Wearable.
    """
    log_info("Scanning connected ADB devices...")
    ret, out, _ = run_adb(["devices", "-l"])
    if ret != 0:
        log_error("Failed to run 'adb devices'. Ensure ADB is installed and in PATH.")
        return None, None, None

    lines = out.splitlines()[1:]
    phone_serial = None
    glasses_serial = None
    glasses_ip = None

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]

        # Check if it's a Wi-Fi TCP/IP connection (Wearable Glasses)
        if ":5555" in serial:
            glasses_serial = serial
            glasses_ip = serial
            continue

        # Inspect product/model via getprop
        _, flavor, _ = run_adb(["shell", "getprop", "ro.build.flavor"], serial=serial, timeout=5)
        _, model, _ = run_adb(["shell", "getprop", "ro.product.model"], serial=serial, timeout=5)
        
        combined = f"{flavor} {model} {line}".lower()
        if "glasses" in combined or "glass" in combined or "wearable" in combined or "xr" in combined:
            glasses_serial = serial
        else:
            phone_serial = serial

    log_info(f"Companion Phone Serial : {Color.BOLD}{phone_serial or 'None'}{Color.RESET}")
    log_info(f"Wearable Device Serial : {Color.BOLD}{glasses_serial or 'None'}{Color.RESET}")
    if glasses_ip:
        log_info(f"Wearable Wi-Fi Target  : {Color.BOLD}{glasses_ip}{Color.RESET}")

    return phone_serial, glasses_serial, glasses_ip

def ensure_glasses_keepalive(glasses_serial):
    """Applies power and battery spoofing to prevent Wi-Fi and CPU sleep dropouts during testing."""
    if not glasses_serial:
        return
    log_info(f"Applying keepalive & disabling power-save on wearable ({glasses_serial})...")
    run_adb(["shell", "dumpsys", "battery", "set", "ac", "1"], serial=glasses_serial)
    run_adb(["shell", "dumpsys", "battery", "set", "status", "2"], serial=glasses_serial)
    run_adb(["shell", "dumpsys", "battery", "set", "level", "100"], serial=glasses_serial)
    run_adb(["shell", "settings", "put", "global", "stay_on_while_plugged_in", "7"], serial=glasses_serial)
    run_adb(["shell", "svc", "power", "stayon", "true"], serial=glasses_serial)
    run_adb(["shell", "dumpsys", "deviceidle", "disable"], serial=glasses_serial)
    run_adb(["shell", "su", "0", "iw", "dev", "wlan0", "set", "power_save", "off"], serial=glasses_serial)

def connect_glasses_to_ap(ssid=None, password=None, usb_glasses_serial=None):
    """Configures Wi-Fi AP connection and enables TCP/IP debugging on the wearable device."""
    log_header("Connecting Wearable Device to Wi-Fi AP")
    target = usb_glasses_serial
    
    if not ssid:
        ssid = os.environ.get("XR_WIFI_SSID")
    if not password:
        password = os.environ.get("XR_WIFI_PASSWORD")

    if not ssid:
        ssid = input("Enter Wi-Fi SSID for test station: ").strip()
    if password is None:
        password = input("Enter Wi-Fi Password (leave blank for open network): ").strip()

    log_info("Enabling Wi-Fi and TCP/IP port 5555 on device...")
    run_adb(["shell", "setprop", "persist.adb.tcp.port", "5555"], serial=target)
    run_adb(["shell", "svc", "wifi", "enable"], serial=target)
    run_adb(["shell", "cmd", "wifi", "set-wifi-enabled", "enabled"], serial=target)
    
    if ssid:
        log_info(f"Connecting to Wi-Fi SSID '{ssid}'...")
        if password:
            run_adb(["shell", "cmd", "wifi", "connect-network", f"'{ssid}'", "wpa2", f"'{password}'"], serial=target)
        else:
            run_adb(["shell", "cmd", "wifi", "connect-network", f"'{ssid}'", "open"], serial=target)
    
    glasses_ip = None
    for attempt in range(1, 11):
        time.sleep(1)
        # Try IPv6 link-local
        _, v6_out, _ = run_adb(["shell", "ifconfig wlan0 | grep 'inet6 addr' | grep 'Scope: Link' | awk '{print $3}' | cut -d'/' -f1"], serial=target)
        # Try IPv4
        _, v4_out, _ = run_adb(["shell", "ifconfig wlan0 | grep 'inet addr' | awk -F: '{print $2}' | awk '{print $1}'"], serial=target)
        
        v6_out = v6_out.strip()
        v4_out = v4_out.strip()
        
        if v6_out:
            glasses_ip = f"[{v6_out}%en0]:5555"
            log_success(f"Found IPv6 address: {v6_out}")
            break
        elif v4_out:
            glasses_ip = f"{v4_out}:5555"
            log_success(f"Found IPv4 address: {v4_out}")
            break
        print(f"  Attempt {attempt}/10: Waiting for IP address assignment...")

    run_adb(["tcpip", "5555"], serial=target)
    time.sleep(2)
    
    if glasses_ip:
        log_info(f"Attempting ADB connection: adb connect {glasses_ip}")
        _, conn_res, _ = run_adb(["connect", glasses_ip])
        if "connected" in conn_res.lower():
            log_success(f"Successfully connected to wearable over Wi-Fi: {glasses_ip}")
            ensure_glasses_keepalive(glasses_ip)
            return glasses_ip
        else:
            log_warning(f"Connection result: {conn_res}")
            return glasses_ip
    else:
        log_error("Could not obtain IP address from wlan0 on wearable device.")
        return None

def setup_glasses_input_overrides(glasses_serial):
    """Extracts capacitive touch device descriptors and configures kernel input overrides."""
    log_header("Configuring Wearable Input Overrides")
    _, dumpsys_out, _ = run_adb(["shell", "dumpsys", "input"], serial=glasses_serial)
    
    # Extract descriptor after TOUCH_MT
    descriptors = []
    lines = dumpsys_out.splitlines()
    for i, line in enumerate(lines):
        if "TOUCH_MT" in line or "touch" in line.lower():
            for sub_line in lines[i:i+10]:
                if "descriptor:" in sub_line or "Descriptor:" in sub_line:
                    desc = sub_line.split(":")[-1].strip().strip("'\"")
                    if desc and len(desc) > 10 and desc not in descriptors:
                        descriptors.append(desc)

    for desc in descriptors:
        log_info(f"Configuring touch input override for descriptor: {desc}")
        run_adb(["shell", "cmd", "input", "add", 
                 "--action", "GLOBAL_ACTION_NONE", 
                 "--gesture", "TOUCH_GESTURE_TAP_AND_HOLD", 
                 "--type", "touch", 
                 f"--descriptor={desc}"], serial=glasses_serial)

    # Enable detailed touchpad logging sysprops
    run_adb(["shell", "setprop", "persist.vendor.input.log", "1"], serial=glasses_serial)
    log_success("Wearable input overrides configured.")

def full_station_setup(ssid=None, password=None):
    """Runs automated full station setup for both companion phone and wearable glasses."""
    log_header("FULL TEST STATION SETUP WIZARD")
    phone_serial, glasses_serial, glasses_ip = detect_devices()
    
    # 1. Phone configuration
    log_info("Configuring companion device settings...")
    run_adb(["shell", "am", "force-stop", "com.example.gesturetracker"], serial=phone_serial)
    log_success("Companion device configured.")
    
    # 2. Wearable Wi-Fi & TCP/IP
    if not glasses_ip:
        glasses_ip = connect_glasses_to_ap(ssid=ssid, password=password, usb_glasses_serial=glasses_serial)
    
    # 3. Input overrides & keepalive
    active_glasses = glasses_ip or glasses_serial
    if active_glasses:
        setup_glasses_input_overrides(active_glasses)
        ensure_glasses_keepalive(active_glasses)
    
    log_success("Station setup completed successfully!")

# --- Spatial and Temporal Log Alignment Engine ---
def parse_and_sync_logs(filtered_file, linux_file, output_csv):
    """
    Correlates high-level Android MotionEvents with raw Linux kernel evdev streams.
    Calculates touch duration, start coordinates, pointer counts, and timing delta.
    """
    android_touches = []
    current_android_touch = {}
    current_prompt = 0

    if os.path.exists(filtered_file):
        with open(filtered_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "User prompted to perform" in line or "user prompted to perform" in line.lower():
                    current_prompt += 1
                elif "ACTION_DOWN" in line:
                    match = re.search(r'x\[0\]=([0-9.]+), y\[0\]=([0-9.]+).*?eventTime=(\d+)', line)
                    if match:
                        current_android_touch = {
                            'prompt_id': current_prompt,
                            'android_start_x': float(match.group(1)),
                            'android_start_y': float(match.group(2)),
                            'android_start_time': int(match.group(3)),
                            'max_pointers': 1
                        }
                elif current_android_touch:
                    ptr_match = re.search(r'pointerCount=(\d+)', line)
                    if ptr_match:
                        count = int(ptr_match.group(1))
                        if count > current_android_touch['max_pointers']:
                            current_android_touch['max_pointers'] = count

                    if "ACTION_UP" in line:
                        match = re.search(r'eventTime=(\d+)', line)
                        if match:
                            current_android_touch['android_end_time'] = int(match.group(1))
                            android_touches.append(current_android_touch)
                            current_android_touch = {}

    linux_touches = []
    current_linux_touch = {}

    if os.path.exists(linux_file):
        with open(linux_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "/dev/input/event" not in line and "event" not in line:
                    continue
                ts_match = re.search(r'\[\s*([\d.]+)\]', line)
                if not ts_match:
                    continue
                timestamp = float(ts_match.group(1))

                if "BTN_TOUCH" in line and "DOWN" in line:
                    current_linux_touch = {
                        'linux_start_time': timestamp,
                        'tracking_ids': set()
                    }
                elif current_linux_touch:
                    if "ABS_MT_TRACKING_ID" in line:
                        hex_val = line.split()[-1]
                        if hex_val != "ffffffff":
                            current_linux_touch['tracking_ids'].add(hex_val)
                    elif "ABS_MT_POSITION_X" in line and 'linux_start_x' not in current_linux_touch:
                        try:
                            current_linux_touch['linux_start_x'] = int(line.split()[-1], 16)
                        except ValueError:
                            pass
                    elif "ABS_MT_POSITION_Y" in line and 'linux_start_y' not in current_linux_touch:
                        try:
                            current_linux_touch['linux_start_y'] = int(line.split()[-1], 16)
                        except ValueError:
                            pass
                    elif "BTN_TOUCH" in line and "UP" in line:
                        current_linux_touch['linux_end_time'] = timestamp
                        current_linux_touch['linux_max_pointers'] = max(1, len(current_linux_touch['tracking_ids']))
                        linux_touches.append(current_linux_touch)
                        current_linux_touch = {}

    # Spatial Alignment (Tolerance within 2.0 scaled pixels)
    all_events = []
    a_idx = 0
    l_idx = 0

    def is_match(a_event, l_event):
        if not a_event or not l_event:
            return False
        ax = a_event.get('android_start_x', 0)
        ay = a_event.get('android_start_y', 0)
        lx = l_event.get('linux_start_x', 0) * 0.34
        ly = l_event.get('linux_start_y', 0) * 0.34
        return abs(ax - lx) < 2.0 and abs(ay - ly) < 2.0

    while a_idx < len(android_touches) and l_idx < len(linux_touches):
        a = android_touches[a_idx]
        l = linux_touches[l_idx]

        if is_match(a, l):
            all_events.append({**a, **l})
            a_idx += 1
            l_idx += 1
        else:
            found_match = False
            for lookahead in range(1, 6):
                if l_idx + lookahead < len(linux_touches) and is_match(a, linux_touches[l_idx + lookahead]):
                    for orphaned_l_idx in range(l_idx, l_idx + lookahead):
                        all_events.append(linux_touches[orphaned_l_idx].copy())
                    l_idx += lookahead
                    found_match = True
                    break
            if found_match:
                continue

            for lookahead in range(1, 6):
                if a_idx + lookahead < len(android_touches) and is_match(android_touches[a_idx + lookahead], l):
                    for orphaned_a_idx in range(a_idx, a_idx + lookahead):
                        all_events.append(android_touches[orphaned_a_idx].copy())
                    a_idx += lookahead
                    found_match = True
                    break
            if found_match:
                continue

            all_events.append({**a, **l})
            a_idx += 1
            l_idx += 1

    while a_idx < len(android_touches):
        all_events.append(android_touches[a_idx].copy())
        a_idx += 1
    while l_idx < len(linux_touches):
        all_events.append(linux_touches[l_idx].copy())
        l_idx += 1

    current_pid = 1
    for event in all_events:
        if 'prompt_id' in event and event['prompt_id'] > 0:
            current_pid = event['prompt_id']
        else:
            event['prompt_id'] = current_pid

    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'Gesture_Number', 'Tap_Count', 'Max_Fingers_Detected',
            'Total_Android_Duration_ms', 'Total_Linux_Duration_ms',
            'Start_Android_X', 'Start_Linux_X_Scaled',
            'Start_Android_Y', 'Start_Linux_Y_Scaled',
            'Android_Start_Time_ms', 'Linux_Start_Time_ms',
            'Sum_of_Last_Two_Linux_Events_ms'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        previous_linux_duration = 0
        for event in all_events:
            if 'android_start_time' in event and 'android_end_time' in event:
                android_dur = event['android_end_time'] - event['android_start_time']
                start_a_x = event.get('android_start_x', '')
                start_a_y = event.get('android_start_y', '')
                max_a_fingers = event.get('max_pointers', 1)
                a_start_time = event['android_start_time']
            else:
                android_dur = start_a_x = start_a_y = a_start_time = ''
                max_a_fingers = 1

            if 'linux_start_time' in event and 'linux_end_time' in event:
                linux_dur = round((event['linux_end_time'] - event['linux_start_time']) * 1000)
                start_l_x = round(event.get('linux_start_x', 0) * 0.34, 2) if 'linux_start_x' in event else ''
                start_l_y = round(event.get('linux_start_y', 0) * 0.34, 2) if 'linux_start_y' in event else ''
                max_l_fingers = event.get('linux_max_pointers', 1)
                l_start_time = round(event['linux_start_time'] * 1000)

                if 'android_start_time' not in event and previous_linux_duration > 0:
                    sum_last_two = previous_linux_duration + linux_dur
                else:
                    sum_last_two = ''

                previous_linux_duration = linux_dur
            else:
                linux_dur = start_l_x = start_l_y = l_start_time = sum_last_two = ''
                max_l_fingers = 1

            writer.writerow({
                'Gesture_Number': event.get('prompt_id', ''),
                'Tap_Count': 1,
                'Max_Fingers_Detected': max(max_a_fingers, max_l_fingers),
                'Total_Android_Duration_ms': android_dur,
                'Total_Linux_Duration_ms': linux_dur,
                'Start_Android_X': start_a_x,
                'Start_Linux_X_Scaled': start_l_x,
                'Start_Android_Y': start_a_y,
                'Start_Linux_Y_Scaled': start_l_y,
                'Android_Start_Time_ms': a_start_time,
                'Linux_Start_Time_ms': l_start_time,
                'Sum_of_Last_Two_Linux_Events_ms': sum_last_two
            })

    log_success(f"Processed {len(all_events)} interactions into '{output_csv}'")
    return len(all_events)

# --- Log Filtering Routine ---
def filter_and_format_logs(raw_phone_log, raw_glasses_log, filtered_output, meta):
    phone_lines = []
    regex_pattern = re.compile(
        r"user prompted to perform|gesture detected, checking input map: gesture =|inputevent received: motionevent \{|advance keyevent detected|all gestures completed|detectonefingergesture|detecttwofingergesture",
        re.IGNORECASE
    )

    if os.path.exists(raw_phone_log):
        paused = False
        with open(raw_phone_log, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "RefractoryState: START" in line:
                    paused = True
                    continue
                if "RefractoryState: END" in line:
                    paused = False
                    continue
                if not paused and regex_pattern.search(line):
                    phone_lines.append(line)

    glasses_lines = []
    glasses_pattern = re.compile(r"detecttwofingergesture|gesture=two_finger_swipe", re.IGNORECASE)
    if os.path.exists(raw_glasses_log):
        with open(raw_glasses_log, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if glasses_pattern.search(line):
                    glasses_lines.append(line)

    combined = phone_lines + glasses_lines
    combined.sort()

    with open(filtered_output, 'w', encoding='utf-8') as f:
        f.write(f"--- BUILD ID: {meta.get('build_id', '')} ---\n")
        f.write(f"--- PARTICIPANT ID: {meta.get('participant_id', '')} ---\n")
        f.write(f"--- CSV PATH: {meta.get('csv_path', '')} ---\n")
        f.write(f"--- WEARABLE IP: {meta.get('glasses_ip', '')} ---\n")
        if meta.get('extra_metadata'):
            f.write(f"--- METADATA: {meta.get('extra_metadata')} ---\n")
        f.write(f"--- START NOTES: {meta.get('start_notes', '')} ---\n")
        f.write("-----------------------------------------\n")
        for line in combined:
            f.write(line if line.endswith('\n') else line + '\n')
        f.write("-----------------------------------------\n")
        f.write(f"--- END NOTES: {meta.get('end_notes', '')} ---\n")

# --- Live Capture Session Runner ---
def run_capture_session(participant_id, build_id, csv_path, extra_metadata="", app_package="com.example.gesturetracker"):
    log_header("TOUCHPAD CAPTURE SESSION")
    print(f"Participant ID : {Color.CYAN}{participant_id}{Color.RESET}")
    print(f"Build ID       : {Color.CYAN}{build_id}{Color.RESET}")
    print(f"CSV Protocol   : {Color.CYAN}{csv_path}{Color.RESET}")
    if extra_metadata:
        print(f"Extra Metadata : {Color.CYAN}{extra_metadata}{Color.RESET}")

    if not os.path.isfile(csv_path):
        log_error(f"Gesture protocol CSV file not found: {csv_path}")
        sys.exit(1)

    start_notes = input(f"\n{Color.BOLD}📝 Enter starting notes (optional, press Enter to skip): {Color.RESET}").strip()

    # Detect devices
    phone_serial, glasses_serial, glasses_ip = detect_devices()
    
    if not glasses_ip:
        if glasses_serial and not glasses_serial.endswith(":5555"):
            log_warning("Wearable connected via USB. Attempting Wi-Fi pairing automatically...")
            glasses_ip = connect_glasses_to_ap(usb_glasses_serial=glasses_serial)
        else:
            glasses_ip = input(f"\n🕶️  Enter Wearable IP address (e.g. 192.168.1.100:5555): ").strip()
            run_adb(["connect", glasses_ip])

    if not glasses_ip:
        log_error("Failed to acquire Wearable Wi-Fi connection. Exiting.")
        sys.exit(1)

    ensure_glasses_keepalive(glasses_ip)

    # Reset Companion App State & Push CSV
    log_info("Resetting app state and pushing gesture protocol to companion device...")
    run_adb(["shell", "am", "force-stop", app_package])
    run_adb(["shell", "rm", "/data/local/tmp/gestures.csv"])
    
    ret, _, err = run_adb(["push", csv_path, "/data/local/tmp/gestures.csv"])
    if ret != 0:
        log_error(f"Failed to push CSV to device: {err}")
        sys.exit(1)
    log_success("Gesture protocol pushed to '/data/local/tmp/gestures.csv'.")

    # File definitions
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = f"{participant_id}_{build_id}_{timestamp}"
    
    raw_phone_log = f"{prefix}_raw.txt"
    raw_glasses_log = f"{prefix}_wearable_raw.txt"
    linux_log_file = f"{prefix}_linux_events.txt"
    filtered_log_file = f"{prefix}_filtered.txt"
    synced_csv_file = f"{prefix}_synced_data.csv"
    bugreport_file = f"{prefix}_bugreport.zip"

    # Start background capture processes
    log_info("Starting ADB logcat captures & Linux evdev getevent streams...")
    run_adb(["logcat", "-c"])
    run_adb(["logcat", "-c"], serial=glasses_ip)

    f_phone = open(raw_phone_log, "w", encoding="utf-8")
    f_glasses = open(raw_glasses_log, "w", encoding="utf-8")
    f_linux = open(linux_log_file, "w", encoding="utf-8")

    p_phone = subprocess.Popen(["adb", "-d", "logcat", "-v", "threadtime"], stdout=f_phone, stderr=subprocess.DEVNULL)
    p_glasses = subprocess.Popen(["adb", "-s", glasses_ip, "logcat", "-v", "threadtime"], stdout=f_glasses, stderr=subprocess.DEVNULL)
    p_linux = subprocess.Popen(["adb", "-s", glasses_ip, "shell", "getevent", "-lt"], stdout=f_linux, stderr=subprocess.DEVNULL)

    session_active = True
    gesture_counter = [0]
    prompt_counter = [0]

    # Live Logcat Tail & Parser Thread
    def logcat_monitor():
        time.sleep(1)
        with open(raw_phone_log, 'r', encoding='utf-8', errors='ignore') as pf, \
             open(raw_glasses_log, 'r', encoding='utf-8', errors='ignore') as gf:
            
            while session_active:
                pline = pf.readline()
                gline = gf.readline()
                
                line_to_check = pline or gline
                if not line_to_check:
                    time.sleep(0.05)
                    continue

                # 1. Prompt Display
                if "User prompted to perform" in pline:
                    prompt_counter[0] += 1
                    match = re.search(r'User prompted to perform\s*:\s*(.*)', pline)
                    prompt_text = match.group(1).strip() if match else pline.strip()
                    print(f"\n{Color.BOLD}{Color.PINK}===================================================={Color.RESET}")
                    print(f"➡️  {Color.BOLD}PROMPT #{prompt_counter[0]}:{Color.RESET} Please perform: {Color.CYAN}{prompt_text}{Color.RESET}")
                    print(f"{Color.BOLD}{Color.PINK}===================================================={Color.RESET}\n")

                # 2. Gesture Detection & Auto Advance
                elif "Gesture Detected, checking input map: gesture =" in pline:
                    gesture_counter[0] += 1
                    print(f"{Color.GREEN}✅ GESTURE #{gesture_counter[0]} CAPTURED -> Auto-advancing prompt...{Color.RESET}")
                    run_adb(["shell", "am", "broadcast", "-a", f"{app_package}.ADVANCE_PROMPT"])

                elif re.search(r'gesture=TWO_FINGER|gesture=two_finger', gline, re.I) and not re.search(r'HOLD', gline, re.I):
                    gesture_counter[0] += 1
                    print(f"{Color.GREEN}✅ 2-FINGER GESTURE #{gesture_counter[0]} CAPTURED -> Auto-advancing prompt...{Color.RESET}")
                    run_adb(["shell", "am", "broadcast", "-a", f"{app_package}.ADVANCE_PROMPT"])

                elif "All gestures completed" in pline:
                    print(f"\n{Color.BOLD}{Color.GREEN}🎉 === All gestures completed! === 🎉{Color.RESET}")
                    print(f"{Color.YELLOW}Press [ENTER] to conclude the session and process logs.{Color.RESET}\n")

    monitor_thread = threading.Thread(target=logcat_monitor, daemon=True)
    monitor_thread.start()

    # Connection Watchdog Thread
    def connection_watchdog():
        while session_active:
            time.sleep(2)
            if p_linux.poll() is not None:
                sys.stderr.write("\a")
                print(f"\n{Color.RED}{Color.BOLD}🚨 CRITICAL ALERT: Wearable Wi-Fi ADB connection dropped! 🚨{Color.RESET}")
                print(f"{Color.YELLOW}Attempting automatic reconnection to {glasses_ip}...{Color.RESET}")
                run_adb(["connect", glasses_ip])
                break

    watchdog_thread = threading.Thread(target=connection_watchdog, daemon=True)
    watchdog_thread.start()

    # Interactive In-Terminal Controls
    print(f"\n{Color.GREEN}🚀 Gesture capture is now LIVE and recording!{Color.RESET}")
    print(f"{Color.BOLD}💡 In-Terminal Controls:{Color.RESET}")
    print(f"   • Press {Color.CYAN}[SPACE] or [a] + [ENTER]{Color.RESET} at any time to {Color.BOLD}MANUALLY ADVANCE PROMPT{Color.RESET}")
    print(f"   • Press {Color.YELLOW}[ENTER] (empty) or type 'done'{Color.RESET} to {Color.BOLD}FINISH & SAVE{Color.RESET}\n")

    while session_active:
        try:
            user_input = input().strip().lower()
            if user_input in ["", "done", "q", "quit"]:
                break
            elif user_input in [" ", "a", "advance", "next"]:
                log_info("Manual prompt advance triggered...")
                run_adb(["shell", "am", "broadcast", "-a", f"{app_package}.ADVANCE_PROMPT"])
            else:
                log_info("Manual prompt advance triggered...")
                run_adb(["shell", "am", "broadcast", "-a", f"{app_package}.ADVANCE_PROMPT"])
        except (KeyboardInterrupt, EOFError):
            break

    session_active = False
    log_info("Stopping background capture processes...")

    for p in [p_phone, p_glasses, p_linux]:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            p.kill()

    for f in [f_phone, f_glasses, f_linux]:
        f.close()

    # Close companion app
    run_adb(["shell", "am", "force-stop", app_package])

    end_notes = input(f"\n{Color.BOLD}📝 Enter ending notes (optional, press Enter to skip): {Color.RESET}").strip()

    # Post-Processing: Filtering
    log_header("POST-PROCESSING & LOG ALIGNMENT")
    meta = {
        'participant_id': participant_id,
        'build_id': build_id,
        'csv_path': csv_path,
        'glasses_ip': glasses_ip,
        'extra_metadata': extra_metadata,
        'start_notes': start_notes,
        'end_notes': end_notes
    }
    log_info("Filtering and chronological sorting of logs...")
    filter_and_format_logs(raw_phone_log, raw_glasses_log, filtered_log_file, meta)

    # Post-Processing: Sync Logs
    log_info("Running spatial & temporal log alignment...")
    synced_count = parse_and_sync_logs(filtered_log_file, linux_log_file, synced_csv_file)

    # Sanity Check
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            expected_lines = sum(1 for _ in f if _.strip()) - 1
        if synced_count < expected_lines:
            log_warning(f"Sanity Check Warning: Expected at least {expected_lines} gestures from CSV, synced {synced_count}.")
        else:
            log_success(f"Sanity Check Passed: All {expected_lines} gestures synced perfectly!")

    # Optional Bug Report Capture
    bugreport_captured = False
    capture_br = input(f"\n{Color.BOLD}Do you want to capture a full system bugreport? (y/N): {Color.RESET}").strip().lower()
    if capture_br in ['y', 'yes']:
        log_info(f"Capturing bug report into '{bugreport_file}' (this may take 1-2 minutes)...")
        ret, _, _ = run_adb(["bugreport", bugreport_file])
        if ret == 0 and os.path.exists(bugreport_file):
            log_success("Bug report captured successfully.")
            bugreport_captured = True
        else:
            log_warning("Bug report capture failed or timed out.")

    # Session Output Folder Organization
    session_dir = f"{participant_id}_{build_id}_{timestamp}"
    os.makedirs(session_dir, exist_ok=True)
    log_info(f"Bundling all session files into '{session_dir}/'...")

    files_to_move = [
        raw_phone_log, raw_glasses_log, linux_log_file,
        filtered_log_file, synced_csv_file
    ]
    if bugreport_captured and os.path.exists(bugreport_file):
        files_to_move.append(bugreport_file)

    for f_item in files_to_move:
        if os.path.exists(f_item):
            dest = os.path.join(session_dir, f_item)
            os.replace(f_item, dest)

    if os.path.exists(csv_path):
        csv_dest = os.path.join(session_dir, os.path.basename(csv_path))
        try:
            import shutil
            shutil.copyfile(csv_path, csv_dest)
        except Exception:
            pass

    log_header("SESSION COMPLETED SUCCESSFULLY")
    print(f"{Color.GREEN}{Color.BOLD}All files packaged in:{Color.RESET} {Color.CYAN}{os.path.abspath(session_dir)}{Color.RESET}")
    print(f"\nFiles inside session bundle:")
    for root, _, files in os.walk(session_dir):
        for f in files:
            print(f"  📦 {f}")
    print(f"\n{Color.BOLD}➡️  Ready for analysis in XR Touchpad Analytics Studio!{Color.RESET}\n")

# --- Main Entry Point & Argument Parsing ---
def main():
    parser = argparse.ArgumentParser(
        description="XR Touchpad Reliability Test Automation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run station setup wizard (Wi-Fi pairing & input overrides)
  python3 xr_touchpad.py --setup --ssid MyTestAP --password MySecretPassword

  # Run interactive gesture capture session
  python3 xr_touchpad.py --participant Tester-01 --build v2.4.0 --csv sample_gestures.csv
        """
    )
    parser.add_argument("--participant", default=os.environ.get("PARTICIPANT_ID"), help="Participant ID (e.g. Tester-01)")
    parser.add_argument("--build", default=os.environ.get("BUILD_ID"), help="Firmware / Algorithm Build ID (e.g. v2.4.0)")
    parser.add_argument("--csv", default=os.environ.get("TOUCHPAD_CSV_PATH"), help="Path to gesture protocol CSV")
    parser.add_argument("--metadata", default=os.environ.get("EXTRA_METADATA", ""), help="Extra metadata string")
    parser.add_argument("--ssid", help="Wi-Fi SSID for wearable station pairing")
    parser.add_argument("--password", help="Wi-Fi Password for wearable station pairing")
    parser.add_argument("--package", default="com.example.gesturetracker", help="Companion App Package name")
    parser.add_argument("--setup", "-s", action="store_true", help="Run full station setup wizard")
    args = parser.parse_args()

    if args.setup:
        full_station_setup(ssid=args.ssid, password=args.password)
        return

    participant_id = args.participant
    build_id = args.build
    csv_path = args.csv
    extra_metadata = args.metadata
    app_package = args.package

    # Interactive fallback if arguments are missing
    if not participant_id or not build_id or not csv_path:
        print(f"{Color.YELLOW}Interactive Session Setup:{Color.RESET}")
        if not participant_id:
            participant_id = input("Enter Participant ID (e.g., Tester-01): ").strip()
        if not build_id:
            build_id = input("Enter Build ID (e.g., v2.4.0): ").strip()
        if not csv_path:
            csv_files = glob.glob("*.csv")
            if csv_files:
                print("\nAvailable CSV protocols in current directory:")
                for idx, c_name in enumerate(csv_files, 1):
                    print(f"  [{idx}] {c_name}")
                sel = input(f"Select CSV [1-{len(csv_files)}] or type filename: ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(csv_files):
                    csv_path = csv_files[int(sel)-1]
                else:
                    csv_path = sel
            else:
                csv_path = input("Enter CSV path: ").strip()

    run_capture_session(participant_id, build_id, csv_path, extra_metadata, app_package=app_package)

if __name__ == "__main__":
    main()
