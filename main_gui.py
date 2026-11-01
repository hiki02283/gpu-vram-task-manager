"""
Main GUI for GPU VRAM Task Manager & Cleaner.
Features live real-time updating, CPU power & telemetry, and Windows DirectX GPU Preference management.
"""

import os
import sys
import subprocess
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

from cleaner_dialog import VRAMCleanerDialog

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")



class GPUVRAMManagerApp(ctk.CTk):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend

        self.title("GPU VRAM Task Manager & Hardware Monitor_Hiki")
        self.geometry("1240x780")
        self.minsize(1050, 620)

        # Support both normal run and PyInstaller --onefile
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(__file__)

        icon_path = os.path.join(base_dir, "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # State
        self.is_running = True
        self.refresh_interval = 1.0
        self.selected_gpu_tab = "All GPUs"
        self.hide_system_procs = True
        self.search_filter = ""
        self.sort_column = "dedicated_mb"
        self.sort_descending = True

        self.last_procs_data = []
        self.last_gpu_data = {}
        self.last_cpu_data = {}
        self.is_fetching = False

        # Dynamically discover and classify physical adapters
        valid_adapters = [a for a in self.backend.adapters.values() if not a.get("is_software", False)]
        valid_adapters.sort(key=lambda a: (a.get("vendor") == "NVIDIA", a.get("dedicated_mb", 0)), reverse=True)
        self.gpu1 = valid_adapters[0] if len(valid_adapters) > 0 else None
        self.gpu2 = valid_adapters[1] if len(valid_adapters) > 1 else None

        self.gpu1_short = self._get_short_name(self.gpu1["name"]) if self.gpu1 else "Primary GPU"
        self.gpu2_short = self._get_short_name(self.gpu2["name"]) if self.gpu2 else ""

        if self.gpu2:
            self.tab_values = ["All GPUs", self.gpu1_short, self.gpu2_short]
            self.pref_options = [
                f"{self.gpu2_short} (Power Save)",
                f"{self.gpu1_short} (High Perf)",
                "Windows Auto (Default)"
            ]
        elif self.gpu1:
            self.tab_values = ["All GPUs", self.gpu1_short]
            self.pref_options = [
                f"{self.gpu1_short} (High Perf)",
                "Windows Auto (Default)"
            ]
        else:
            self.tab_values = ["All GPUs"]
            self.pref_options = ["Windows Auto (Default)"]

        self._init_theme_styles()
        self._build_ui()

        self.poll_thread = threading.Thread(target=self._background_poll_loop, daemon=True)
        self.poll_thread.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _get_short_name(name):
        clean = name.replace("(R)", "").replace("(TM)", "").replace("Graphics", "").replace("Laptop GPU", "")
        clean = " ".join(clean.split())
        clean = clean.replace("NVIDIA GeForce", "GeForce")
        if len(clean) > 26:
            clean = clean[:25].strip() + ".."
        return clean

    def _get_pref_display(self, pref_code):
        if pref_code == 1:
            name = self.gpu2_short if self.gpu2 else "Power Save"
            return (f"🟢 {name} (Power)", "#a6e3a1")
        elif pref_code == 2:
            name = self.gpu1_short if self.gpu1 else "High Perf"
            return (f"⚡ {name} (Perf)", "#fab387")
        else:
            return ("⚪ Auto (Default)", "#a6adc8")

    def _init_theme_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(
            "VRAM.Treeview",
            background="#181825",
            foreground="#cdd6f4",
            fieldbackground="#181825",
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 10)
        )
        self.style.configure(
            "VRAM.Treeview.Heading",
            background="#1e1e2e",
            foreground="#cdd6f4",
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 10, "bold")
        )
        self.style.map(
            "VRAM.Treeview.Heading",
            background=[("active", "#313244"), ("pressed", "#45475a")],
            foreground=[("active", "#ffffff")]
        )
        self.style.map(
            "VRAM.Treeview",
            background=[("selected", "#313244")],
            foreground=[("selected", "#89b4fa")]
        )

    def _build_ui(self):
        # 1. Header Bar
        header = ctk.CTkFrame(self, fg_color="#11111b", height=60, corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=10)

        main_title = ctk.CTkLabel(
            title_box,
            text="⚡ GPU VRAM Task Manager & Hardware Monitor_Hiki",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#cdd6f4"
        )
        main_title.pack(anchor="w")

        sub_title = ctk.CTkLabel(
            title_box,
            text="Real-time VRAM telemetry, CPU Package Power, and Windows GPU Preference Router",
            font=ctk.CTkFont(size=11),
            text_color="#a6adc8"
        )
        sub_title.pack(anchor="w")

        actions_box = ctk.CTkFrame(header, fg_color="transparent")
        actions_box.pack(side="right", padx=20, pady=10)

        self.live_badge = ctk.CTkLabel(
            actions_box,
            text="● LIVE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a6e3a1"
        )
        self.live_badge.pack(side="left", padx=(0, 10))

        self.refresh_lbl = ctk.CTkLabel(actions_box, text="Rate:", font=ctk.CTkFont(size=11))
        self.refresh_lbl.pack(side="left", padx=(0, 5))

        self.interval_combo = ctk.CTkComboBox(
            actions_box,
            values=["0.5s (Real-Time)", "1s (Live)", "2s (Normal)", "Paused"],
            width=135,
            height=28,
            command=self._on_interval_change
        )
        self.interval_combo.set("1s (Live)")
        self.interval_combo.pack(side="left", padx=(0, 10))

        self.refresh_btn = ctk.CTkButton(
            actions_box,
            text="🔄 Refresh",
            width=85,
            height=28,
            fg_color="#313244",
            hover_color="#45475a",
            command=self._trigger_immediate_refresh
        )
        self.refresh_btn.pack(side="left", padx=(0, 10))

        self.clean_vram_btn = ctk.CTkButton(
            actions_box,
            text="🧹 Clean GPU VRAM",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=140,
            height=32,
            fg_color="#a6e3a1",
            hover_color="#94e2d5",
            text_color="#11111b",
            command=self._open_vram_cleaner
        )
        self.clean_vram_btn.pack(side="left")

        # 2. Hardware Overview Cards (3 Cards Side-by-Side: RTX 5050, AMD 780M, AMD Ryzen CPU)
        cards_container = ctk.CTkFrame(self, fg_color="transparent")
        cards_container.pack(fill="x", padx=15, pady=(10, 5))

        # Card 1: NVIDIA RTX 5050
        self.rtx_card = ctk.CTkFrame(cards_container, fg_color="#181825", corner_radius=10, border_width=1, border_color="#313244")
        self.rtx_card.pack(side="left", fill="both", expand=True, padx=4)
        self._build_rtx_card_ui(self.rtx_card)

        # Card 2: AMD Radeon 780M
        self.amd_card = ctk.CTkFrame(cards_container, fg_color="#181825", corner_radius=10, border_width=1, border_color="#313244")
        self.amd_card.pack(side="left", fill="both", expand=True, padx=4)
        self._build_amd_card_ui(self.amd_card)

        # Card 3: AMD Ryzen CPU & System
        self.cpu_card = ctk.CTkFrame(cards_container, fg_color="#181825", corner_radius=10, border_width=1, border_color="#313244")
        self.cpu_card.pack(side="left", fill="both", expand=True, padx=4)
        self._build_cpu_card_ui(self.cpu_card)

        # 3. Filter & Search Controls Bar
        filter_bar = ctk.CTkFrame(self, fg_color="transparent")
        filter_bar.pack(fill="x", padx=20, pady=(10, 5))

        self.gpu_tabs = ctk.CTkSegmentedButton(
            filter_bar,
            values=self.tab_values,
            command=self._on_gpu_tab_change
        )
        self.gpu_tabs.set("All GPUs")
        self.gpu_tabs.pack(side="left", padx=(0, 15))

        self.search_entry = ctk.CTkEntry(
            filter_bar,
            placeholder_text="🔍 Filter processes (e.g. game, discord, pid)...",
            width=280,
            height=30
        )
        self.search_entry.pack(side="left", padx=(0, 15))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.sys_switch_var = tk.BooleanVar(value=True)
        self.sys_switch = ctk.CTkSwitch(
            filter_bar,
            text="Hide Windows System Processes",
            variable=self.sys_switch_var,
            command=self._on_sys_switch_toggle,
            font=ctk.CTkFont(size=12)
        )
        self.sys_switch.pack(side="left", padx=(0, 15))

        self.status_count_lbl = ctk.CTkLabel(
            filter_bar,
            text="Connecting live telemetry...",
            font=ctk.CTkFont(size=12),
            text_color="#a6adc8"
        )
        self.status_count_lbl.pack(side="right")

        # 4. Process Table (Treeview)
        table_frame = ctk.CTkFrame(self, fg_color="#181825", corner_radius=8)
        table_frame.pack(fill="both", expand=True, padx=20, pady=5)

        columns = ("name", "pid", "gpu", "pref", "dedicated", "shared", "total", "ram", "type", "path")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="VRAM.Treeview",
            selectmode="extended"
        )

        col_defs = [
            ("name", "Process Name", 180, "w"),
            ("pid", "PID", 70, "center"),
            ("gpu", "Active GPU", 100, "center"),
            ("pref", "GPU Preference", 160, "center"),
            ("dedicated", "Dedicated VRAM ▼", 130, "e"),
            ("shared", "Shared Memory", 110, "e"),
            ("total", "Total GPU", 110, "e"),
            ("ram", "System RAM", 95, "e"),
            ("type", "Type", 95, "center"),
            ("path", "Executable Path", 260, "w")
        ]

        for col_id, heading, width, align in col_defs:
            self.tree.heading(col_id, text=heading, command=lambda c=col_id: self._on_heading_click(c))
            self.tree.column(col_id, width=width, minwidth=60, anchor=align)

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # 5. Context Menu
        self._build_context_menu()

        # 6. Bottom Action Bar with GPU Preference Switcher
        bottom_bar = ctk.CTkFrame(self, fg_color="#11111b", height=54, corner_radius=0)
        bottom_bar.pack(fill="x", padx=0, pady=0)

        self.selected_info_lbl = ctk.CTkLabel(
            bottom_bar,
            text="No process selected. Click a process in the table to manage.",
            font=ctk.CTkFont(size=12),
            text_color="#cdd6f4"
        )
        self.selected_info_lbl.pack(side="left", padx=20, pady=12)

        btn_box = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        btn_box.pack(side="right", padx=20, pady=8)

        # GPU Preference Selector dropdown
        self.pref_lbl = ctk.CTkLabel(btn_box, text="Set Preference:", font=ctk.CTkFont(size=11))
        self.pref_lbl.pack(side="left", padx=(0, 4))

        self.pref_combo = ctk.CTkComboBox(
            btn_box,
            values=self.pref_options,
            width=185,
            height=30,
            state="disabled"
        )
        self.pref_combo.set(self.pref_options[0])
        self.pref_combo.pack(side="left", padx=(0, 6))

        self.apply_pref_btn = ctk.CTkButton(
            btn_box,
            text="Apply Preference",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=120,
            height=30,
            fg_color="#89b4fa",
            hover_color="#b4befe",
            text_color="#11111b",
            state="disabled",
            command=self._apply_gpu_preference
        )
        self.apply_pref_btn.pack(side="left", padx=(0, 10))

        # Standard Process Actions
        self.restart_btn = ctk.CTkButton(
            btn_box,
            text="🔄 Restart",
            width=85,
            height=30,
            fg_color="#313244",
            hover_color="#45475a",
            state="disabled",
            command=self._restart_selected
        )
        self.restart_btn.pack(side="left", padx=(0, 6))

        self.trim_btn = ctk.CTkButton(
            btn_box,
            text="🧹 Flush",
            width=75,
            height=30,
            fg_color="#313244",
            hover_color="#45475a",
            state="disabled",
            command=self._trim_selected
        )
        self.trim_btn.pack(side="left", padx=(0, 6))

        self.open_loc_btn = ctk.CTkButton(
            btn_box,
            text="📁 Location",
            width=85,
            height=30,
            fg_color="#313244",
            hover_color="#45475a",
            state="disabled",
            command=self._open_selected_location
        )
        self.open_loc_btn.pack(side="left", padx=(0, 6))

        self.force_kill_btn = ctk.CTkButton(
            btn_box,
            text="⚡ Force",
            width=75,
            height=30,
            fg_color="#45475a",
            hover_color="#585b70",
            state="disabled",
            command=lambda: self._kill_selected(force=True)
        )
        self.force_kill_btn.pack(side="left", padx=(0, 6))

        self.end_task_btn = ctk.CTkButton(
            btn_box,
            text="❌ End Task",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=90,
            height=30,
            fg_color="#f38ba8",
            hover_color="#eba0ac",
            text_color="#11111b",
            state="disabled",
            command=lambda: self._kill_selected(force=False)
        )
        self.end_task_btn.pack(side="left")

    def _build_rtx_card_ui(self, parent):
        top_row = ctk.CTkFrame(parent, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 2))

        title_text = self.gpu1_short if self.gpu1 else "Primary GPU"
        badge_text = f"Discrete • {round(self.gpu1['dedicated_mb']/1024, 1)}GB" if self.gpu1 else "Primary"
        title_color = "#a6e3a1" if (self.gpu1 and self.gpu1.get("vendor") == "NVIDIA") else "#fab387"

        title = ctk.CTkLabel(
            top_row,
            text=title_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=title_color
        )
        title.pack(side="left")

        self.rtx_badge = ctk.CTkLabel(
            top_row,
            text=badge_text,
            font=ctk.CTkFont(size=10),
            text_color="#a6adc8"
        )
        self.rtx_badge.pack(side="right")

        total_vram = f"{self.gpu1['dedicated_mb']:,.0f} MB" if self.gpu1 else "-- MB"
        self.rtx_vram_lbl = ctk.CTkLabel(
            parent,
            text=f"VRAM: 0 MB / {total_vram} (0.0%)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cdd6f4"
        )
        self.rtx_vram_lbl.pack(anchor="w", padx=12, pady=(2, 3))

        self.rtx_progress = ctk.CTkProgressBar(parent, height=8, fg_color="#313244", progress_color=title_color)
        self.rtx_progress.pack(fill="x", padx=12, pady=(0, 5))
        self.rtx_progress.set(0.0)

        self.rtx_stats_lbl = ctk.CTkLabel(
            parent,
            text="Power: -- W  •  Temp: --°C  •  Load: --%",
            font=ctk.CTkFont(size=11),
            text_color="#a6adc8"
        )
        self.rtx_stats_lbl.pack(anchor="w", padx=12, pady=(0, 8))

    def _build_amd_card_ui(self, parent):
        top_row = ctk.CTkFrame(parent, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 2))

        if self.gpu2:
            title_text = self.gpu2_short
            badge_text = f"Integrated • {round(self.gpu2['dedicated_mb'])}MB"
            title_color = "#89b4fa" if self.gpu2.get("vendor") == "Intel" else "#fab387"
        else:
            title_text = "Secondary GPU"
            badge_text = "Not Present"
            title_color = "#6c7086"

        title = ctk.CTkLabel(
            top_row,
            text=title_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=title_color
        )
        title.pack(side="left")

        self.amd_badge = ctk.CTkLabel(
            top_row,
            text=badge_text,
            font=ctk.CTkFont(size=10),
            text_color="#a6adc8"
        )
        self.amd_badge.pack(side="right")

        total_vram = f"{self.gpu2['dedicated_mb']:,.0f} MB" if self.gpu2 else "--"
        self.amd_vram_lbl = ctk.CTkLabel(
            parent,
            text=f"Dedicated VRAM: 0 MB / {total_vram} (0.0%)" if self.gpu2 else "Single-GPU Configuration",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cdd6f4"
        )
        self.amd_vram_lbl.pack(anchor="w", padx=12, pady=(2, 3))

        self.amd_progress = ctk.CTkProgressBar(parent, height=8, fg_color="#313244", progress_color=title_color)
        self.amd_progress.pack(fill="x", padx=12, pady=(0, 5))
        self.amd_progress.set(0.0)

        self.amd_stats_lbl = ctk.CTkLabel(
            parent,
            text="Free: -- MB  •  Shared Used: -- MB" if self.gpu2 else "All applications run on Primary GPU",
            font=ctk.CTkFont(size=11),
            text_color="#a6adc8"
        )
        self.amd_stats_lbl.pack(anchor="w", padx=12, pady=(0, 8))

    def _build_cpu_card_ui(self, parent):
        top_row = ctk.CTkFrame(parent, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 2))

        cpu_display = self.backend.cpu_model_name
        if len(cpu_display) > 28:
            cpu_display = cpu_display[:26].strip() + ".."

        title = ctk.CTkLabel(
            top_row,
            text=cpu_display,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#89b4fa"
        )
        title.pack(side="left")

        self.cpu_badge = ctk.CTkLabel(
            top_row,
            text="CPU",
            font=ctk.CTkFont(size=10),
            text_color="#a6adc8"
        )
        self.cpu_badge.pack(side="right")

        self.cpu_power_lbl = ctk.CTkLabel(
            parent,
            text="CPU Package Power: 0.0 W",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cdd6f4"
        )
        self.cpu_power_lbl.pack(anchor="w", padx=12, pady=(2, 3))

        self.cpu_progress = ctk.CTkProgressBar(parent, height=8, fg_color="#313244", progress_color="#89b4fa")
        self.cpu_progress.pack(fill="x", padx=12, pady=(0, 5))
        self.cpu_progress.set(0.0)

        self.cpu_stats_lbl = ctk.CTkLabel(
            parent,
            text="CPU Load: 0.0%  •  RAM: 0.0 GB / 0.0 GB",
            font=ctk.CTkFont(size=11),
            text_color="#a6adc8"
        )
        self.cpu_stats_lbl.pack(anchor="w", padx=12, pady=(0, 8))

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0, bg="#1e1e2e", fg="#cdd6f4", activebackground="#313244", activeforeground="#ffffff")
        
        # GPU Preference Submenu
        pref_menu = tk.Menu(self.context_menu, tearoff=0, bg="#1e1e2e", fg="#cdd6f4", activebackground="#313244", activeforeground="#ffffff")
        if self.gpu2:
            pref_menu.add_command(label=f"🟢 Power Saving ({self.gpu2_short})", command=lambda: self._set_pref_from_menu(1))
            pref_menu.add_command(label=f"⚡ High Performance ({self.gpu1_short})", command=lambda: self._set_pref_from_menu(2))
        else:
            pref_menu.add_command(label=f"⚡ High Performance ({self.gpu1_short})", command=lambda: self._set_pref_from_menu(2))
        pref_menu.add_command(label="⚪ Let Windows Decide (Auto)", command=lambda: self._set_pref_from_menu(0))
        self.context_menu.add_cascade(label="🎯 Set Windows GPU Preference", menu=pref_menu)

        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 Restart App", command=self._restart_selected)
        self.context_menu.add_command(label="❌ End Task", command=lambda: self._kill_selected(force=False))
        self.context_menu.add_command(label="⚡ Force Kill Process", command=lambda: self._kill_selected(force=True))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🧹 Flush Working Set", command=self._trim_selected)
        self.context_menu.add_command(label="📁 Open File Location", command=self._open_selected_location)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋 Copy Process Details", command=self._copy_selected_info)

    def _show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self.context_menu.post(event.x_root, event.y_root)

    # --- Live Background Polling Loop ---
    def _background_poll_loop(self):
        while self.is_running:
            if self.refresh_interval > 0:
                t0 = time.time()
                self._fetch_and_update()
                elapsed = time.time() - t0
                sleep_time = max(0.05, self.refresh_interval - elapsed)
                time.sleep(sleep_time)
            else:
                time.sleep(0.5)

    def _fetch_and_update(self):
        if self.is_fetching:
            return
        self.is_fetching = True
        try:
            overview, procs, cpu_stats = self.backend.get_live_telemetry()
            self.after(0, self._apply_update, overview, procs, cpu_stats)
        except Exception as e:
            print(f"[Live Fetch Error] {e}")
        finally:
            self.is_fetching = False

    def _trigger_immediate_refresh(self):
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _apply_update(self, overview, procs, cpu_stats):
        self.last_gpu_data = overview
        self.last_procs_data = procs
        self.last_cpu_data = cpu_stats

        if self.refresh_interval > 0:
            now_str = datetime.now().strftime("%H:%M:%S")
            self.live_badge.configure(text=f"● LIVE ({self.refresh_interval}s) {now_str}", text_color="#a6e3a1")
        else:
            self.live_badge.configure(text="⏸ PAUSED", text_color="#f9e2af")

        # 1. Update Hardware Cards
        self._update_cards(overview, cpu_stats)

        # 2. Update Table
        self._render_table_live()

    def _update_cards(self, overview, cpu_stats):
        # Update GPU 1 Card
        if self.gpu1 and self.gpu1["luid"] in overview:
            gpu = overview[self.gpu1["luid"]]
            ded_used = gpu.get("dedicated_used_mb", 0.0)
            ded_total = max(gpu.get("dedicated_total_mb", 1.0), 1.0)
            ded_pct = min(100.0, (ded_used / ded_total) * 100.0)
            free_mb = max(0.0, ded_total - ded_used)

            bar_color = "#a6e3a1" if ded_pct < 65 else ("#f9e2af" if ded_pct < 85 else "#f38ba8")

            self.rtx_vram_lbl.configure(
                text=f"VRAM: {ded_used:,.1f} MB / {ded_total:,.1f} MB ({ded_pct:.1f}%)"
            )
            self.rtx_progress.configure(progress_color=bar_color)
            self.rtx_progress.set(ded_pct / 100.0)

            temp_str = f"{gpu['temperature']}°C" if gpu.get("temperature") is not None else "--°C"
            util_str = f"{gpu['gpu_util']}%" if gpu.get("gpu_util") is not None else "--%"
            pwr_str = f"{gpu['power_watts']} W" if gpu.get("power_watts") is not None else "-- W"

            if gpu.get("temperature") is not None or gpu.get("power_watts") is not None:
                self.rtx_stats_lbl.configure(
                    text=f"Power: {pwr_str}  •  Temp: {temp_str}  •  Load: {util_str}"
                )
            else:
                shd_used = gpu.get("shared_used_mb", 0.0)
                self.rtx_stats_lbl.configure(
                    text=f"Free: {free_mb:,.1f} MB  •  Shared Used: {shd_used:,.1f} MB"
                )

        # Update GPU 2 Card
        if self.gpu2 and self.gpu2["luid"] in overview:
            gpu = overview[self.gpu2["luid"]]
            ded_used = gpu.get("dedicated_used_mb", 0.0)
            ded_total = max(gpu.get("dedicated_total_mb", 1.0), 1.0)
            ded_pct = min(100.0, (ded_used / ded_total) * 100.0)
            free_mb = max(0.0, ded_total - ded_used)
            shd_used = gpu.get("shared_used_mb", 0.0)

            bar_color = "#fab387" if ded_pct < 65 else ("#f9e2af" if ded_pct < 85 else "#f38ba8")

            self.amd_vram_lbl.configure(
                text=f"Dedicated VRAM: {ded_used:,.1f} MB / {ded_total:,.1f} MB ({ded_pct:.1f}%)"
            )
            self.amd_progress.configure(progress_color=bar_color)
            self.amd_progress.set(ded_pct / 100.0)

            self.amd_stats_lbl.configure(
                text=f"Free: {free_mb:,.1f} MB  •  Shared Used: {shd_used:,.1f} MB"
            )

        # Update CPU Card
        if cpu_stats:
            pwr = cpu_stats.get("power_watts", 0.0)
            load = cpu_stats.get("load_percent", 0.0)
            ram_u = cpu_stats.get("ram_used_gb", 0.0)
            ram_t = cpu_stats.get("ram_total_gb", 0.0)
            ram_p = cpu_stats.get("ram_percent", 0.0)
            cores = cpu_stats.get("cores", "")

            if cores:
                self.cpu_badge.configure(text=cores)
            if pwr > 0:
                self.cpu_power_lbl.configure(text=f"CPU Package Power: {pwr:.1f} Watts")
            else:
                self.cpu_power_lbl.configure(text=f"CPU Utilization: {load:.1f}%")

            cpu_bar_color = "#89b4fa" if load < 65 else ("#f9e2af" if load < 85 else "#f38ba8")
            self.cpu_progress.configure(progress_color=cpu_bar_color)
            self.cpu_progress.set(min(1.0, max(0.0, load / 100.0)))

            self.cpu_stats_lbl.configure(
                text=f"CPU Load: {load:.1f}%  •  RAM: {ram_u} GB / {ram_t} GB ({ram_p:.0f}%)"
            )

    def _render_table_live(self):
        filtered = []
        target_tab = self.selected_gpu_tab
        search = self.search_filter.lower().strip()
        hide_sys = self.sys_switch_var.get()

        total_vram_sum = 0.0

        for p in self.last_procs_data:
            if hide_sys and p["is_protected"]:
                continue

            if target_tab != "All GPUs":
                if self.gpu1 and target_tab == self.gpu1_short:
                    if p.get("gpu_luid") != self.gpu1["luid"]:
                        continue
                elif self.gpu2 and target_tab == self.gpu2_short:
                    if p.get("gpu_luid") != self.gpu2["luid"]:
                        continue

            if search:
                name_match = search in p["name"].lower()
                pid_match = search in str(p["pid"])
                path_match = search in p["exe"].lower()
                if not (name_match or pid_match or path_match):
                    continue

            filtered.append(p)
            total_vram_sum += p["dedicated_mb"]

        # Sort
        col_key = self.sort_column
        reverse = self.sort_descending

        def sort_key_func(item):
            val = item.get(col_key, "")
            if isinstance(val, (int, float)):
                return val
            return str(val).lower()

        filtered.sort(key=sort_key_func, reverse=reverse)

        # In-place live update
        existing_rows = set(self.tree.get_children())
        active_row_ids = set()

        for idx, p in enumerate(filtered):
            row_id = f"{p['pid']}_{p['gpu_luid']}"
            active_row_ids.add(row_id)

            if self.gpu1 and p.get("gpu_luid") == self.gpu1["luid"]:
                gpu_display = self.gpu1_short
            elif self.gpu2 and p.get("gpu_luid") == self.gpu2["luid"]:
                gpu_display = self.gpu2_short
            else:
                gpu_display = self._get_short_name(p.get("gpu_name", ""))

            p_type = "🛡 Protected" if p["is_protected"] else "Application"
            pref_text, _ = self._get_pref_display(p.get("gpu_pref", 0))

            vals = (
                p["name"],
                p["pid"],
                gpu_display,
                pref_text,
                f"{p['dedicated_mb']:.1f} MB",
                f"{p['shared_mb']:.1f} MB",
                f"{p['total_gpu_mb']:.1f} MB",
                f"{p['ram_mb']:.1f} MB",
                p_type,
                p["exe"]
            )

            if row_id in existing_rows:
                current_vals = self.tree.item(row_id, "values")
                if current_vals != vals:
                    self.tree.item(row_id, values=vals)
                self.tree.move(row_id, "", idx)
            else:
                self.tree.insert("", idx, iid=row_id, values=vals)

        dead_rows = existing_rows - active_row_ids
        for dead_id in dead_rows:
            self.tree.delete(dead_id)

        self.status_count_lbl.configure(
            text=f"Showing {len(filtered)} processes  |  Live VRAM Total: {total_vram_sum:,.1f} MB"
        )

        self._update_selected_action_buttons()

    def _on_heading_click(self, col):
        col_map = {
            "name": "name",
            "pid": "pid",
            "gpu": "gpu_name",
            "pref": "gpu_pref",
            "dedicated": "dedicated_mb",
            "shared": "shared_mb",
            "total": "total_gpu_mb",
            "ram": "ram_mb",
            "type": "is_protected",
            "path": "exe"
        }
        mapped_key = col_map.get(col, "dedicated_mb")
        if self.sort_column == mapped_key:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = mapped_key
            self.sort_descending = True

        for c, text, _, _ in [
            ("name", "Process Name", 180, "w"),
            ("pid", "PID", 70, "center"),
            ("gpu", "Active GPU", 100, "center"),
            ("pref", "GPU Preference", 160, "center"),
            ("dedicated", "Dedicated VRAM", 130, "e"),
            ("shared", "Shared Memory", 110, "e"),
            ("total", "Total GPU", 110, "e"),
            ("ram", "System RAM", 95, "e"),
            ("type", "Type", 95, "center"),
            ("path", "Executable Path", 260, "w")
        ]:
            if col_map.get(c) == self.sort_column:
                arrow = " ▼" if self.sort_descending else " ▲"
                self.tree.heading(c, text=text + arrow)
            else:
                self.tree.heading(c, text=text)

        self._render_table_live()

    def _on_tree_select(self, event=None):
        self._update_selected_action_buttons()

    def _update_selected_action_buttons(self):
        selected = self.tree.selection()
        if not selected:
            self.selected_info_lbl.configure(
                text="No process selected. Click a process in the table to manage.",
                text_color="#a6adc8"
            )
            self.end_task_btn.configure(state="disabled")
            self.force_kill_btn.configure(state="disabled")
            self.open_loc_btn.configure(state="disabled")
            self.restart_btn.configure(state="disabled")
            self.trim_btn.configure(state="disabled")
            self.pref_combo.configure(state="disabled")
            self.apply_pref_btn.configure(state="disabled")
            return

        self.end_task_btn.configure(state="normal")
        self.force_kill_btn.configure(state="normal")
        self.open_loc_btn.configure(state="normal")
        self.restart_btn.configure(state="normal")
        self.trim_btn.configure(state="normal")
        self.pref_combo.configure(state="normal")
        self.apply_pref_btn.configure(state="normal")

        if len(selected) == 1:
            item = self.tree.item(selected[0], "values")
            name = item[0]
            pid = item[1]
            gpu = item[2]
            pref = item[3]
            vram = item[4]
            path = item[9]
            self.selected_info_lbl.configure(
                text=f"Selected: {name} (PID: {pid}) • {vram} on {gpu} • Current: {pref}",
                text_color="#cdd6f4"
            )
            # Sync combo selection with process
            if "Power" in pref:
                self.pref_combo.set(self.pref_options[0])
            elif "Perf" in pref:
                self.pref_combo.set(self.pref_options[1] if self.gpu2 else self.pref_options[0])
            else:
                self.pref_combo.set("Windows Auto (Default)")
        else:
            self.selected_info_lbl.configure(
                text=f"Selected: {len(selected)} processes in bulk",
                text_color="#cdd6f4"
            )

    def _on_tree_double_click(self, event):
        self._open_selected_location()

    # --- GPU Preference Actions ---
    def _apply_gpu_preference(self):
        selected = self.tree.selection()
        if not selected:
            return

        choice = self.pref_combo.get()
        if "Power" in choice:
            code = 1
            gpu_name = f"{self.gpu2_short} (Power Saving)" if self.gpu2 else "Power Saving"
        elif "Perf" in choice or "High" in choice:
            code = 2
            gpu_name = f"{self.gpu1_short} (High Performance)" if self.gpu1 else "High Performance"
        else:
            code = 0
            gpu_name = "Windows Auto (Default)"

        count = 0
        names = []
        for row_id in selected:
            item = self.tree.item(row_id, "values")
            name = item[0]
            exe_path = item[9]

            if not exe_path:
                continue

            if self.backend.set_gpu_preference(exe_path, code):
                count += 1
                names.append(name)

        if count == 0:
            messagebox.showinfo("Preference", "No valid executable path found for selected process(es).", parent=self)
            return

        self._trigger_immediate_refresh()

        messagebox.showinfo(
            "GPU Preference Applied",
            f"Successfully applied GPU preference:\n👉 {gpu_name}\nfor: {', '.join(names)}\n\n"
            f"Preference is saved in Windows.\nIt will take effect when you manually restart the app.",
            parent=self
        )

    def _set_pref_from_menu(self, code):
        selected = self.tree.selection()
        if not selected:
            return

        gpu_name = f"{self.gpu2_short} (Power Saving)" if (code == 1 and self.gpu2) else (f"{self.gpu1_short} (High Performance)" if code == 2 else "Windows Auto")
        count = 0
        names = []
        for row_id in selected:
            item = self.tree.item(row_id, "values")
            name = item[0]
            exe_path = item[9]
            if exe_path and self.backend.set_gpu_preference(exe_path, code):
                count += 1
                names.append(name)

        if count > 0:
            self._trigger_immediate_refresh()
            messagebox.showinfo(
                "GPU Preference Applied",
                f"Preference set to: {gpu_name}\nfor: {', '.join(names)}\n\n"
                f"Preference is saved in Windows.\nIt will take effect when you manually restart the app.",
                parent=self
            )

    # --- Actions ---
    def _restart_selected(self):
        selected = self.tree.selection()
        if not selected:
            return

        restarted = 0
        errors = []

        for row_id in selected:
            item = self.tree.item(row_id, "values")
            name = item[0]
            pid = int(item[1])
            p_type = item[8]
            exe_path = item[9]

            if not exe_path or not os.path.exists(exe_path):
                errors.append(f"{name}: executable path not found or not accessible.")
                continue

            if "Protected" in p_type or pid <= 4:
                confirm = messagebox.askyesno(
                    "System Process Warning",
                    f"{name} is a protected Windows system component.\nRestarting it may disrupt your desktop session.\nDo you want to continue?",
                    parent=self
                )
                if not confirm:
                    continue

            ok, msg = self.backend.restart_process(pid, exe_path)
            if ok:
                restarted += 1
            else:
                errors.append(msg)

        self._trigger_immediate_refresh()

        if errors:
            messagebox.showwarning("Restart App", f"Restarted {restarted} app(s).\nNotes:\n" + "\n".join(errors), parent=self)
        elif restarted > 0:
            messagebox.showinfo("Restart App", f"Successfully restarted {restarted} application(s).", parent=self)

    def _open_selected_location(self):
        selected = self.tree.selection()
        if not selected:
            return
        row_id = selected[0]
        item = self.tree.item(row_id, "values")
        exe_path = item[9]
        if exe_path and os.path.exists(exe_path):
            try:
                subprocess.Popen(f'explorer /select,"{exe_path}"')
            except Exception as e:
                messagebox.showerror("Error", f"Could not open location: {e}", parent=self)
        else:
            messagebox.showinfo("Info", "Executable path is not available or file does not exist.", parent=self)

    def _trim_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        count = 0
        for row_id in selected:
            item = self.tree.item(row_id, "values")
            try:
                pid = int(item[1])
                if self.backend.trim_process_working_set(pid):
                    count += 1
            except:
                pass
        self._trigger_immediate_refresh()
        messagebox.showinfo("Working Set Trimmed", f"Flushed memory working set for {count} process(es).", parent=self)

    def _copy_selected_info(self):
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for row_id in selected:
            item = self.tree.item(row_id, "values")
            lines.append(f"{item[0]} (PID: {item[1]}) - Active: {item[2]} - Pref: {item[3]} - VRAM: {item[4]} - Path: {item[9]}")
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"Copied {len(lines)} process details to clipboard.", parent=self)

    def _kill_selected(self, force=False):
        selected = self.tree.selection()
        if not selected:
            return

        pids = []
        for row_id in selected:
            item = self.tree.item(row_id, "values")
            try:
                pids.append(int(item[1]))
            except:
                pass

        pids = list(set(pids))

        protected_in_selection = []
        for p in self.last_procs_data:
            if p["pid"] in pids and p["is_protected"]:
                protected_in_selection.append(f"{p['name']} (PID: {p['pid']})")

        if protected_in_selection:
            warn_msg = (
                f"WARNING: You have selected system-critical process(es):\n"
                f"{', '.join(protected_in_selection)}\n\n"
                f"Terminating Windows system processes can crash your desktop session or restart your PC!\n"
                f"Do you really want to continue?"
            )
            confirm = messagebox.askyesno("CRITICAL SYSTEM WARNING", warn_msg, icon="warning", parent=self)
            if not confirm:
                return

        action_name = "Force Kill" if force else "End Task"
        confirm = messagebox.askyesno(
            f"Confirm {action_name}",
            f"Are you sure you want to {action_name.lower()} {len(pids)} process(es)?",
            parent=self
        )
        if not confirm:
            return

        success_count = 0
        errors = []
        for pid in pids:
            ok, msg = self.backend.end_task(pid, force=force)
            if ok:
                success_count += 1
            else:
                errors.append(msg)

        self._trigger_immediate_refresh()

        if errors:
            messagebox.showwarning("Result", f"Ended {success_count} processes.\nErrors:\n" + "\n".join(errors), parent=self)

    def _open_vram_cleaner(self):
        VRAMCleanerDialog(self, self.backend, on_clean_callback=self._trigger_immediate_refresh)

    def _on_interval_change(self, choice):
        if "0.5s" in choice:
            self.refresh_interval = 0.5
        elif "1s" in choice:
            self.refresh_interval = 1.0
        elif "2s" in choice:
            self.refresh_interval = 2.0
        else:
            self.refresh_interval = 0.0

    def _on_gpu_tab_change(self, choice):
        self.selected_gpu_tab = choice
        self._render_table_live()

    def _on_sys_switch_toggle(self):
        self._render_table_live()

    def _on_search_key(self, event=None):
        self.search_filter = self.search_entry.get()
        self._render_table_live()

    def _on_close(self):
        self.is_running = False
        try:
            self.backend.close()
        except:
            pass
        self.destroy()
