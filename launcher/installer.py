# -*- coding: utf-8 -*-
"""Sin'X Automation -- Enterprise Installer (v1.3.0)"""
from __future__ import annotations
import os, shutil, subprocess, sys, winreg
from pathlib import Path

APP_NAME = "Sin'X Automation"
APP_EXE = "sinx-automation.exe"
ICON_NAME = "icon.ico"
UNREG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SinXAutomation"
PUBLISHER = "Sin'X Team"
APP_VERSION = "1.3.0"


def is_silent():
    return any(a.lower() in ("/s", "/silent", "--silent", "-s") for a in sys.argv[1:])

def is_uninstall():
    return any(a.lower() in ("/uninstall", "--uninstall", "-u") for a in sys.argv[1:])

def resource_path(name):
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / name

def log(msg): print(f"  {msg}")
def log_ok(msg): print(f"  [OK] {msg}")
def log_err(msg): print(f"  [!!] {msg}")

def banner():
    print("=" * 58)
    print(f"  Sin'X Automation -- Enterprise Installer v{APP_VERSION}")
    print("=" * 58)
    print()

def create_shortcut(lnk, target, icon=None, workdir=None):
    icon_str = str(icon.resolve()) if icon and icon.exists() else ""
    work_str = str(workdir.resolve()) if workdir else str(target.parent.resolve())
    # Build PowerShell one-liner - avoid single quotes inside the command
    ps_lines = [
        "$ws=New-Object -ComObject WScript.Shell",
        f"$s=$ws.CreateShortcut(\"{lnk}\")",
        f"$s.TargetPath=\"{target.resolve()}\"",
        f"$s.WorkingDirectory=\"{work_str}\"",
    ]
    if icon_str:
        ps_lines.append(f"$s.IconLocation=\"{icon_str},0\"")
    ps_lines.append("$s.Save()")
    ps = ";".join(ps_lines)
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def reg_write(install_dir, uninst_path, icon=None):
    try:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNREG_KEY)
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(install_dir.resolve()))
        uninst_str = '"{}" /uninstall'.format(uninst_path.resolve())
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, uninst_str)
        winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ, uninst_str + " /S")
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        if icon and icon.exists():
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, str(icon.resolve()))
        winreg.CloseKey(k)
        return True
    except Exception as e:
        log_err("Registry gagal: {}".format(e)); return False

def reg_delete():
    try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNREG_KEY)
    except FileNotFoundError: pass
    except Exception as e: log_err("Hapus registry gagal: {}".format(e))


def do_uninstall():
    silent = is_silent()
    if not silent:
        banner(); log("Mode: UNINSTALL"); print()
        if input("  Yakin ingin menghapus? (Y/N, default N): ").strip().lower() != "y":
            log("Dibatalkan."); input("\n  Enter untuk keluar..."); return
    install_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "SinXAutomation"
    desktop = Path.home() / "Desktop"
    programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    for lnk in [desktop / (APP_NAME + ".lnk"), programs / (APP_NAME + ".lnk")]:
        if lnk.exists(): lnk.unlink(missing_ok=True); log_ok("Shortcut dihapus: " + lnk.name)
    if install_dir.exists(): shutil.rmtree(install_dir, ignore_errors=True); log_ok("Folder dihapus: " + str(install_dir))
    reg_delete(); log_ok("Registry dihapus.")
    if not silent: log_ok("Selesai."); input("\n  Enter untuk keluar...")


def do_install():
    silent = is_silent()
    if not silent:
        banner(); print("  Memasang " + APP_NAME + " ke komputer Anda."); print()

    src_exe = resource_path(APP_EXE)
    src_icon = resource_path(ICON_NAME)

    if not src_exe.exists():
        log_err("File tidak ditemukan: " + str(src_exe))
        if not silent: input("\n  Enter untuk keluar...")
        sys.exit(1)

    install_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinXAutomation"
    install_dir.mkdir(parents=True, exist_ok=True)
    log("[1/5] Install ke: " + str(install_dir))

    dest_exe = install_dir / APP_EXE
    shutil.copy2(src_exe, dest_exe)
    size_kb = dest_exe.stat().st_size // 1024
    log_ok("{} ({:,} KB) disalin.".format(dest_exe.name, size_kb))

    dest_icon = None
    if src_icon.exists():
        dest_icon = install_dir / ICON_NAME
        shutil.copy2(src_icon, dest_icon)
        log_ok("Icon disalin: " + dest_icon.name)

    uninst = install_dir / "install.exe"
    try:
        if getattr(sys, "frozen", False): shutil.copy2(Path(sys.executable), uninst)
    except Exception: pass

    log("[2/5] Shortcut Desktop...")
    dl = Path.home() / "Desktop" / (APP_NAME + ".lnk")
    create_shortcut(dl, dest_exe, icon=dest_icon, workdir=install_dir)
    log_ok("Desktop shortcut OK." if dl.exists() else "Desktop shortcut gagal (lanjut).")

    log("[3/5] Shortcut Start Menu...")
    pm = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    pm.mkdir(parents=True, exist_ok=True)
    pl = pm / (APP_NAME + ".lnk")
    create_shortcut(pl, dest_exe, icon=dest_icon, workdir=install_dir)
    log_ok("Start Menu shortcut OK." if pl.exists() else "Start Menu shortcut gagal (lanjut).")

    log("[4/5] Mendaftarkan ke Apps and Features...")
    if reg_write(install_dir, uninst, dest_icon):
        log_ok("Registry OK.")

    log("[5/5] Selesai!")
    if not silent:
        print(); print("  " + "=" * 50)
        print("  SUKSES! " + APP_NAME + " berhasil terpasang!")
        print("  " + "=" * 50); print()
        print("  Shortcut di Desktop sudah tersedia."); print()
        if input("  Buka " + APP_NAME + " sekarang? (Y/N, default Y): ").strip().lower() != "n":
            subprocess.Popen([str(dest_exe.resolve())], cwd=str(install_dir))
        input("\n  Enter untuk keluar...")
    else:
        subprocess.Popen([str(dest_exe.resolve())], cwd=str(install_dir))


if __name__ == "__main__":
    if is_uninstall():
        do_uninstall()
    else:
        do_install()
