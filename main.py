"""
Entry point for GPU VRAM Task Manager & Cleaner.
Enables Windows Per-Monitor DPI awareness and launches the application.
"""

import sys
import os
import ctypes

def enable_high_dpi():
    """Enable crisp text rendering on Windows High-DPI laptop displays."""
    try:
        # Per monitor DPI aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def main():
    enable_high_dpi()
    from gpu_backend import GPUBackend
    from main_gui import GPUVRAMManagerApp

    backend = GPUBackend()
    app = GPUVRAMManagerApp(backend)
    app.mainloop()

if __name__ == "__main__":
    main()
