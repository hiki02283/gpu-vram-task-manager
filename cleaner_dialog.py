"""
VRAM Cleaner Dialog
Allows one-click analysis and selective termination of VRAM-hogging background tasks.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

class VRAMCleanerDialog(ctk.CTkToplevel):
    def __init__(self, parent, backend, on_clean_callback):
        super().__init__(parent)
        self.parent = parent
        self.backend = backend
        self.on_clean_callback = on_clean_callback

        self.title("GPU VRAM Cleaner & Optimizer")
        self.geometry("720x580")
        self.minsize(640, 500)
        self.transient(parent)
        self.grab_set()

        # State
        self.check_vars = {}  # pid -> (CTkCheckBox, BooleanVar, process_dict)
        self.adapter_lookup = {}
        
        valid_adapters = [a for a in self.backend.adapters.values() if not a.get("is_software", False)]
        valid_adapters.sort(key=lambda a: (a.get("vendor") == "NVIDIA", a.get("dedicated_mb", 0)), reverse=True)
        
        self.adapter_names = ["All GPUs"]
        for a in valid_adapters:
            name = a["name"].replace("(R)", "").replace("(TM)", "").replace("Graphics", "").replace("Laptop GPU", "")
            s_name = " ".join(name.split()).replace("NVIDIA GeForce", "GeForce")
            if len(s_name) > 26:
                s_name = s_name[:25].strip() + ".."
            self.adapter_lookup[s_name] = a["luid"]
            self.adapter_names.append(s_name)

        initial_filter = self.adapter_names[1] if len(self.adapter_names) > 1 else "All GPUs"
        self.selected_gpu_filter = tk.StringVar(value=initial_filter)

        self._build_ui()
        self._populate_candidates()

    def _build_ui(self):
        # Header banner
        header_frame = ctk.CTkFrame(self, fg_color="#181825", corner_radius=0)
        header_frame.pack(fill="x", padx=0, pady=0)

        title_lbl = ctk.CTkLabel(
            header_frame, 
            text="🧹 GPU VRAM Cleaner", 
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#cdd6f4"
        )
        title_lbl.pack(anchor="w", padx=20, pady=(15, 2))

        sub_lbl = ctk.CTkLabel(
            header_frame,
            text="Scan, select, and terminate non-essential background processes holding VRAM textures and buffers.",
            font=ctk.CTkFont(size=12),
            text_color="#a6adc8"
        )
        sub_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        # Filter and Controls Row
        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=20, pady=(15, 5))

        gpu_lbl = ctk.CTkLabel(ctrl_frame, text="Target GPU:", font=ctk.CTkFont(size=12, weight="bold"))
        gpu_lbl.pack(side="left", padx=(0, 8))

        self.gpu_selector = ctk.CTkSegmentedButton(
            ctrl_frame,
            values=self.adapter_names,
            variable=self.selected_gpu_filter,
            command=lambda v: self._populate_candidates()
        )
        self.gpu_selector.pack(side="left", padx=5)

        # Quick select buttons
        select_all_btn = ctk.CTkButton(
            ctrl_frame, 
            text="Select All", 
            width=80, 
            height=28,
            fg_color="#313244", 
            hover_color="#45475a",
            command=self._select_all
        )
        select_all_btn.pack(side="right", padx=(5, 0))

        deselect_all_btn = ctk.CTkButton(
            ctrl_frame, 
            text="Deselect All", 
            width=80, 
            height=28,
            fg_color="#313244", 
            hover_color="#45475a",
            command=self._deselect_all
        )
        deselect_all_btn.pack(side="right", padx=(5, 0))

        # Scrollable candidates container
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="#181825", corner_radius=8)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Footer / Action Area
        footer_frame = ctk.CTkFrame(self, fg_color="#11111b", corner_radius=0)
        footer_frame.pack(fill="x", padx=0, pady=0)

        # Summary readout
        self.summary_lbl = ctk.CTkLabel(
            footer_frame,
            text="Selected to reclaim: 0.0 MB VRAM (0 processes)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#a6e3a1"
        )
        self.summary_lbl.pack(side="left", padx=20, pady=15)

        # Clean Action Button
        self.clean_btn = ctk.CTkButton(
            footer_frame,
            text="🚀 Clean & Free VRAM Now",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#f38ba8",
            hover_color="#eba0ac",
            text_color="#11111b",
            height=38,
            width=200,
            command=self._execute_clean
        )
        self.clean_btn.pack(side="right", padx=20, pady=15)

    def _populate_candidates(self):
        # Clear existing
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.check_vars.clear()

        # Fetch current list
        procs = self.backend.get_process_vram_list()
        target = self.selected_gpu_filter.get()
        target_luid = self.adapter_lookup.get(target)

        # Filter candidates: non-protected, dedicated VRAM > 0
        candidates = []
        for p in procs:
            if p["is_protected"]:
                continue
            if p["dedicated_mb"] <= 0.1:
                continue
            
            if target != "All GPUs" and target_luid:
                if p.get("gpu_luid") != target_luid:
                    continue

            candidates.append(p)

        if not candidates:
            empty_lbl = ctk.CTkLabel(
                self.scroll_frame,
                text="✨ No unnecessary background processes found consuming VRAM on this GPU!\nYour VRAM is already clean.",
                font=ctk.CTkFont(size=13),
                text_color="#a6adc8",
                justify="center"
            )
            empty_lbl.pack(pady=40)
            self._update_summary()
            return

        # Render list of candidates
        for p in candidates:
            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color="#1e1e2e", corner_radius=6)
            row_frame.pack(fill="x", padx=5, pady=4)

            var = tk.BooleanVar(value=True)  # default checked
            self.check_vars[p["pid"]] = (var, p)

            chk = ctk.CTkCheckBox(
                row_frame,
                text="",
                variable=var,
                width=24,
                checkbox_width=20,
                checkbox_height=20,
                command=self._update_summary
            )
            chk.pack(side="left", padx=(10, 5), pady=8)

            # Process Name & PID
            name_box = ctk.CTkFrame(row_frame, fg_color="transparent")
            name_box.pack(side="left", fill="both", expand=True, padx=5, pady=6)

            p_title = ctk.CTkLabel(
                name_box,
                text=f"{p['name']} (PID: {p['pid']})",
                font=ctk.CTkFont(size=13, weight="bold"),
                anchor="w",
                text_color="#cdd6f4"
            )
            p_title.pack(anchor="w")

            path_snippet = p["exe"] if p["exe"] else "Path unavailable"
            if len(path_snippet) > 65:
                path_snippet = path_snippet[:30] + "..." + path_snippet[-32:]

            p_sub = ctk.CTkLabel(
                name_box,
                text=f"{path_snippet}  •  {p['gpu_name']}",
                font=ctk.CTkFont(size=11),
                anchor="w",
                text_color="#6c7086"
            )
            p_sub.pack(anchor="w")

            # VRAM Badge
            vram_badge = ctk.CTkLabel(
                row_frame,
                text=f"{p['dedicated_mb']:.1f} MB VRAM",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#fab387",
                width=110,
                anchor="e"
            )
            vram_badge.pack(side="right", padx=15, pady=8)

        self._update_summary()

    def _select_all(self):
        for var, _ in self.check_vars.values():
            var.set(True)
        self._update_summary()

    def _deselect_all(self):
        for var, _ in self.check_vars.values():
            var.set(False)
        self._update_summary()

    def _update_summary(self):
        total_mb = 0.0
        count = 0
        for var, p in self.check_vars.values():
            if var.get():
                total_mb += p["dedicated_mb"]
                count += 1

        self.summary_lbl.configure(
            text=f"Selected to reclaim: {total_mb:.1f} MB VRAM ({count} processes)"
        )
        if count == 0:
            self.clean_btn.configure(state="disabled", text="Select Processes")
        else:
            self.clean_btn.configure(state="normal", text=f"🚀 Clean & Free {total_mb:.0f} MB VRAM")

    def _execute_clean(self):
        selected_pids = [pid for pid, (var, p) in self.check_vars.items() if var.get()]
        if not selected_pids:
            return

        confirm = messagebox.askyesno(
            "Confirm VRAM Clean",
            f"Are you sure you want to end {len(selected_pids)} selected process(es) to reclaim VRAM?\nAny unsaved work in these apps may be lost.",
            parent=self
        )
        if not confirm:
            return

        # Perform cleanup
        result = self.backend.clean_vram_targets(selected_pids)
        
        msg = f"Cleaned successfully!\nClosed {result['closed_count']} processes.\nFreed ~{result['freed_mb']:.1f} MB of GPU VRAM."
        if result['errors']:
            msg += f"\n\nNote: {len(result['errors'])} processes could not be closed (e.g. system permission)."

        messagebox.showinfo("VRAM Clean Complete", msg, parent=self)

        # Notify parent to refresh and close dialog
        if self.on_clean_callback:
            self.on_clean_callback()
        self.destroy()
