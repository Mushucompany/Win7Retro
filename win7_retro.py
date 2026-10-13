# -*- coding: utf-8 -*-
"""
Win7 Retro for Windows 11
GUI-помощник для превращения Windows 11 в стиль Windows 7.

Схема работы — "гид-оркестратор":
  * всё, что делается штатно (обои, курсоры, звуки, акценты, конфиг меню),
    применяется напрямую из программы;
  * третьи-сторонние инструменты (OpenShell, StartAllBack, патчер uxtheme)
    пользователь скачивает, программа находит и запускает их;
  * свои файлы (темы *.theme/*.msstyles, курсоры, звуки) пользователь
    прикладывает через кнопки "Выбрать файл", программа ставит их по месту;
  * вкладка "Откат" делает бэкап реестра и изменённых файлов.

Запуск:  python win7_retro.py
Нужен только Python 3 (tkinter входит в стандартную поставку на Windows).
"""

import os
import sys
import re
import json
import ctypes
import platform
import subprocess
import webbrowser
import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, Tk
import tkinter as tk

try:
    import tkinter.font as tkfont
except Exception:
    tkfont = None

APP_NAME = "Win7 Retro"
APP_VERSION = "1.0"
SETTINGS_PATH = Path.home() / ".win7retro_settings.json"

WINDIR = Path(os.environ.get("SystemRoot", r"C:\Windows"))
USERPROFILE = Path.home()
THEMES_DIR = WINDIR / "Resources" / "Themes"
MEDIA_DIR = WINDIR / "Media"
SHELL_GAMES = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"

# Известные пути к сторонним инструментам (программа ищет их, а не ставит сама)
KNOWN_TOOLS = {
    "OpenShell": [
        (USERPROFILE / "AppData" / "Local" / "Programs" / "Open-Shell" /
         "StartMenu.exe"),
        Path("C:/Program Files/Open-Shell/StartMenu.exe"),
        Path("C:/Program Files (x86)/Open-Shell/StartMenu.exe"),
    ],
    "StartAllBack": [
        Path("C:/Program Files/StartAllBack/StartAllBackCfg.exe"),
        Path("C:/Program Files (x86)/StartAllBack/StartAllBackCfg.exe"),
    ],
    "UltraUXThemePatcher": [
        USERPROFILE / "Desktop" / "UltraUXThemePatcher_4.4.5.exe",
        USERPROFILE / "Downloads" / "UltraUXThemePatcher_4.4.5.exe",
    ],
}

OFFICIAL_URLS = {
    "OpenShell": "https://github.com/Open-Shell/Open-Shell-Menu/releases",
    "StartAllBack": "https://www.startallback.com/",
    "UltraUXThemePatcher": "https://mhoefs.eu/software_uxtheme.php",
}

AERO_SAMPLE_NAMES = [
    "aero", "aerolite", "basic", "classic", "theme1", "theme2", "windows7",
]


def project_base() -> Path:
    """Папка, откуда взять ассеты — рядом с .exe или рядом со скриптом."""
    if getattr(sys, "frozen", False):  # запуск из PyInstaller .exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def assets_dirs() -> dict:
    """Ищет папки ассетов рядом с программой. Возвращает {тип: папка}."""
    base = project_base()
    result = {}
    # курсоры
    for cand in ("win7_cursors", "cursors", "Cursors"):
        p = base / cand
        if p.is_dir() and any(p.glob("*.cur")):
            result["cursors"] = p
            break
    # иконки для рабочего стола (файлы-значки)
    for cand in ("win7_assets", "icons", "Icons", "win7_icons"):
        p = base / cand
        if p.is_dir():
            result.setdefault("icons_dir", p)
    # звуки
    for cand in (r"win7_icons\sounds", "sounds", "Sounds", r"win7_assets\sounds"):
        p = base / cand
        if p.is_dir() and any(p.glob("*.wav")):
            result["sounds"] = p
            break
    return result


# ---------------------------------------------------------------- helpers ----
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(wait: bool = False) -> None:
    """Перезапускает текущий скрипт с правами администратора."""
    script = os.path.abspath(__file__)
    params = f'"{script}"'
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        if result <= 32:
            raise ctypes.WinError()
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Не удалось запросить права администратора:\n{exc}")


def reg_get(root: str, path: str, name: str) -> str | None:
    try:
        out = subprocess.run(
            ["reg", "query", f"{root}\\{path}", "/v", name],
            capture_output=True, text=True)
        m = re.search(r"\s+(REG_\w+)\s+(.*)$", out.stdout, re.M)
        return m.group(2).strip() if m else None
    except Exception:
        return None


def reg_set(root: str, path: str, name: str, value: str, kind: str = "REG_SZ") -> bool:
    try:
        subprocess.run(
            ["reg", "add", f"{root}\\{path}", "/v", name,
             "/t", kind, "/d", value, "/f"],
            capture_output=True, text=True, check=True)
        return True
    except Exception:
        return False


def reg_del(root: str, path: str, name: str) -> bool:
    try:
        subprocess.run(
            ["reg", "delete", f"{root}\\{path}", "/v", name, "/f"],
            capture_output=True, text=True, check=True)
        return True
    except Exception:
        return False


def backup_registry_keys(keys, backup_path: Path) -> str:
    """Экспорт нескольких веток реестра в .reg (используется для отката)."""
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for root, path in keys:
        try:
            out = subprocess.run(
                ["reg", "export", f"{root}\\{path}", backup_path,
                 "/y"], capture_output=True, text=True)
            if out.returncode == 0:
                parts.append(out.stdout)
        except Exception:
            continue
    merged = "\r\n".join(parts)
    if merged:
        backup_path.write_text(merged, encoding="utf-8")
        return str(backup_path)
    return ""


# ---------------------------------------------------------------- core UI ----
class Win7RetroApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION} — Windows 11 в стиле Windows 7")
        self.root.geometry("920x640")
        self.root.minsize(820, 560)

        # разделы, которые применяются пользователем
        self.checked = {
            "menu": tk.BooleanVar(value=True),
            "theme": tk.BooleanVar(value=True),
            "wallpaper": tk.BooleanVar(value=True),
            "cursors": tk.BooleanVar(value=True),
            "sounds": tk.BooleanVar(value=True),
            "icons": tk.BooleanVar(value=False),
        }
        self.status = {}

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self._load_settings()
        self._build_header()
        self._build_tabs()

    # ------------------------------------------------------------ plumbing ----
    def _load_settings(self) -> None:
        if SETTINGS_PATH.exists():
            try:
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                for key, var in self.checked.items():
                    var.set(data.get(key, var.get()))
            except Exception:
                pass

    def _save_settings(self) -> None:
        data = {k: v.get() for k, v in self.checked.items()}
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False),
                                 encoding="utf-8")

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        title = ttk.Label(header, text="Превращаем Windows 11 в Windows 7",
                          font=("Segoe UI", 15, "bold"))
        title.pack(side="left")
        if is_admin():
            badge = "Права администратора: есть"
            color = "#1e7d32"
        else:
            badge = "Права администратора: нет (часть операций недоступна)"
            color = "#c62828"
        adm = ttk.Label(header, text=badge, foreground=color)
        adm.pack(side="right")

        hint = ("Порядок: скачайте OpenShell + StartAllBack + патчер uxtheme, "
                "затем проходите по шагам. Начните с авто-проверки системы.")
        ttk.Label(self.root, text=hint, padding=(12, 0)).pack(anchor="w")

    @staticmethod
    def _make_scroll(parent):
        """Возвращает полотно со скроллом и его контейнер."""
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return outer, canvas, inner

    def _build_tabs(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=6)

        self.tab_check = ttk.Frame(nb, padding=10)
        self.tab_menu = ttk.Frame(nb, padding=10)
        self.tab_theme = ttk.Frame(nb, padding=10)
        self.tab_wall = ttk.Frame(nb, padding=10)
        self.tab_cur = ttk.Frame(nb, padding=10)
        self.tab_sound = ttk.Frame(nb, padding=10)
        self.tab_icons = ttk.Frame(nb, padding=10)
        self.tab_rollback = ttk.Frame(nb, padding=10)

        nb.add(self.tab_check, text="1. Проверка")
        nb.add(self.tab_menu, text="2. Меню Пуск")
        nb.add(self.tab_theme, text="3. Тема Aero")
        nb.add(self.tab_wall, text="4. Обои")
        nb.add(self.tab_cur, text="5. Курсоры")
        nb.add(self.tab_sound, text="6. Звуки")
        nb.add(self.tab_icons, text="7. Иконки")
        nb.add(self.tab_rollback, text="Откат")

        self._build_check_tab()
        self._build_menu_tab()
        self._build_theme_tab()
        self._build_wall_tab()
        self._build_cursor_tab()
        self._build_sound_tab()
        self._build_icons_tab()
        self._build_rollback_tab()

        btns = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Применить выбранное",
                   command=self.apply_selected).pack(side="right")
        ttk.Button(btns, text="Сохранить галочки",
                   command=self._save_settings).pack(side="right", padx=6)
        ttk.Button(btns, text="Скачать инструменты",
                   command=self.open_downloads).pack(side="left")
        ttk.Button(btns, text="⚙ Установить всё из проекта",
                   command=self.install_assets).pack(side="left", padx=6)

    # -------------------------------------------------------- tab 1: check ----
    def _build_check_tab(self) -> None:
        f = self.tab_check
        ttk.Label(f, text="Проверка системы и готовности компонентов",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

        self.check_text = tk.Text(f, height=16, wrap="word", state="disabled",
                                  font=("Consolas", 9))
        self.check_text.pack(fill="both", expand=True)
        ttk.Button(f, text="Выполнить авто-проверку",
                   command=self.run_checks).pack(anchor="w", pady=8)
        ttk.Label(
            f, wraplength=820,
            text="Проверка не изменяет систему, только читает состояние. "
                 "Вы увидите: версию Windows, права, наличие инструментов "
                 "и источники для скачивания.").pack(anchor="w")

    def _log(self, line: str) -> None:
        self.check_text.configure(state="normal")
        self.check_text.insert("end", line + "\n")
        self.check_text.configure(state="disabled")
        self.check_text.see("end")

    def run_checks(self) -> None:
        self.check_text.configure(state="normal")
        self.check_text.delete("1.0", "end")
        self.check_text.configure(state="disabled")

        self._log(f"== {APP_NAME} {APP_VERSION} — проверка системы ==")
        self._log(f"Дата: {datetime.date.today().isoformat()}")
        self._log(f"Python: {platform.python_version()}")
        self._log("")

        # версия Windows
        try:
            rel = platform.win32_ver()
            ver = f"{rel[0]} {rel[1]} build {rel[2]} {rel[3]}"
        except Exception:
            ver = "не определена"
        self._log(f"Windows: {ver}")
        self._log("Права администратора: " + ("ЕСТЬ" if is_admin() else "НЕТ"))

        # битность
        bit = platform.architecture()[0]
        self._log(f"Разрядность Python: {bit}")

        # проверка источников и инструментов
        self._log("")
        self._log("Проверка сторонних инструментов (скачиваются отдельно):")
        for name, paths in KNOWN_TOOLS.items():
            found = next((str(p) for p in paths if p.exists()), None)
            if found:
                self._log(f"  [OK] {name}: найден ({found})")
            else:
                self._log(f"  [--] {name}: НЕ найден")
                self._log(f"       скачать: {OFFICIAL_URLS.get(name, '')}")

        # проверка тем
        self._log("")
        aero = THEMES_DIR / "aero"
        if aero.exists():
            self._log("Тема aero.msstyles: найдена в системной папке тем")
        else:
            self._log("Тема aero.msstyles: не найдена (появится после установки "
                      "Win7-темы в папку тем)")
        ms = list(THEMES_DIR.glob("*.msstyles"))
        self._log(f"Количество непропатченых/сторонних тем в папке: {len(ms)}")

        # патч uxtheme
        self._log("")
        patched = self._check_uxtheme_patcher_ver()
        if patched:
            self._log("Патчер uxtheme: по-видимому применён (версия uxtheme.dll изменена)")
        else:
            self._log("Патчер uxtheme: НЕ применён — сторонние темы Windows не "
                      "поставятся, пока не пропатчишь uxtheme.dll")

        self._log("")
        self._log("Проверка завершена.")

    @staticmethod
    def _check_uxtheme_patcher_ver() -> bool:
        """Попытка выяснить, заменён ли uxtheme.dll (маркер патча)."""
        try:
            uxtheme = WINDIR / "System32" / "uxtheme.dll"
            if not uxtheme.exists():
                return False
            size = uxtheme.stat().st_size
            return size > 0
        except Exception:
            return False

    # ------------------------------------------------------- tab 2: menu -----
    def _build_menu_tab(self) -> None:
        f = self.tab_menu
        ttk.Label(f, text="Меню «Пуск» и панель задач в стиле Windows 7",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Применять классическое меню «Пуск» (OpenShell)",
                        variable=self.checked["menu"]).pack(anchor="w", pady=2)

        ttk.Label(f, wraplength=820, padding=(0, 6),
                  text="Для меню в стиле Windows 7 нужен стартовый лончер. "
                       "Открытая альтернатива — OpenShell (бесплатна), платная "
                       "с более точным видом — StartAllBack. Программа найдёт "
                       "установленный инструмент и запустит его конфигуратор.").pack(anchor="w")

        sub = ttk.Frame(f, padding=(0, 6))
        sub.pack(anchor="w", fill="x")
        ttk.Button(sub, text="Запустить OpenShell / StartAllBack",
                   command=self.launch_menu_tool).pack(side="left", padx=(0, 6))
        ttk.Button(sub, text="Скачать последний OpenShell (авто)",
                   command=self.download_openshell).pack(side="left", padx=6)
        ttk.Button(sub, text="Открыть страницу загрузки",
                   command=lambda: webbrowser.open(OFFICIAL_URLS["OpenShell"])).pack(side="left", padx=6)

        ttk.Label(f, wraplength=820, padding=(0, 10),
                  text="Совет: в OpenShell выберите стиль Start Menu → Windows 7. "
                       "Логотип/кнопку «Пуск» можно поменять на орбиту Windows 7 "
                       "через его настройки кнопки.").pack(anchor="w")

    def launch_menu_tool(self) -> None:
        for name in ("StartAllBack", "OpenShell"):
            found = next((str(p) for p in KNOWN_TOOLS[name] if p.exists()), None)
            if found:
                try:
                    os.startfile(found)  # noqa: S606 - локальный UI на Windows
                    return
                except Exception as exc:
                    messagebox.showerror(APP_NAME, str(exc))
                    return
        messagebox.showinfo(
            APP_NAME,
            "Инструмент для меню «Пуск» не найден. Откройте страницу загрузки "
            "OpenShell (или StartAllBack) и установите его.")

    def download_openshell(self) -> None:
        """Скачивает последний установщик OpenShell с GitHub (открытый проект)."""
        import urllib.request
        download_dir = Path.home() / "Downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._log_threadsafe("Запрашиваю последний релиз OpenShell с GitHub…")
            url = self._github_release_asset(
                "Open-Shell/Open-Shell-Menu",
                lambda a: a["name"].lower().startswith("openshellsetup"))
            if not url:
                messagebox.showinfo(
                    APP_NAME, "Установщик OpenShell не найден в последнем релизе.\n"
                              "Откройте страницу загрузки вручную.")
                return
            fname = url.rsplit("/", 1)[-1]
            dest = download_dir / fname
            self._log_threadsafe(f"Скачиваю: {url} → {dest}")
            urllib.request.urlretrieve(url, dest)
            self._log_threadsafe(f"Готово: {dest}")
            if messagebox.askyesno(APP_NAME,
                                   f"Установщик скачан: {dest}\nЗапустить установку OpenShell?"):
                os.startfile(str(dest))  # noqa: S606
        except Exception as exc:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось скачать OpenShell:\n{exc}\n\n"
                f"Скачайте вручную: {OFFICIAL_URLS['OpenShell']}")

    @staticmethod
    def _github_release_asset(repo: str, filt) -> str | None:
        """Возвращает browser_download_url первого подходящего asset последнего релиза."""
        import urllib.request, json
        api = (f"https://api.github.com/repos/{repo}/releases/latest")
        req = urllib.request.Request(api, headers={"User-Agent": "win7-retro"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        for asset in data.get("assets", []):
            if filt(asset):
                return asset.get("browser_download_url")
        return None

    def _log_threadsafe(self, line: str) -> None:
        """Пишет строку в текстовый лог проверки, если вкладка существует."""
        if hasattr(self, "check_text"):
            self._log(line)

    # ------------------------------------------------------- tab 3: theme ----
    def _build_theme_tab(self) -> None:
        f = self.tab_theme
        ttk.Label(f, text="Тема Aero в стиле Windows 7 (стекло, рамки окон)",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Применять тему Aero-стиль",
                        variable=self.checked["theme"]).pack(anchor="w", pady=2)

        ttk.Label(f, wraplength=820, padding=(0, 4),
                  text="Настоящая Aero-тема Windows 7 требует двух вещей:\n"
                       "1) патч uxtheme.dll (запустите UltraUXThemePatcher от "
                       "имени администратора) — иначе Windows откажется ставить "
                       "сторонние темы;\n"
                       "2) файл темы *.theme + *.msstyles в стиле Win7, который "
                       "нужно скачать отдельно (программа не может вшивать "
                       "бинарники Microsoft).").pack(anchor="w")

        row = ttk.Frame(f, padding=(0, 8))
        row.pack(anchor="w", fill="x")
        ttk.Button(row, text="Выбрать .theme файл",
                   command=self.pick_theme_file).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Выбрать .msstyles файл",
                   command=self.pick_msstyles_file).pack(side="left", padx=6)
        self.theme_file = tk.StringVar(value="")
        self.msstyles_file = tk.StringVar(value="")

        ttk.Button(row, text="Применить тему из выбранных файлов",
                   command=self.apply_theme_files).pack(side="left", padx=6)
        ttk.Button(row, text="Скачать патчер uxtheme",
                   command=lambda: webbrowser.open(OFFICIAL_URLS["UltraUXThemePatcher"])).pack(side="left", padx=6)

        ttk.Label(f, textvariable=self.theme_file, foreground="#444").pack(anchor="w")
        ttk.Label(f, textvariable=self.msstyles_file, foreground="#444").pack(anchor="w")

        ttk.Label(f, wraplength=820, padding=(0, 10),
                  text="Предупреждение: патч uxtheme.dll и сторонние темы — "
                       "на свой риск. После крупных обновлений Windows всё "
                       "слетает, патчер надо запускать заново. Откат изменённых "
                       "файлов — во вкладке «Откат».").pack(anchor="w")

    def pick_theme_file(self) -> None:
        fn = filedialog.askopenfilename(
            title="Выберите .theme файл",
            filetypes=[("Темы Windows", "*.theme"), ("Все файлы", "*.*")])
        if fn:
            self.theme_file.set(fn)

    def pick_msstyles_file(self) -> None:
        fn = filedialog.askopenfilename(
            title="Выберите .msstyles файл",
            filetypes=[("Стили оформления", "*.msstyles"), ("Все файлы", "*.*")])
        if fn:
            self.msstyles_file.set(fn)

    def apply_theme_files(self) -> None:
        if not is_admin():
            messagebox.showwarning(
                APP_NAME, "Установка темы требует прав администратора.\n"
                          "Запросить права?")
            return
        theme = self.theme_file.get()
        msstyles = self.msstyles_file.get()

        if msstyles:
            target = THEMES_DIR / Path(msstyles).name
            try:
                Path(msstyles).replace if False else None
                import shutil
                shutil.copy2(msstyles, target)
                messagebox.showinfo(APP_NAME, f"Файл стиля установлен:\n{target}")
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Не удалось скопировать стиль:\n{exc}")
                return
        elif theme:
            # копируем .theme и ставим через .theme
            target_themes = THEMES_DIR / Path(theme).name
            import shutil
            try:
                shutil.copy2(theme, target_themes)
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Не удалось установить тему:\n{exc}")
                return
            self._apply_theme_by_path(target_themes)
        else:
            messagebox.showinfo(APP_NAME, "Сначала выберите .theme или .msstyles файл.")

    def _apply_theme_by_path(self, theme_path: Path) -> None:
        """Применяем .theme: пишем в реестр текущую тему и показываем справку."""
        try:
            theme_name = theme_path.stem
            # системная установка темы
            subprocess.run(["rundll32.exe", "shell32.dll,Control_RunDLL",
                            "desk.cpl,,2", f"/Style:{theme_name}"],
                           capture_output=True, timeout=8)
            reg_set("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                    "ColorPrevalence", "0")
            messagebox.showinfo(
                APP_NAME,
                "Тема установлена в системную папку и применена.\n"
                "Если окно выбора темы не сменилось автоматически, откройте "
                "Параметры → Персонализация → Темы и выберите её вручную.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"Тема скопирована, но применение не удалось:\n{exc}")

    # ----------------------------------------------------- tab 4: wallpaper --
    def _build_wall_tab(self) -> None:
        f = self.tab_wall
        ttk.Label(f, text="Обои в стиле Windows 7",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Устанавливать выбранные обои",
                        variable=self.checked["wallpaper"]).pack(anchor="w", pady=2)

        row = ttk.Frame(f, padding=(0, 8))
        row.pack(anchor="w", fill="x")
        self.wall_var = tk.StringVar(value="")
        ttk.Button(row, text="Выбрать изображение...",
                   command=self.pick_wallpaper).pack(side="left")
        ttk.Label(f, textvariable=self.wall_var, foreground="#444").pack(anchor="w")

        ttk.Label(f, wraplength=820, padding=(0, 8),
                  text="Можно взять любую картинку (в т.ч. классические обои "
                       "«синий холм» Windows 7 из поиска по картинкам) — "
                       "физический файл выбираете вы.").pack(anchor="w")
        ttk.Button(f, text="Применить обои",
                   command=self.apply_wallpaper).pack(anchor="w")

    def pick_wallpaper(self) -> None:
        fn = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.bmp"),
                       ("Все файлы", "*.*")])
        if fn:
            self.wall_var.set(fn)

    def apply_wallpaper(self) -> None:
        path = self.wall_var.get()
        if not path or not Path(path).exists():
            messagebox.showwarning(APP_NAME, "Выберите изображение для обоев.")
            return
        # штатный способ: скрытый системный вызов SPI_SETDESKWALLPAPER
        SPI_SETDESKWALLPAPER = 20
        try:
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, path, 3)
            if not ok:
                raise ctypes.WinError()
            messagebox.showinfo(APP_NAME, "Обои установлены.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Не удалось установить обои:\n{exc}")

    # ----------------------------------------------------- tab 5: cursors ---
    def _build_cursor_tab(self) -> None:
        f = self.tab_cur
        ttk.Label(f, text="Схема курсоров Aero / Windows 7",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Применять схему курсоров из выбранной папки",
                        variable=self.checked["cursors"]).pack(anchor="w", pady=2)
        ttk.Label(f, wraplength=820, padding=(0, 4),
                  text="Скачайте набор курсоров Aero/Windows 7 (.cur и .ani) в "
                       "отдельную папку и укажите её через кнопку ниже. "
                       "Программа пропишет файлы в реестр вручную — это "
                       "безопаснее и работает без дополнительных утилит.").pack(anchor="w")

        row = ttk.Frame(f, padding=(0, 8))
        row.pack(anchor="w", fill="x")
        self.cursor_dir = tk.StringVar(value="")
        ttk.Button(row, text="Выбрать папку с курсорами...",
                   command=self.pick_cursor_dir).pack(side="left")
        ttk.Button(row, text="Применить курсоры", command=self.apply_cursors).pack(side="left", padx=6)
        ttk.Button(row, text="Использовать системную схему Aero (Win7)",
                   command=self.use_system_aero_cursors).pack(side="left", padx=6)
        ttk.Label(f, textvariable=self.cursor_dir, foreground="#444").pack(anchor="w")

        ttk.Label(f, wraplength=820, padding=(0, 8),
                  text="Ожидаемые имена файлов: arrow (указатель), help, wait, "
                       "cross, beam, pen, no, size_*, up, appstarting и т.д.\n"
                       "Если какой-то файл не найден, он пропускается.").pack(anchor="w")

    def pick_cursor_dir(self) -> None:
        d = filedialog.askdirectory(title="Папка с курсорами Aero")
        if d:
            self.cursor_dir.set(d)

    @staticmethod
    def _find_cursor(d: Path, *names) -> str:
        # ищем как есть, затем с системным префиксом aero_, затем с _l (крупный)
        candidates = []
        for n in names:
            candidates += [n, "aero_" + n]
        for n in candidates:
            for ext in (".cur", ".ani"):
                p = d / f"{n}{ext}"
                if p.exists():
                    return str(p)
        for n in names:
            for ext in (".cur", ".ani"):
                p = d / f"aero_{n}_l{ext}"
                if p.exists():
                    return str(p)
        return ""

    def use_system_aero_cursors(self) -> None:
        system_dir = WINDIR / "Cursors"
        if not system_dir.is_dir():
            messagebox.showwarning(APP_NAME, "Системная папка курсоров не найдена.")
            return
        self.cursor_dir.set(str(system_dir))
        if messagebox.askyesno(
                APP_NAME, "Применить системную схему курсоров Aero "
                          "(те, что в Windows 7) из папки Windows?"):
            self.apply_cursors()

    def apply_cursors(self) -> None:
        if not is_admin():
            messagebox.showwarning(APP_NAME, "Установка схемы курсоров требует прав администратора.")
            return
        d = Path(self.cursor_dir.get())
        if not d.is_dir():
            messagebox.showwarning(APP_NAME, "Выберите папку с курсорами.")
            return

        base = r"Software\Microsoft\Windows\CurrentVersion\Control Panel\Cursors"
        scheme = {
            "Arrow": self._find_cursor(d, "arrow", "Arrow"),
            "Help": self._find_cursor(d, "help", "Help"),
            "Wait": self._find_cursor(d, "wait", "AppStarting-inverse", "Wait", "aero_busy"),
            "Crosshair": self._find_cursor(d, "cross", "Cross"),
            "IBeam": self._find_cursor(d, "beam", "IBeam"),
            "No": self._find_cursor(d, "no", "No"),
            "SizeNS": self._find_cursor(d, "size_ns", "size_vert", "SizeNS"),
            "SizeWE": self._find_cursor(d, "size_we", "size_horiz", "SizeWE"),
            "SizeNWSE": self._find_cursor(d, "size_nwse", "SizeNWSE"),
            "SizeNESW": self._find_cursor(d, "size_nesw", "SizeNESW"),
            "Plus": self._find_cursor(d, "plus", "Pen"),
            "UpArrow": self._find_cursor(d, "up", "UpArrow"),
            "AppStarting": self._find_cursor(d, "appstarting", "AppStarting", "aero_working"),
            "Hand": self._find_cursor(d, "hand", "Link"),
        }
        applied = 0
        for name, path in scheme.items():
            if path:
                reg_set("HKCU", base, name, path)
                applied += 1
        # схема включена
        reg_set("HKCU", base, "", "Схема из Win7 Retro")
        messagebox.showinfo(APP_NAME, f"Применено курсоров: {applied}.\n"
                                      "Перезачтите систему или сеанс, чтобы изменения вступили в силу.")

    # ------------------------------------------------------- tab 6: sounds ---
    def _build_sound_tab(self) -> None:
        f = self.tab_sound
        ttk.Label(f, text="Системные звуки",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Применять схему звуков из выбранной папки",
                        variable=self.checked["sounds"]).pack(anchor="w", pady=2)
        ttk.Label(f, wraplength=820, padding=(0, 4),
                  text="Скачайте набор звуков Windows 7 (.wav) в отдельную "
                       "папку и укажите её. Программа пропишет события в схему "
                       "AppEvents (реестр) — это безопасно.").pack(anchor="w")

        row = ttk.Frame(f, padding=(0, 8))
        row.pack(anchor="w", fill="x")
        self.sound_dir = tk.StringVar(value="")
        ttk.Button(row, text="Выбрать папку со звуками...",
                   command=self.pick_sound_dir).pack(side="left")
        ttk.Button(row, text="Применить звуки", command=self.apply_sounds).pack(side="left", padx=6)
        ttk.Label(f, textvariable=self.sound_dir, foreground="#444").pack(anchor="w")

    def pick_sound_dir(self) -> None:
        d = filedialog.askdirectory(title="Папка со звуками Windows 7")
        if d:
            self.sound_dir.set(d)

    @staticmethod
    def _find_wav(d: Path, *names) -> str:
        for n in names:
            p = d / f"{n}.wav"
            if p.exists():
                return str(p)
        return ""

    def apply_sounds(self) -> None:
        if not is_admin():
            messagebox.showwarning(APP_NAME, "Установка схемы звуков требует прав администратора.")
            return
        d = Path(self.sound_dir.get())
        if not d.is_dir():
            messagebox.showwarning(APP_NAME, "Выберите папку со звуками.")
            return
        # события AppEvents: ключ -> список возможных имён файлов в пакете
        base = r"Software\Microsoft\Windows\CurrentVersion\Applets\AppEvents\Schemes\Apps\.Default"
        events = {
            "WindowsLogonSound": ("WindowsLogon", "Windows Logon Sound", "WindowsLogonSound"),
            "WindowsLogoffSound": ("WindowsLogoff", "Windows Logoff Sound", "WindowsLogoffSound"),
            "SystemStart": ("SystemStart", "Windows Startup", "Startup"),
            "SystemExit": ("SystemExit", "Windows Shutdown", "Shutdown"),
            "SystemExclamation": ("SystemExclamation", "Windows Exclamation", "Exclamation"),
            "SystemNotification": ("SystemNotification", "Windows Notify", "Notify", "Windows Balloon"),
            "Asterisk": ("Asterisk", "Windows Ding", "Ding"),
            "SystemHand": ("SystemHand", "Windows Error", "Error", "Windows Critical Stop"),
            "SystemQuestion": ("SystemQuestion", "Windows Exclamation", "Windows Ding"),
            "WindowsUAC": ("Windows User Account Control", "WindowsUAC", "UAC"),
            "DeviceConnect": ("Windows Hardware Insert", "DeviceConnect", "Hardware Insert"),
            "DeviceDisconnect": ("Windows Hardware Remove", "DeviceDisconnect", "Hardware Remove"),
            "SystemError": ("Windows Hardware Fail", "Windows Error", "Hardware Fail"),
        }
        # Схема звуков по умолчанию
        scheme_id = r"Software\Microsoft\Windows\CurrentVersion\Applets\AppEvents\Schemes\Apps\.Default"
        applied = 0
        for event_name, names in events.items():
            path = self._find_wav(d, *names)
            if path:
                node = f"{scheme_id}\\{event_name}\\.current"
                reg_set("HKCU", node, "", path)
                applied += 1
        messagebox.showinfo(APP_NAME, f"Найдено и прописано звуков: {applied}. "
                                      "Схема запуска будет использоваться после "
                                      "установки звуков Windows 7. Проверьте "
                                      "привязку в Настройках → Система → Звук.")

    def install_assets(self) -> None:
        """Авто-установка курсоров, иконок и звуков из папок рядом с программой."""
        dirs = assets_dirs()
        if not dirs:
            messagebox.showwarning(
                APP_NAME,
                "Папки ассетов не найдены рядом с программой.\n"
                "Ожидаются: win7_cursors/, win7_icons/ (иконки), "
                "win7_icons/sounds/ (звуки).\n"
                f"Поиск вёл в: {project_base()}")
            return
        report = []

        if d := dirs.get("cursors"):
            self.cursor_dir.set(str(d))
            report.append(f"【Курсоры】 {d}")
        if sd := dirs.get("sounds"):
            self.sound_dir.set(str(sd))
            report.append(f"【Звуки】 {sd}")
        ic = dirs.get("icons_dir")
        if ic:
            found = self._auto_fill_icons(ic)
            report.append(f"【Иконки】 {ic} (заполнено {found})")
        else:
            report.append("【Иконки】 папка не найдена")

        if not messagebox.askyesno(
                APP_NAME,
                "Найдены ассеты в проекте:\n" +
                "\n".join(f"- {r}" for r in report) +
                "\n\nПрименить их сейчас?\n"
                "(потребуются права администратора для звуков и курсоров)"):
            self.cursor_dir.set("")
            self.sound_dir.set("")
            return

        results = []
        # курсоры
        if dirs.get("cursors"):
            try:
                self.apply_cursors()
                results.append("курсоры: применено")
            except Exception as e:
                results.append(f"курсоры: ошибка ({e})")
        # звуки
        if dirs.get("sounds"):
            try:
                self.apply_sounds()
                results.append("звуки: применено")
            except Exception as e:
                results.append(f"звуки: ошибка ({e})")
        # иконки
        if ic and any(self.icon_vars[lbl].get() for lbl, _ in self.icon_mapping):
            try:
                self.apply_icons()
                results.append("иконки: применено")
            except Exception as e:
                results.append(f"иконки: ошибка ({e})")

        messagebox.showinfo(
            APP_NAME,
            "Результат установки:\n" + "\n".join(f"- {r}" for r in results) +
            "\n\nКурсоры и звуки применились; для иконок, если нужно, "
            "перезапустите Проводник.")

    def _auto_fill_icons(self, folder: Path) -> int:
        """Заполняет поля иконок рабочего стола из папки: ищет .ico по имени."""
        if not hasattr(self, "icon_mapping") or not hasattr(self, "icon_vars"):
            return 0
        # перечень кандидатов по каждой позиции
        wanted = {
            "Компьютер": ["computer", "Computer", "pc", "ПК"],
            "Корзина (полная)": ["recycle_full", "recyclefull", "recycle bin full", "full"],
            "Корзина (пустая)": ["recycle_empty", "recycleempty", "recycle bin empty", "empty"],
            "Сеть": ["network", "Network", "net", "Сеть"],
        }
        # соберём все .ico в папке (рекурсивно, по приоритету имени)
        found = 0
        for label, clsid in self.icon_mapping:
            candidates = wanted.get(label, [])
            picked = self._find_icon_by_name(folder, candidates)
            if picked:
                self.icon_vars[label].set(str(picked))
                found += 1
        return found

    @staticmethod
    def _find_icon_by_name(folder: Path, names) -> str:
        """Ищет .ico по подстроке имени (сначала точное)."""
        if not folder.is_dir():
            return ""
        icos = sorted(folder.rglob("*.ico"))
        # точное совпадение имени файла (слюдание)
        for n in names:
            for p in icos:
                if p.stem.lower() == n.lower():
                    return str(p)
        # частичное совпадение
        for n in names:
            nlow = n.lower()
            for p in icos:
                if nlow in p.stem.lower():
                    return str(p)
        # запасной: первые подходящие по типу
        return ""

    # ------------------------------------------------------ tab 7: icons ----
    def _build_icons_tab(self) -> None:
        f = self.tab_icons
        ttk.Label(f, text="Системные значки рабочего стола в стиле Windows 7",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(f, text="Применять выбранные системные значки",
                        variable=self.checked["icons"]).pack(anchor="w", pady=2)

        ttk.Label(f, wraplength=820, padding=(0, 4),
                  text="Выберите .ico файлы для значков «Компьютер», «Корзина» "
                       "и «Сеть» (Windows 7-стиль с планеты или классика Aero). "
                       "Программа пропишет их через реестр рабочего стола — "
                       "безопасно и обратимо.").pack(anchor="w")

        grid = ttk.Frame(f, padding=(0, 8))
        grid.pack(anchor="w", fill="x")
        self.icon_vars = {}
        self.icon_mapping = [
            ("Компьютер", "{20D04FE0-3AEA-1069-A2D8-08002B30309D}"),
            ("Корзина (полная)", "{645FF040-5081-101B-9F08-00AA002F954E}"),
            ("Корзина (пустая)", "{5EF4AF3A-C726-11D0-8C57-00C04FD7D535}"),
            ("Сеть", "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}"),
        ]
        for i, (label, _) in enumerate(self.icon_mapping):
            ttk.Label(grid, text=f"{label}:").grid(row=i, column=0,
                                                   sticky="e", padx=(0, 6), pady=3)
            var = tk.StringVar(value="")
            self.icon_vars[label] = var
            ttk.Entry(grid, textvariable=var, width=50).grid(
                row=i, column=1, sticky="we", pady=3)
            ttk.Button(grid, text="...",
                       command=lambda lb=label: self.pick_icon(lb)).grid(
                row=i, column=2, padx=4)
        grid.columnconfigure(1, weight=1)

        ttk.Button(f, text="Применить значки",
                   command=self.apply_icons).pack(anchor="w", pady=8)
        ttk.Label(f, wraplength=820,
                  text="После применения нужно перезапустить Проводник "
                       "(explorer.exe), чтобы значки обновились. Программа "
                       "предложит это сделать.").pack(anchor="w")

    def pick_icon(self, label: str) -> None:
        fn = filedialog.askopenfilename(
            title=f"Выберите значок для: {label}",
            filetypes=[("Иконки", "*.ico"), ("Все файлы", "*.*")])
        if fn:
            self.icon_vars[label].set(fn)

    def apply_icons(self) -> None:
        if not is_admin():
            messagebox.showwarning(
                APP_NAME, "Установка системных значков требует прав администратора.")
            return
        # Способ Windows 7: значение параметра Workspace под Desktop\NameSpace
        # для каждого CLSID хранит путь к значку "путь,индекс".
        base = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\Desktop\NameSpace")
        applied = 0
        for label, clsid in self.icon_mapping:
            path = self.icon_vars[label].get()
            if not path or not Path(path).exists():
                continue
            node = f"{base}\\{clsid}"
            reg_set("HKCU", node, "DefaultIcon", f"{path},0")
            applied += 1
        if applied:
            self._maybe_restart_explorer(
                f"Значков применено: {applied}. Перезапустить Проводник, "
                "чтобы изменения вступили в силу?")
            messagebox.showinfo(
                APP_NAME,
                f"Значков применено: {applied}.\n"
                "Если значки не обновились, перезапустите Проводник вручную "
                "или перезайдите в систему.")
        else:
            messagebox.showinfo(APP_NAME, "Ни один значок не выбран или файлы не существуют.")

    def _maybe_restart_explorer(self, question: str = "Перезапустить Проводник (explorer.exe)?") -> None:
        """Перезапускает оболочку, если у процесса есть права администратора."""
        if not is_admin():
            return
        if messagebox.askyesno(APP_NAME, question):
            try:
                subprocess.run(["taskkill", "/f", "/im", "explorer.exe"],
                               capture_output=True)
                subprocess.Popen(["explorer.exe"])
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Не удалось перезапустить проводник:\n{exc}")

    # ------------------------------------------------------ tab 8: rollback --
    def _build_rollback_tab(self) -> None:
        f = self.tab_rollback
        ttk.Label(f, text="Откат изменений (бэкап и восстановление)",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(f, wraplength=820,
                  text="Перед серьёзными изменениями сделайте бэкап реестра и "
                       "точку восстановления Windows. При проблемах можно "
                       "восстановиться из точки или через «Восстановление» "
                       "(Shift+Перезагрузка → Диагностика).").pack(anchor="w")

        row = ttk.Frame(f, padding=(0, 10))
        row.pack(anchor="w", fill="x")
        ttk.Button(row, text="Сделать бэкап реестра (темы/курсоры/звуки)",
                   command=self.make_registry_backup).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Создать точку восстановления системы",
                   command=self.make_restore_point).pack(side="left", padx=6)
        self.rollback_log = tk.StringVar(value="Бэкап ещё не создавался.")
        ttk.Label(f, textvariable=self.rollback_log, foreground="#444").pack(anchor="w", pady=4)

    def make_registry_backup(self) -> None:
        if not is_admin():
            messagebox.showwarning(APP_NAME, "Бэкап реестра требует прав администратора.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = USERPROFILE / f"win7retro_backup_{ts}.reg"
        keys = [
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes"),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Control Panel\Cursors"),
        ]
        res = backup_registry_keys(keys, backup_path)
        if res:
            self.rollback_log.set(f"Бэкап создан: {res}")
            messagebox.showinfo(APP_NAME, f"Бэкап реестра сохранён:\n{res}")
        else:
            self.rollback_log.set("Не удалось создать бэкап.")
            messagebox.showerror(APP_NAME, "Не удалось создать бэкап реестра.")

    @staticmethod
    def make_restore_point() -> None:
        if not is_admin():
            messagebox.showwarning(APP_NAME, "Создание точки восстановления требует прав администратора.")
            return
        try:
            # SystemRestore API через wmic (если доступен) либо PowerShell
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "Enable-ComputerRestore -Drive 'C:\\'; "
                 "Checkpoint-Computer -Description 'Win7 Retro before' "
                 "-RestorePointType 'APPLICATION_INSTALL'"],
                capture_output=True, timeout=180)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка создания точки:\n{exc}")
        messagebox.showinfo(APP_NAME, "Команда создания точки восстановления выполнена.\n"
                                      "Если точка не создалась, включите защиту "
                                      "системы вручную: Параметры → Система → "
                                      "Восстановление.")

    # --------------------------------------------------- main apply logic ----
    def apply_selected(self) -> None:
        """Прогоняет выбранные галочками шаги."""
        agreed = messagebox.askyesno(
            APP_NAME,
            "Вы собираетесь применить изменения к системе.\n"
            "Убедитесь, что сделали бэкап (вкладка «Откат»).\n"
            "Продолжить?")
        if not agreed:
            return

        report = []
        if self.checked["theme"].get():
            report.append("тема (файлы из вкладки «Тема Aero»)")
            self.apply_theme_files()
        if self.checked["wallpaper"].get():
            report.append("обои")
            self.apply_wallpaper()
        if self.checked["cursors"].get():
            report.append("курсоры")
            self.apply_cursors()
        if self.checked["sounds"].get():
            report.append("звуки")
            self.apply_sounds()
        if self.checked["icons"].get():
            report.append("системные значки")
            self.apply_icons()
        if self.checked["menu"].get():
            report.append("меню «Пуск»")
            self.launch_menu_tool()

        self._save_settings()
        messagebox.showinfo(
            APP_NAME,
            f"Выбранные шаги запущены:\n" + "\n".join(f"- {r}" for r in report) +
            "\n\nЧасть операций требует прав администратора. Если что-то не "
            "применилось, перезапустите программу от имени администратора.")

    def open_downloads(self) -> None:
        for url in OFFICIAL_URLS.values():
            webbrowser.open(url)


def main() -> None:
    root = Tk()
    try:
        Win7RetroApp(root)
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Ошибка запуска:\n{exc}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()