# XR Touchpad Reliability Test Automation Suite

An automated end-to-end Hardware & Firmware QA testing suite for **Smart Glasses, Head-Mounted Displays (HMDs), and XR Wearables** equipped with capacitive temple touchpads.

This tool coordinates test protocols between companion devices (smartphones/tablets) and wearable devices over USB and Wi-Fi ADB. It captures dual-layer telemetry (Android framework `MotionEvents` + Linux kernel `evdev` raw events), correlates interactions in real time, and produces synchronized diagnostic datasets.

---

## 🌟 Architecture & Key Features

```
               ┌───────────────────────────────┐
               │    XR Test Automation CLI     │
               │       (xr_touchpad.py)        │
               └──────┬─────────────────┬──────┘
                      │                 │
             USB ADB  │                 │  Wi-Fi TCP/IP
                      ▼                 ▼
          ┌───────────────────────┐ ┌───────────────────────┐
          │    Companion Phone    │ │    Wearable Device    │
          │   (Gesture Prompter)  │ │   (Capacitive TP)     │
          └───────────┬───────────┘ └───────────┬───────────┘
                      │                         │
                      ▼                         ▼
             Android Framework           Linux Kernel evdev
                MotionEvent                  /dev/input
                      │                         │
                      └────────────┬────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │  Spatial & Temporal Alignment │
                   │  - Microsecond synchronization│
                   │  - Coordinate scaling         │
                   │  - Pointer count tracking     │
                   └───────────────┬───────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │   Clean Synced Dataset (CSV)  │
                   │  + Raw Traces + Bug Reports   │
                   └───────────────────────────────┘
```

- **Automated Device Discovery:**
  - Auto-detects attached devices via ADB and classifies them as Companion Phone vs. Wearable Device.
- **Wi-Fi TCP/IP Pairing Wizard:**
  - Automatically provisions device Wi-Fi, resolves IPv4/IPv6 link-local addresses, and activates ADB port `5555`.
- **Keepalive & Power Spoofing:**
  - Bypasses system idle states and battery save modes to prevent Wi-Fi dropouts during prolonged test runs.
- **Dual-Layer Telemetry Capture:**
  - Captures high-level Android `MotionEvent` streams simultaneously with low-level Linux kernel `/dev/input` raw touch packets.
- **Real-Time Interactive Prompter & Watchdog:**
  - Live logcat monitoring auto-advances prompts via Android broadcast intents upon detected gestures.
  - Manual override support (`[SPACE]` / `[ENTER]`) directly from the terminal.
  - Background connection watchdog thread with automatic reconnect logic.
- **Spatial & Temporal Event Synchronization:**
  - Aligns touch begin/end timestamps, duration delta, normalized coordinate scaling, and multitouch pointer counts into a unified CSV.
- **Session Packaging:**
  - Organizes test runs into timestamped directories ready for visualization in the **[XR Touchpad Analytics Studio](https://github.com/Hekim98/touchpad-analytics-studio)**.

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.8+** (Uses standard library; no external pip packages required)
- **Android SDK Platform Tools (`adb`)** added to system `PATH`
- Target Android wearable device and companion phone with USB Debugging enabled

### Installation

```bash
git clone https://github.com/Hekim98/xr-touchpad-test-automation.git
cd xr-touchpad-test-automation
chmod +x xr_touchpad.py capture_gesture_data.sh
```

---

## 📖 Usage Guide

### 1. Test Station Setup (Wi-Fi Pairing & Input Overrides)

Run the setup wizard to connect the wearable device to the test station's Wi-Fi network and apply input overrides:

```bash
python3 xr_touchpad.py --setup --ssid "TestNetwork_5G" --password "TestPass123"
```

### 2. Interactive Test Capture Session

Start an interactive testing session with automatic device detection and prompt selection:

```bash
./capture_gesture_data.sh
```

Or run directly with Python:

```bash
python3 xr_touchpad.py --participant Tester-01 --build v2.4.0 --csv sample_gestures.csv
```

### 3. CLI Options Reference

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--setup`, `-s` | Run station setup wizard (Wi-Fi pairing + keepalive) | `False` |
| `--participant` | Participant or Test Operator ID | Interactive prompt |
| `--build` | Firmware / Algorithm build identifier | Interactive prompt |
| `--csv` | Path to test protocol CSV sequence | Interactive prompt |
| `--ssid` | Wi-Fi SSID for station pairing | `None` / Env var |
| `--password` | Wi-Fi Password for station pairing | `None` / Env var |
| `--package` | Companion app package name | `com.example.gesturetracker` |
| `--metadata` | Optional metadata tags for reporting | `""` |

---

## 📁 Output Artifacts

Upon completing a capture session, a timestamped bundle directory is generated:

```text
Tester-01_v2.4.0_20260902-154500/
├── sample_gestures.csv        # Reference ground truth protocol
├── Tester-01_v2.4.0_raw.txt   # Raw companion phone logcat
├── Tester-01_v2.4.0_wearable_raw.txt # Raw wearable device logcat
├── Tester-01_v2.4.0_linux_events.txt # Raw Linux getevent stream (/dev/input)
├── Tester-01_v2.4.0_filtered.txt     # Chronologically sorted & filtered events
├── Tester-01_v2.4.0_synced_data.csv  # Synchronized touch metrics dataset
└── Tester-01_v2.4.0_bugreport.zip    # Optional full system bugreport dump
```

The resulting `synced_data.csv` can be directly dragged and dropped into the **XR Touchpad Analytics Studio** for instant KPI calculation, confusion matrix generation, and head-pose correlation analysis.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
