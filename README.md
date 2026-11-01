# ⚡ GPU VRAM Task Manager & Hardware Monitor

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%20Windows%2011-0078D6?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built with CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-blue)](https://github.com/TomSchimansky/CustomTkinter)

A dedicated, high-performance Windows desktop application designed to monitor **GPU VRAM allocation per process**, track **CPU Package Power (RAPL)**, switch **Windows DirectX GPU Preferences**, and cleanly terminate or flush VRAM-hogging background applications in one click.

Built by **Hiki**.

---

## 🌟 Key Features

### 1. 📊 Real-Time Per-Process GPU VRAM Tracking
- Queries the Windows **D3D/WDDM Performance Data Helper (PDH)** engine for exact VRAM metrics:
  - **Process Name & PID**
  - **Active Render GPU** (e.g., Discrete NVIDIA RTX vs Integrated AMD/Intel)
  - **Dedicated VRAM** (Allocated video memory on the GPU)
  - **Shared GPU Memory** (System RAM mapped for GPU textures)
  - **Total GPU Footprint**
  - **System RAM Usage**
  - **Current Windows GPU Preference** (Auto / Power Saving / High Performance)
  - **Executable Path**
- **In-place differential table updates**: No screen flickering; updates only rows that change.
- **Adjustable Refresh Rates**: `0.5s (Real-Time)`, `1s (Live)`, `2s (Normal)`, or `Paused`.
- **Search & Filters**: Real-time filtering by process name, PID, executable path, or GPU adapter.
- **System Process Shield**: Toggle to hide protected Windows services (`dwm.exe`, `csrss.exe`, `explorer.exe`).

### 2. 🎮 Universal Multi-GPU & Single-GPU Support
- **Auto-Hardware Discovery**: Automatically detects your exact adapters via DXGI:
  - **Dual-GPU Laptops**: Dedicated GPU (NVIDIA RTX/GTX or AMD RX) + Integrated GPU (AMD Radeon / Intel Iris Xe / UHD).
  - **Single-GPU Desktop PCs**: Seamlessly displays single-GPU configurations without errors.
- **NVIDIA NVML Telemetry**: Live GPU core utilization (%), temperature (°C), and real-time board power draw (Watts).
- **CPU Package Power (RAPL)**: Real-time CPU package wattage via Windows Energy Meter counters, CPU load percentage, core count, and system memory.

### 3. 🎯 Windows DirectX GPU Preference Router
- Inspect and change which GPU an application uses directly from the UI:
  - **🟢 Power Saving**: Routes app to the Integrated GPU (AMD / Intel).
  - **⚡ High Performance**: Routes app to the Discrete GPU (NVIDIA RTX / AMD RX).
  - **⚪ Let Windows Decide**: Resets to automatic Windows GPU scheduling.
- Writes directly to Windows Registry (`HKCU\Software\Microsoft\DirectX\UserGpuPreferences`).
- **No forced restart required**: Changes are safely applied in Windows; restart the application at your convenience.

### 4. 🧹 One-Click VRAM Cleaner Modal
- Click **🧹 Clean GPU VRAM** to scan background processes holding textures and framebuffers.
- Analyzes non-system background tasks (e.g. Discord, Spotify, browser helpers, background game launchers).
- Live tally of recoverable VRAM (e.g., *"Selected to reclaim: 650 MB VRAM"*).
- Click **🚀 Clean & Free VRAM Now** to terminate unnecessary hogs in bulk.

### 5. 🔄 Process Management
- **❌ End Task**: Clean graceful termination.
- **⚡ Force Kill**: Immediate forceful termination for hung or unresponsive games.
- **🔄 Restart App**: Terminate and immediately relaunch an application with its original arguments.
- **🧹 Flush Working Set**: Trim memory caches via Windows API.
- **📁 Open Location**: Reveals the executable in Windows File Explorer.

---

## 📁 Repository Structure

```text
├── app_icon.ico              # Application branding icon
├── cleaner_dialog.py         # Dedicated VRAM Cleaner popup modal
├── gpu_backend.py            # DXGI, NVML, Windows PDH counters, and Registry backend
├── GPU_VRAM_Manager.spec     # PyInstaller standalone build specification
├── LICENSE                   # MIT License
├── main.py                   # High-DPI bootstrap entry point
├── main_gui.py               # CustomTkinter Dark UI, live Treeview table, and overview cards
├── README.md                 # Project documentation
├── requirements.txt          # Python dependencies
├── build.bat                 # One-click standalone executable builder
└── run.bat                   # One-click runner from source
```

---

## 🚀 Getting Started

### Prerequisites
- **Windows 10** (build 19041+) or **Windows 11** (64-bit)
- **Python 3.10+** (if running from source)

### Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/<your-username>/gpu-vram-task-manager.git
   cd gpu-vram-task-manager
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python main.py
   ```
   *(Or double-click `run.bat`)*

---

## 📦 Building Standalone Executable (.exe)

To compile a single, standalone `.exe` that runs on any other Windows 10/11 PC without Python:

1. Run the build script:
   ```cmd
   build.bat
   ```
   *(Or run manually)*:
   ```cmd
   pyinstaller --noconfirm GPU_VRAM_Manager.spec
   ```

2. The standalone binary will be generated at:
   ```text
   dist\GPU_VRAM_Manager.exe
   ```

---

## 🔒 Security & System Safety
- Critical Windows system components (`system`, `csrss.exe`, `dwm.exe`, `explorer.exe`, etc.) are marked with a `🛡 Protected` badge and prompt for confirmation before termination.
- Only writes to documented Windows user preferences (`HKCU\Software\Microsoft\DirectX\UserGpuPreferences`).

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
