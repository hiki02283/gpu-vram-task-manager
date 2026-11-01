"""
GPU Backend module for GPU VRAM Manager & Cleaner.
Queries DXGI, NVML, Windows PDH counters, RAPL CPU power, and psutil.
Provides per-process VRAM metrics, GPU telemetry, CPU power, and Windows DirectX GPU Preferences.
"""

import os
import sys
import time
import winreg
import ctypes
import subprocess
from ctypes import wintypes, c_uint, c_ulonglong, Structure, byref, create_string_buffer
import psutil
import win32pdh

# --- Critical Windows system processes that shouldn't be terminated without warning ---
PROTECTED_PROCESSES = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", 
    "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "dwm.exe", 
    "explorer.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "spoolsv.exe"
}

# --- DXGI Data Structures ---
class LUID(Structure):
    _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

class DXGI_ADAPTER_DESC(Structure):
    _fields_ = [
        ('Description', wintypes.WCHAR * 128),
        ('VendorId', wintypes.UINT),
        ('DeviceId', wintypes.UINT),
        ('SubSysId', wintypes.UINT),
        ('Revision', wintypes.UINT),
        ('DedicatedVideoMemory', ctypes.c_size_t),
        ('DedicatedSystemMemory', ctypes.c_size_t),
        ('SharedSystemMemory', ctypes.c_size_t),
        ('AdapterLuid', LUID),
    ]

# --- NVML Structures ---
class NVMLUtilization(Structure):
    _fields_ = [('gpu', c_uint), ('memory', c_uint)]

class NVMLMemory(Structure):
    _fields_ = [('total', c_ulonglong), ('free', c_ulonglong), ('used', c_ulonglong)]


class WindowsGpuPreferences:
    """Manages Windows DirectX UserGpuPreferences in the registry."""
    KEY_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"

    @classmethod
    def get_all_preferences(cls):
        """Returns dict mapping lowercased exe_path -> pref_code (1=PowerSaving, 2=HighPerf, 0=Default)."""
        prefs = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.KEY_PATH, 0, winreg.KEY_READ) as key:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        prefs[name.lower()] = cls._parse_code(val)
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            pass
        return prefs

    @classmethod
    def get_preference_for_exe(cls, exe_path):
        if not exe_path:
            return 0
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.KEY_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, exe_path)
                return cls._parse_code(val)
        except (FileNotFoundError, OSError):
            return 0

    @classmethod
    def set_preference(cls, exe_path, pref_code):
        """
        Set GPU preference for executable.
        pref_code: 1 = Power Saving (AMD Radeon 780M)
                   2 = High Performance (NVIDIA RTX 5050)
                   0 = Let Windows Decide (Auto/Delete)
        """
        if not exe_path:
            return False
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cls.KEY_PATH) as key:
                if pref_code == 0:
                    try:
                        val, _ = winreg.QueryValueEx(key, exe_path)
                        parts = [p for p in val.split(';') if not p.startswith('GpuPreference=') and p]
                        if parts:
                            winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, ';'.join(parts) + ';')
                        else:
                            winreg.DeleteValue(key, exe_path)
                    except FileNotFoundError:
                        pass
                else:
                    try:
                        val, _ = winreg.QueryValueEx(key, exe_path)
                        parts = [p for p in val.split(';') if not p.startswith('GpuPreference=') and p]
                    except FileNotFoundError:
                        parts = []
                    parts.append(f"GpuPreference={pref_code}")
                    new_val = ';'.join(parts) + ';'
                    winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, new_val)
            return True
        except Exception as e:
            print(f"[SetGpuPreference Error] {e}")
            return False

    @staticmethod
    def _parse_code(val_str):
        if not val_str:
            return 0
        for part in val_str.split(';'):
            if part.startswith('GpuPreference='):
                try:
                    return int(part.split('=')[1])
                except:
                    pass
        return 0


class GPUBackend:
    @staticmethod
    def get_cpu_model_name():
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                val, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                clean = " ".join(val.replace("(R)", "").replace("(TM)", "").split())
                return clean.strip()
        except Exception:
            try:
                import platform
                return platform.processor() or "CPU"
            except:
                return "CPU"

    def __init__(self):
        self.adapters = {}
        self.nvml_initialized = False
        self.nvml_device = None
        self.nvml_lib = None
        self.proc_info_cache = {}
        self.cpu_model_name = self.get_cpu_model_name()
        self._init_dxgi()
        self._init_nvml()

    def _init_dxgi(self):
        try:
            dxgi = ctypes.WinDLL('dxgi.dll')
            IID_IDXGIFactory = (ctypes.c_char * 16)(
                0xec, 0x66, 0x71, 0x7b, 0xc7, 0x21, 0xae, 0x44, 0xb2, 0x1a, 0xc9, 0xae, 0x32, 0x1a, 0xe3, 0x69
            )
            pFactory = ctypes.c_void_p()
            hr = dxgi.CreateDXGIFactory(IID_IDXGIFactory, byref(pFactory))
            if hr != 0:
                return

            vtable = ctypes.cast(pFactory.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            EnumAdapters_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
            EnumAdapters = EnumAdapters_proto(vtable[7])
            Release_proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
            ReleaseFactory = Release_proto(vtable[2])
            GetDesc_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC))

            idx = 0
            while True:
                pAdapter = ctypes.c_void_p()
                hr = EnumAdapters(pFactory, idx, byref(pAdapter))
                if hr != 0:
                    break
                adapter_vtable = ctypes.cast(pAdapter.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                GetDesc = GetDesc_proto(adapter_vtable[8])
                desc = DXGI_ADAPTER_DESC()
                GetDesc(pAdapter, byref(desc))

                luid_key = f"0x{desc.AdapterLuid.HighPart:08x}_0x{desc.AdapterLuid.LowPart:08x}".lower()
                desc_name = str(desc.Description).strip()
                
                vendor = "Other"
                if desc.VendorId == 0x10DE:
                    vendor = "NVIDIA"
                elif desc.VendorId == 0x1002:
                    vendor = "AMD"
                elif desc.VendorId == 0x8086:
                    vendor = "Intel"

                is_software = "Basic Render" in desc_name or "Microsoft" in desc_name

                self.adapters[luid_key] = {
                    "index": idx,
                    "name": desc_name,
                    "luid": luid_key,
                    "vendor": vendor,
                    "is_software": is_software,
                    "dedicated_bytes": desc.DedicatedVideoMemory,
                    "shared_bytes": desc.SharedSystemMemory,
                    "dedicated_mb": round(desc.DedicatedVideoMemory / (1024 * 1024), 1),
                    "shared_mb": round(desc.SharedSystemMemory / (1024 * 1024), 1),
                }

                adapter_release = Release_proto(adapter_vtable[2])
                adapter_release(pAdapter)
                idx += 1

            ReleaseFactory(pFactory)
        except Exception as e:
            print(f"[DXGI Error] {e}")

    def _init_nvml(self):
        try:
            self.nvml_lib = ctypes.CDLL('nvml.dll')
            if self.nvml_lib.nvmlInit_v2() == 0:
                dev = ctypes.c_void_p()
                if self.nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, byref(dev)) == 0:
                    self.nvml_device = dev
                    self.nvml_initialized = True
        except Exception:
            self.nvml_initialized = False

    def get_nvml_stats(self):
        if not self.nvml_initialized or not self.nvml_device:
            return None
        stats = {}
        try:
            temp = c_uint()
            if self.nvml_lib.nvmlDeviceGetTemperature(self.nvml_device, 0, byref(temp)) == 0:
                stats['temperature'] = temp.value
            
            util = NVMLUtilization()
            if self.nvml_lib.nvmlDeviceGetUtilizationRates(self.nvml_device, byref(util)) == 0:
                stats['gpu_util'] = util.gpu
                stats['mem_util'] = util.memory

            power = c_uint()
            if hasattr(self.nvml_lib, 'nvmlDeviceGetPowerUsage'):
                if self.nvml_lib.nvmlDeviceGetPowerUsage(self.nvml_device, byref(power)) == 0:
                    stats['power_watts'] = round(power.value / 1000.0, 1)

            mem = NVMLMemory()
            if self.nvml_lib.nvmlDeviceGetMemoryInfo(self.nvml_device, byref(mem)) == 0:
                stats['nvml_total_mb'] = mem.total // (1024 * 1024)
                stats['nvml_used_mb'] = mem.used // (1024 * 1024)
                stats['nvml_free_mb'] = mem.free // (1024 * 1024)
        except Exception:
            pass
        return stats

    def get_proc_metadata(self, pid):
        if pid in self.proc_info_cache:
            return self.proc_info_cache[pid]

        name = f"PID {pid}"
        exe_path = ""
        is_protected = False

        try:
            proc = psutil.Process(pid)
            name = proc.name()
            try:
                exe_path = proc.exe()
            except:
                exe_path = ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            if pid == 4:
                name = "System"
            elif pid == 0:
                name = "System Idle"

        name_lower = name.lower()
        if name_lower in PROTECTED_PROCESSES or pid <= 4:
            is_protected = True

        info = (name, exe_path, is_protected)
        self.proc_info_cache[pid] = info
        return info

    def get_live_telemetry(self):
        """
        Unified fast fetch: retrieves GPU adapter overview, CPU RAPL package power,
        and per-process VRAM metrics + GPU preference in a single pass.
        """
        overview = {}
        for luid, info in self.adapters.items():
            if info["is_software"]:
                continue
            overview[luid] = {
                "name": info["name"],
                "luid": luid,
                "vendor": info["vendor"],
                "dedicated_total_mb": info["dedicated_mb"],
                "shared_total_mb": info["shared_mb"],
                "dedicated_used_mb": 0.0,
                "shared_used_mb": 0.0,
                "temperature": None,
                "gpu_util": None,
                "power_watts": None
            }

        cpu_stats = {
            "model": self.cpu_model_name,
            "power_watts": 0.0,
            "load_percent": 0.0,
            "cores": f"{psutil.cpu_count(logical=False)}C/{psutil.cpu_count(logical=True)}T",
            "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "ram_percent": psutil.virtual_memory().percent
        }

        raw_process_data = {}
        query = None

        try:
            query = win32pdh.OpenQuery()
            _, inst_adapt = win32pdh.EnumObjectItems(None, None, 'GPU Adapter Memory', win32pdh.PERF_DETAIL_WIZARD)
            _, inst_proc = win32pdh.EnumObjectItems(None, None, 'GPU Process Memory', win32pdh.PERF_DETAIL_WIZARD)

            # 1. GPU Adapter counters
            counters_adapt = {}
            for inst in inst_adapt:
                inst_lower = inst.lower()
                for luid in overview.keys():
                    if luid in inst_lower:
                        p_ded = win32pdh.MakeCounterPath((None, 'GPU Adapter Memory', inst, None, -1, 'Dedicated Usage'))
                        p_shd = win32pdh.MakeCounterPath((None, 'GPU Adapter Memory', inst, None, -1, 'Shared Usage'))
                        try:
                            h_ded = win32pdh.AddCounter(query, p_ded)
                            h_shd = win32pdh.AddCounter(query, p_shd)
                            counters_adapt[inst] = (luid, h_ded, h_shd)
                        except:
                            pass

            # 2. CPU Power counter (RAPL via Energy Meter)
            h_cpu_power = None
            try:
                p_cpu = win32pdh.MakeCounterPath((None, 'Energy Meter', 'rapl_package0_pkg', None, -1, 'Power'))
                h_cpu_power = win32pdh.AddCounter(query, p_cpu)
            except:
                pass

            # 3. GPU Process counters
            counters_proc = {}
            for inst in inst_proc:
                parts = inst.split('_')
                if len(parts) >= 4 and parts[0].lower() == 'pid':
                    try:
                        pid = int(parts[1])
                        luid_part = f"{parts[3]}_{parts[4]}".lower()
                    except (ValueError, IndexError):
                        continue

                    if luid_part not in self.adapters or self.adapters[luid_part]["is_software"]:
                        continue

                    p_ded = win32pdh.MakeCounterPath((None, 'GPU Process Memory', inst, None, -1, 'Dedicated Usage'))
                    p_shd = win32pdh.MakeCounterPath((None, 'GPU Process Memory', inst, None, -1, 'Shared Usage'))
                    try:
                        h_ded = win32pdh.AddCounter(query, p_ded)
                        h_shd = win32pdh.AddCounter(query, p_shd)
                        counters_proc[inst] = (pid, luid_part, h_ded, h_shd)
                    except:
                        pass

            if counters_adapt or counters_proc:
                win32pdh.CollectQueryData(query)
                time.sleep(0.035)
                win32pdh.CollectQueryData(query)

                # Collect CPU Power
                if h_cpu_power:
                    try:
                        _, v_cpu = win32pdh.GetFormattedCounterValue(h_cpu_power, win32pdh.PDH_FMT_DOUBLE)
                        cpu_stats["power_watts"] = round(v_cpu / 1000.0, 1)
                    except:
                        pass

                # Process Adapter totals
                for inst, (luid, h_ded, h_shd) in counters_adapt.items():
                    try:
                        _, vd = win32pdh.GetFormattedCounterValue(h_ded, win32pdh.PDH_FMT_LARGE)
                        _, vs = win32pdh.GetFormattedCounterValue(h_shd, win32pdh.PDH_FMT_LARGE)
                        overview[luid]["dedicated_used_mb"] += round(vd / (1024 * 1024), 1)
                        overview[luid]["shared_used_mb"] += round(vs / (1024 * 1024), 1)
                    except:
                        pass

                # Process Per-Process metrics
                for inst, (pid, luid_part, h_ded, h_shd) in counters_proc.items():
                    try:
                        _, vd = win32pdh.GetFormattedCounterValue(h_ded, win32pdh.PDH_FMT_LARGE)
                        _, vs = win32pdh.GetFormattedCounterValue(h_shd, win32pdh.PDH_FMT_LARGE)
                        key = (pid, luid_part)
                        if key not in raw_process_data:
                            raw_process_data[key] = {"dedicated": 0, "shared": 0}
                        raw_process_data[key]["dedicated"] += vd
                        raw_process_data[key]["shared"] += vs
                    except:
                        pass

        except Exception as e:
            print(f"[Live Telemetry Error] {e}")
        finally:
            if query:
                try:
                    win32pdh.CloseQuery(query)
                except:
                    pass

        # CPU Load percentage
        try:
            cpu_stats["load_percent"] = psutil.cpu_percent()
        except:
            pass

        # Overlay NVML data
        nvml_stats = self.get_nvml_stats()
        if nvml_stats:
            for luid, gpu in overview.items():
                if gpu["vendor"] == "NVIDIA":
                    gpu["temperature"] = nvml_stats.get("temperature")
                    gpu["gpu_util"] = nvml_stats.get("gpu_util")
                    gpu["power_watts"] = nvml_stats.get("power_watts")
                    if nvml_stats.get("nvml_used_mb") and gpu["dedicated_used_mb"] < 1.0:
                        gpu["dedicated_used_mb"] = float(nvml_stats["nvml_used_mb"])

        # Fetch all user GPU preferences from Windows Registry in one shot
        user_prefs = WindowsGpuPreferences.get_all_preferences()

        # Format process list
        process_list = []
        active_pids = set()

        for (pid, luid), mem in raw_process_data.items():
            ded_mb = round(mem["dedicated"] / (1024 * 1024), 2)
            shd_mb = round(mem["shared"] / (1024 * 1024), 2)

            if ded_mb < 0.1 and shd_mb < 0.1:
                continue

            active_pids.add(pid)
            adapter_info = self.adapters.get(luid, {"name": "Unknown GPU", "vendor": "Unknown"})
            gpu_name = adapter_info["name"]
            gpu_vendor = adapter_info["vendor"]

            name, exe_path, is_protected = self.get_proc_metadata(pid)

            # Match GPU preference
            pref_code = 0
            if exe_path:
                pref_code = user_prefs.get(exe_path.lower(), 0)

            ram_mb = 0.0
            try:
                p_handle = psutil.Process(pid)
                ram_mb = round(p_handle.memory_info().rss / (1024 * 1024), 1)
            except:
                pass

            process_list.append({
                "pid": pid,
                "name": name,
                "exe": exe_path,
                "gpu_name": gpu_name,
                "gpu_vendor": gpu_vendor,
                "gpu_luid": luid,
                "dedicated_mb": ded_mb,
                "shared_mb": shd_mb,
                "total_gpu_mb": round(ded_mb + shd_mb, 2),
                "ram_mb": ram_mb,
                "is_protected": is_protected,
                "gpu_pref": pref_code
            })

        if len(self.proc_info_cache) > 200:
            dead = set(self.proc_info_cache.keys()) - active_pids
            for d in dead:
                self.proc_info_cache.pop(d, None)

        process_list.sort(key=lambda x: x["dedicated_mb"], reverse=True)
        return overview, process_list, cpu_stats

    def get_gpu_overview(self):
        ov, _, _ = self.get_live_telemetry()
        return ov

    def get_process_vram_list(self):
        _, pl, _ = self.get_live_telemetry()
        return pl

    def set_gpu_preference(self, exe_path, pref_code):
        """Set Windows DirectX GPU preference for an application."""
        return WindowsGpuPreferences.set_preference(exe_path, pref_code)

    def restart_process(self, pid, exe_path):
        """Terminate and restart the process with its new GPU preference."""
        if not exe_path or not os.path.exists(exe_path):
            return False, "Executable path does not exist."
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except psutil.TimeoutExpired:
                proc.kill()
        except:
            pass

        try:
            subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
            return True, f"Restarted {os.path.basename(exe_path)}."
        except Exception as e:
            return False, f"Failed to restart: {e}"

    def end_task(self, pid, force=False):
        try:
            proc = psutil.Process(pid)
            self.proc_info_cache.pop(pid, None)
            if force:
                proc.kill()
                return True, f"Process {proc.name()} (PID {pid}) forcibly terminated."
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                    return True, f"Process {proc.name()} (PID {pid}) ended successfully."
                except psutil.TimeoutExpired:
                    proc.kill()
                    return True, f"Process {proc.name()} (PID {pid}) did not exit gracefully, force killed."
        except psutil.NoSuchProcess:
            self.proc_info_cache.pop(pid, None)
            return True, f"Process (PID {pid}) is already closed."
        except psutil.AccessDenied:
            res = os.system(f"taskkill /PID {pid} {'/F' if force else ''} >nul 2>&1")
            if res == 0:
                self.proc_info_cache.pop(pid, None)
                return True, f"Process (PID {pid}) ended via taskkill."
            return False, f"Access denied ending PID {pid}. Administrator rights may be required."
        except Exception as e:
            return False, f"Error ending PID {pid}: {str(e)}"

    def trim_process_working_set(self, pid):
        try:
            psapi = ctypes.WinDLL('psapi.dll')
            kernel32 = ctypes.WinDLL('kernel32.dll')
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_SET_QUOTA = 0x0100
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
            if h_proc:
                res = psapi.EmptyWorkingSet(h_proc)
                kernel32.CloseHandle(h_proc)
                return bool(res)
        except Exception:
            pass
        return False

    def clean_vram_targets(self, pids):
        closed_count = 0
        freed_vram_est = 0.0
        errors = []

        _, current_procs, _ = self.get_live_telemetry()
        vram_map = {p["pid"]: p["dedicated_mb"] for p in current_procs}

        for pid in pids:
            ded = vram_map.get(pid, 0.0)
            success, msg = self.end_task(pid, force=True)
            if success:
                closed_count += 1
                freed_vram_est += ded
            else:
                errors.append(msg)

        try:
            for proc in psutil.process_iter(['pid']):
                p = proc.info['pid']
                if p > 4 and p not in pids:
                    self.trim_process_working_set(p)
        except:
            pass

        return {
            "closed_count": closed_count,
            "freed_mb": round(freed_vram_est, 1),
            "errors": errors
        }

    def close(self):
        if self.nvml_initialized and self.nvml_lib:
            try:
                self.nvml_lib.nvmlShutdown()
            except:
                pass
            self.nvml_initialized = False
