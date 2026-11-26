"""Discord VPN — usa a Proton VPN Free (WireGuard) SOMENTE no Discord. Windows."""
import ctypes
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import winreg
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from core_config import (ConfigError, DISCORD_EXES, PROXY_NAME, build_yaml,
                         parse_wireguard, safe_name)

APP = "DiscordVPN"
DATA = Path(os.environ.get("APPDATA", ".")) / APP
CORE_DIR = DATA / "core"
CORE_EXE_NAME = "discordvpn-core.exe"   # nome próprio: não mata o Clash/mihomo de outros apps
WG_CONF = DATA / "proton.conf"          # formato antigo (v1.0), migrado sozinho
CONFIGS_DIR = DATA / "configs"          # todos os .conf ficam aqui
SESSION_FILE = DATA / "proton-session.json"   # sessão da Proton (a senha NÃO é guardada)
HELPER_NAME = "proton-helper.exe"
VERSION = "2.0.0"
SETTINGS_FILE = DATA / "settings.json"
API_PORT = 9097
TASK_AUTOSTART = "DiscordVPN-Autostart"
TASK_LAUNCH = "DiscordVPN-LaunchDiscord"
TEST_URL = "https://www.gstatic.com/generate_204"
NO_WINDOW = 0x08000000

DEFAULTS = {"autostart": True, "launch_discord": True, "secret": "",
            "username": "", "routes_expire": 0, "route_names": {}}
COLORS = {"off": (140, 140, 140, 255), "connecting": (240, 180, 0, 255),
          "on": (46, 184, 92, 255), "error": (220, 60, 60, 255)}
LABELS = {"off": "desconectada", "connecting": "conectando…",
          "on": "ativa (só Discord)", "error": "erro"}

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ignora proxy do sistema


# ---------------------------------------------------------------- utilidades
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="ignore",
                          creationflags=NO_WINDOW, **kw)


def ps(script):
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])


def ps_q(s):
    return "'" + s.replace("'", "''") + "'"


def msgbox(text, title="Discord VPN", icon=0x40):
    ctypes.windll.user32.MessageBoxW(0, text, title, icon | 0x40000)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def bundled_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bin"
    return Path(__file__).resolve().parent / "bin"


def launch_cmd():
    """(executável, argumentos) para a tarefa de inicialização."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--autostart"
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), f'"{Path(__file__).resolve()}" --autostart'


def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.ellipse((20, 20, 44, 44), fill=(255, 255, 255, 235))
    return img


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
    except Exception:
        pass
    if not s["secret"]:
        s["secret"] = secrets.token_hex(16)
    save_settings(s)
    return s


def save_settings(s):
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), "utf-8")


def sync_bundled():
    """Copia núcleo, driver e helper da Proton para a pasta de dados."""
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    src = bundled_dir()
    for name, dst in (("mihomo.exe", CORE_EXE_NAME), ("wintun.dll", "wintun.dll"),
                      ("protonvpn-wg.exe", HELPER_NAME)):
        s_, d_ = src / name, CORE_DIR / dst
        if s_.exists() and (not d_.exists() or d_.stat().st_size != s_.stat().st_size):
            shutil.copy2(s_, d_)


def run_helper(args, stdin_obj=None, timeout=240):
    """Roda o helper de login da Proton. Retorna {"code": int, "json": dict}."""
    try:
        sync_bundled()
    except OSError:
        pass
    exe = CORE_DIR / HELPER_NAME
    if not exe.exists():
        return {"code": -1, "json": {"success": False, "error": "Helper da Proton não encontrado neste programa."}}
    kw = {"input": json.dumps(stdin_obj)} if stdin_obj is not None else {"stdin": subprocess.DEVNULL}
    try:
        p = subprocess.run([str(exe)] + args, capture_output=True, encoding="utf-8", errors="ignore",
                           timeout=timeout, creationflags=NO_WINDOW, cwd=str(CORE_DIR), **kw)
    except subprocess.TimeoutExpired:
        return {"code": -2, "json": {"success": False, "error": "Tempo esgotado falando com a Proton."}}
    j = {}
    for line in reversed((p.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                break
            except ValueError:
                continue
    return {"code": p.returncode, "json": j}


def explain_proton_error(j):
    """(categoria, mensagem em português) a partir do JSON de erro do helper."""
    code, err = str(j.get("code", "")), str(j.get("error", ""))
    if code == "TWO_FACTOR_REQUIRED":
        return "2FA", "Digite o código de 6 dígitos do seu app autenticador (2FA) e clique de novo."
    if code == "TWO_FACTOR_INVALID":
        return "2FA", "Código 2FA incorreto ou vencido. Digite o próximo código."
    if code == "INVALID_CREDENTIALS":
        return "CRED", "Usuário ou senha incorretos."
    if code == "APP_VERSION_UNSUPPORTED":
        return "APPVER", "A Proton não aceita mais esta versão do programa. Baixe a versão nova no GitHub."
    if j.get("captchaUrl") or "captcha" in (code + err).lower() or "9001" in code + err:
        return "CAPTCHA", ("A Proton pediu verificação anti-robô (captcha). Entre uma vez em "
                           "account.proton.me no navegador, aguarde uns minutos e tente de novo.")
    if code == "NETWORK_ERROR":
        return "NET", "Sem resposta da Proton agora. Confira a internet e tente de novo."
    return "ERR", (err[:220] or "Erro desconhecido ao falar com a Proton.")


# ------------------------------------------------------- tarefas do Windows
def set_autostart(enable: bool) -> bool:
    """Tarefa agendada no logon, com privilégio máximo (sem UAC) — roda antes do Discord."""
    if not enable:
        run(["schtasks", "/Delete", "/TN", TASK_AUTOSTART, "/F"])
        return True
    exe, args = launch_cmd()
    script = f"""
$u = "$env:USERDOMAIN\\$env:USERNAME"
$a = New-ScheduledTaskAction -Execute {ps_q(exe)} -Argument {ps_q(args)}
$t = New-ScheduledTaskTrigger -AtLogOn -User $u
$p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName {ps_q(TASK_AUTOSTART)} -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
"""
    return ps(script).returncode == 0


def discord_install():
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    for folder in ("Discord", "DiscordPTB", "DiscordCanary"):
        upd = base / folder / "Update.exe"
        if upd.exists():
            return upd, f"{folder}.exe"
    return None, None


def discord_running():
    out = run(["tasklist", "/FO", "CSV", "/NH"]).stdout.lower()
    return any(f'"{n.lower()}"' in out for n in DISCORD_EXES)


def kill_discord():
    for n in DISCORD_EXES:
        run(["taskkill", "/F", "/IM", n])


def disable_discord_autostart():
    """Remove a entrada do Discord no Iniciar do Windows: quem abre o Discord é este programa."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return
    with key:
        for name in ("Discord", "DiscordPTB", "DiscordCanary"):
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def launch_unelevated(update_exe: Path, exe_name: str):
    """Abre o Discord SEM privilégio de admin (o app é admin, o Discord não deve ser)."""
    script = f"""
$u = "$env:USERDOMAIN\\$env:USERNAME"
$a = New-ScheduledTaskAction -Execute {ps_q(str(update_exe))} -Argument {ps_q('--processStart ' + exe_name)}
$p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName {ps_q(TASK_LAUNCH)} -Action $a -Principal $p -Force | Out-Null
"""
    if ps(script).returncode == 0 and run(["schtasks", "/Run", "/TN", TASK_LAUNCH]).returncode == 0:
        return
    subprocess.Popen([str(update_exe), "--processStart", exe_name], creationflags=NO_WINDOW)


# ------------------------------------------------------------------- app
class App:
    def __init__(self):
        self.settings = load_settings()
        self.proc = None
        self.logf = None
        self.state = "off"
        self.msg = ""
        self.want = False
        self.lock = threading.Lock()
        self.quit_evt = threading.Event()
        self.icon = None
        self.proxy_names = []
        self.current = ""
        self.delays = {}
        self.watching = False
        self.watch_until = 0
        self.dialog_open = False

    # ---- estado / UI
    def status_text(self):
        if self.state == "on" and self.current:
            return f"{LABELS['on']} — {self.pretty(self.current)}"
        return LABELS[self.state] + (f" — {self.msg}" if self.msg and self.state == "error" else "")

    def pretty(self, name):
        return self.settings.get("route_names", {}).get(name, name)

    def notify(self, text):
        try:
            if self.icon:
                self.icon.notify(text, "Discord VPN")
        except Exception:
            pass

    def set_state(self, st, msg=""):
        self.state, self.msg = st, msg
        if self.icon:
            try:
                self.icon.icon = make_icon(COLORS[st])
                self.icon.title = f"Discord VPN — {self.status_text()}"[:127]
                self.icon.update_menu()
            except Exception:
                pass
        if msg:
            self.notify(msg)

    # ---- API do núcleo
    def api(self, path, timeout=6, method="GET", body=None):
        headers = {"Authorization": f"Bearer {self.settings['secret']}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}{path}", data=data,
                                     headers=headers, method=method)
        with OPENER.open(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}

    def tunnel_delay(self):
        q = urllib.parse.quote(TEST_URL, safe="")
        return self.api(f"/proxies/{PROXY_NAME}/delay?url={q}&timeout=5000", 9).get("delay", 0)

    def probe_all(self):
        """Mede a latência de cada servidor, um de cada vez."""
        q = urllib.parse.quote(TEST_URL, safe="")
        res = {}
        for name in self.proxy_names:
            try:
                d = self.api(f"/proxies/{urllib.parse.quote(name)}/delay?url={q}&timeout=4000", 7).get("delay", 0)
                if d > 0:
                    res[name] = d
            except Exception:
                pass
        return res

    def pick_best(self):
        """Escolhe o servidor de menor latência para este PC e passa o Discord para ele."""
        res = self.probe_all()
        self.delays = res
        if not res:
            return None
        best = min(res, key=res.get)
        self.api(f"/proxies/{PROXY_NAME}", 5, method="PUT", body={"name": best})
        self.current = best
        return best

    # ---- núcleo (mihomo)
    def _start_core(self, wgs):
        CORE_DIR.mkdir(parents=True, exist_ok=True)
        self._stop_core()
        run(["taskkill", "/F", "/IM", CORE_EXE_NAME])
        sync_bundled()
        cfg = CORE_DIR / "config.yaml"
        cfg.write_text(build_yaml(wgs, self.settings["secret"], API_PORT), "utf-8")
        self.logf = open(CORE_DIR / "core.log", "wb")
        self.proc = subprocess.Popen(
            [str(CORE_DIR / CORE_EXE_NAME), "-d", str(CORE_DIR), "-f", str(cfg)],
            cwd=str(CORE_DIR), stdout=self.logf, stderr=self.logf, creationflags=NO_WINDOW)

    def _stop_core(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except Exception:
                run(["taskkill", "/F", "/PID", str(p.pid)])
        if self.logf:
            try:
                self.logf.close()
            except Exception:
                pass
            self.logf = None

    def _wait_ready(self, timeout=90):
        end = time.time() + timeout
        while time.time() < end and self.want:
            if self.proc is None or self.proc.poll() is not None:
                return False
            try:
                self.api("/version", 2)
            except Exception:
                time.sleep(2)
                continue
            if self.pick_best():
                return True
            time.sleep(2)
        return False

    # ---- conectar / desconectar
    def connect(self, relaunch=True):
        self.want = True
        threading.Thread(target=self._connect, args=(relaunch,), daemon=True).start()

    def _connect(self, relaunch):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.state == "on":
                return
            if self.settings.get("username") and SESSION_FILE.exists() and \
                    (self.routes_stale() or not self.config_files()):
                self.set_state("connecting")
                ok, key, msg = self.renew_routes()
                if not ok:
                    self.notify(f"Não consegui renovar as rotas da Proton: {msg}")
            if not self.config_files():
                self.set_state("off")
                self.first_run_prompt()
                return
            self.set_state("connecting")
            if self.settings["launch_discord"]:
                disable_discord_autostart()
            try:
                self._start_core(self.load_configs())
            except Exception as e:
                self.set_state("error", str(e))
                return
            if self._wait_ready():
                self.set_state("on")
                self.notify(f"VPN ativa — Discord via {self.pretty(self.current)}.")
                if self.settings["launch_discord"] and relaunch:
                    self.launch_discord(restart=True)
            else:
                self._stop_core()
                if self.want:
                    self.set_state("error", "Não consegui conectar. Veja core.log em %APPDATA%\\DiscordVPN\\core")
                else:
                    self.set_state("off")
        finally:
            self.lock.release()

    def disconnect(self, quiet=False):
        self.want = False
        self._stop_core()
        self.set_state("off")
        if not quiet:
            self.notify("VPN desligada. O Discord agora usa sua conexão normal.")

    def launch_discord(self, restart=False):
        if self.state != "on":
            self.notify("Conecte a VPN antes de abrir o Discord.")
            return
        upd, exe = discord_install()
        if not upd:
            self.notify("Discord não encontrado.")
            return
        if discord_running():
            if not restart:
                return
            kill_discord()      # conexões abertas antes da VPN precisam ser refeitas
            time.sleep(2)
        launch_unelevated(upd, exe)

    # ---- monitor
    def monitor(self):
        fails, last_renew = 0, 0.0
        while not self.quit_evt.wait(10):
            if self.state == "on" and self.want and time.time() - last_renew > 3600:
                last_renew = time.time()
                if self.settings.get("username") and self.routes_stale():
                    ok, key, msg = self.renew_routes()
                    if ok:
                        self.notify("Rotas da Proton renovadas. Reconectando…")
                        self.disconnect(quiet=True)
                        self._wait_idle()
                        self.connect(relaunch=False)
                    else:
                        self.notify(f"Não consegui renovar as rotas: {msg}")
                    continue
            if self.state != "on" or not self.want:
                fails = 0
                continue
            dead = self.proc is None or self.proc.poll() is not None
            if not dead:
                try:
                    self.tunnel_delay()
                    fails = 0
                    continue
                except Exception:
                    fails += 1
            if dead or fails >= 3:
                fails = 0
                if not dead and len(self.proxy_names) > 1 and self.pick_best():
                    self.set_state("on")
                    self.notify(f"Servidor trocado para {self.pretty(self.current)}.")
                    continue
                self._stop_core()
                self.set_state("error", "VPN caiu — reconectando (Discord fica sem rede, sem vazar IP)")
                self.connect(relaunch=False)

    # ---- diagnóstico
    def diagnose(self):
        def work():
            try:
                conns = self.api("/connections")["connections"]
            except Exception:
                msgbox("A VPN não está ativa.", icon=0x30)
                return
            mine = [c for c in conns if "discord" in
                    (c["metadata"].get("process", "") + c["metadata"].get("processPath", "")).lower()]
            via = [c for c in mine if "DIRECT" not in c.get("chains", ["DIRECT"])]
            out = [c for c in mine if "DIRECT" in c.get("chains", ["DIRECT"])]
            text = (f"Conexões do Discord agora: {len(mine)}\n"
                    f"  • pela VPN: {len(via)}\n  • diretas (fora da VPN): {len(out)}")
            if out:
                dests = sorted({f"{c['metadata'].get('destinationIP', '?')}:{c['metadata'].get('destinationPort', '')}"
                                for c in out})[:6]
                text += "\n\nDiretas:\n" + "\n".join(dests)
            msgbox(text)
        threading.Thread(target=work, daemon=True).start()

    # ---- configs (.conf)
    def config_files(self):
        if WG_CONF.exists() and not any(CONFIGS_DIR.glob("*.conf")):   # migra da v1.0
            CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(WG_CONF), str(CONFIGS_DIR / "proton.conf"))
        return sorted(CONFIGS_DIR.glob("*.conf"))

    def load_configs(self):
        used, wgs = set(), []
        for f in self.config_files():
            try:
                wg = parse_wireguard(f.read_text("utf-8-sig"))
            except (ConfigError, OSError, UnicodeDecodeError):
                continue
            wg["name"] = safe_name(f.stem, used)
            wgs.append(wg)
        if not wgs:
            raise ConfigError("Nenhum .conf válido. Use 'Adicionar .conf'.")
        self.proxy_names = [w["name"] for w in wgs]
        return wgs

    def _wait_idle(self, timeout=15):
        end = time.time() + timeout
        while self.lock.locked() and time.time() < end:
            time.sleep(0.3)

    def add_configs(self):
        def work():
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            paths = filedialog.askopenfilenames(
                title="Selecione um ou mais .conf WireGuard da Proton VPN",
                filetypes=[("WireGuard", "*.conf"), ("Todos", "*.*")])
            root.destroy()
            if not paths:
                return
            CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            ok, bad = 0, []
            for p in paths:
                try:
                    text = Path(p).read_text("utf-8-sig")
                    parse_wireguard(text)
                except (ConfigError, OSError, UnicodeDecodeError) as e:
                    bad.append(f"{Path(p).name}: {e}")
                    continue
                (CONFIGS_DIR / (Path(p).stem + ".conf")).write_text(text, "utf-8")
                ok += 1
            if bad:
                msgbox("Não consegui usar:\n" + "\n".join(bad), icon=0x10)
            if ok:
                if self.settings["autostart"]:
                    set_autostart(True)
                self.disconnect(quiet=True)
                self._wait_idle()
                self.connect()
        threading.Thread(target=work, daemon=True).start()

    # ---- login na Proton (helper)
    def routes_stale(self):
        exp = self.settings.get("routes_expire", 0)
        return bool(exp) and time.time() > exp - 36 * 3600

    def proton_login(self, username, password, code):
        r = run_helper(["-username", username, "-session-file", str(SESSION_FILE),
                        "-login-only", "-json", "-stdin-secrets"],
                       {"password": password, "twoFactorCode": code, "humanVerificationToken": ""},
                       timeout=90)
        if r["code"] != 0 or r["json"].get("success") is False:
            key, msg = explain_proton_error(r["json"])
            return False, key, msg
        self.settings["username"] = username
        save_settings(self.settings)
        return self.renew_routes()

    def renew_routes(self):
        """Gera os melhores servidores Free (validados por ping) usando a sessão salva."""
        u = self.settings.get("username", "")
        if not u:
            return False, "NOACC", "Faça login na Proton."
        tmp = DATA / "routes_new"
        last = (False, "ERR", "Não consegui gerar as rotas.")
        for n in (3, 2, 1):
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            r = run_helper(["-username", u, "-session-file", str(SESSION_FILE), "-route-pool",
                            "-route-pool-size", str(n), "-route-pool-output-dir", str(tmp),
                            "-json", "-free-only", "-auto-ping"], timeout=240)
            j = r["json"]
            files = sorted(tmp.glob("route-*.conf"))
            if r["code"] == 0 and j.get("success") and files:
                CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
                for old in CONFIGS_DIR.glob("route-*.conf"):
                    old.unlink(missing_ok=True)
                for f in files:
                    shutil.move(str(f), str(CONFIGS_DIR / f.name))
                names = {}
                for x in j.get("routes", []):
                    stem = Path(str(x.get("confFile", ""))).stem
                    names[stem] = f"{x.get('server', stem)} ({x.get('country', '?')}, {x.get('pingMs', '?')} ms)"
                exp = float(j.get("expiresAt") or (time.time() + 6 * 86400))
                if exp > 1e11:
                    exp /= 1000
                self.settings["route_names"] = names
                self.settings["routes_expire"] = int(exp)
                save_settings(self.settings)
                shutil.rmtree(tmp, ignore_errors=True)
                return True, "OK", f"{len(files)} rota(s) gerada(s)."
            key, msg = explain_proton_error(j)
            last = (False, key, msg)
            if "validated" not in str(j.get("error", "")):      # não é falta de rotas: não adianta repetir
                break
        shutil.rmtree(tmp, ignore_errors=True)
        return last

    def refresh_routes(self):
        def work():
            if not self.settings.get("username") or not SESSION_FILE.exists():
                self.login_dialog()
                return
            self.notify("Procurando os melhores servidores Free…")
            ok, key, msg = self.renew_routes()
            if not ok:
                if key in ("CRED", "NOACC") or "session" in msg.lower() or "sess" in msg.lower():
                    self.login_dialog()
                msgbox(msg, icon=0x30)
                return
            self.disconnect(quiet=True)
            self._wait_idle()
            self.connect()
        threading.Thread(target=work, daemon=True).start()

    def logout_proton(self):
        self.disconnect(quiet=True)
        self._wait_idle()
        SESSION_FILE.unlink(missing_ok=True)
        for f in CONFIGS_DIR.glob("route-*.conf"):
            f.unlink(missing_ok=True)
        self.settings.update({"username": "", "routes_expire": 0, "route_names": {}})
        save_settings(self.settings)
        self.notify("Saí da conta Proton neste PC.")

    def login_dialog(self):
        if self.dialog_open:
            return
        self.dialog_open = True

        def work():
            try:
                import tkinter as tk
                from tkinter import ttk
                q = queue.Queue()
                root = tk.Tk()
                root.title("Discord VPN — Entrar na Proton")
                root.attributes("-topmost", True)
                root.resizable(False, False)
                f = ttk.Frame(root, padding=16)
                f.grid()
                ttk.Label(f, text="Entre com sua conta Proton (Free).\nSua senha não é salva neste PC.",
                          wraplength=340).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="w")
                user, pw, code = tk.StringVar(value=self.settings.get("username", "")), tk.StringVar(), tk.StringVar()
                ttk.Label(f, text="Usuário ou e-mail").grid(row=1, column=0, sticky="w")
                ttk.Entry(f, textvariable=user, width=34).grid(row=1, column=1, pady=3)
                ttk.Label(f, text="Senha").grid(row=2, column=0, sticky="w")
                ttk.Entry(f, textvariable=pw, show="*", width=34).grid(row=2, column=1, pady=3)
                ttk.Label(f, text="Código 2FA (se tiver)").grid(row=3, column=0, sticky="w")
                ttk.Entry(f, textvariable=code, width=34).grid(row=3, column=1, pady=3)
                status = tk.StringVar()
                ttk.Label(f, textvariable=status, wraplength=340, foreground="#b00").grid(
                    row=4, column=0, columnspan=2, pady=6, sticky="w")
                btn = ttk.Button(f, text="Entrar e escolher o melhor servidor")
                btn.grid(row=5, column=0, columnspan=2, sticky="ew")
                ttk.Button(f, text="Prefiro importar um .conf manualmente",
                           command=lambda: (root.destroy(), self.add_configs())).grid(
                    row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))

                def submit(event=None):
                    u, p, c = user.get().strip(), pw.get(), code.get().strip()
                    if not u or not p:
                        status.set("Preencha usuário e senha.")
                        return
                    btn.state(["disabled"])
                    status.set("Entrando e medindo os servidores… (1 a 2 minutos)")
                    threading.Thread(target=lambda: q.put(self.proton_login(u, p, c)), daemon=True).start()

                def poll():
                    try:
                        ok, key, msg = q.get_nowait()
                    except queue.Empty:
                        root.after(300, poll)
                        return
                    if ok:
                        pw.set("")
                        root.destroy()
                        if self.settings["autostart"]:
                            set_autostart(True)
                        self.disconnect(quiet=True)
                        self._wait_idle()
                        self.connect()
                        return
                    btn.state(["!disabled"])
                    status.set(msg)
                    if key == "CRED":
                        pw.set("")

                btn.configure(command=submit)
                root.bind("<Return>", submit)
                root.after(300, poll)
                root.mainloop()
            finally:
                self.dialog_open = False
        threading.Thread(target=work, daemon=True).start()

    # ---- assistente: importa sozinho os .conf baixados da Proton
    def first_run_prompt(self):
        self.login_dialog()

    def start_assistant(self):
        import webbrowser
        self.watch_until = time.time() + 900          # observa a pasta Downloads por 15 min
        if not self.watching:
            self.watching = True
            threading.Thread(target=self._watch_downloads, daemon=True).start()
        webbrowser.open("https://account.protonvpn.com/downloads")
        self.notify("Crie e baixe 3 configs WireGuard (Windows, servidores Free). Eu importo sozinho.")

    def _already_have(self, wg):
        for f in CONFIGS_DIR.glob("*.conf"):
            try:
                o = parse_wireguard(f.read_text("utf-8-sig"))
            except (ConfigError, OSError, UnicodeDecodeError):
                continue
            if o["private_key"] == wg["private_key"] and o["server"] == wg["server"]:
                return True
        return False

    def _watch_downloads(self):
        folder = Path(os.environ.get("USERPROFILE", "")) / "Downloads"
        start, done, added, last_add = time.time(), set(), 0, 0.0
        while not self.quit_evt.wait(3) and time.time() < self.watch_until:
            try:
                for f in folder.glob("*.conf"):
                    mt = f.stat().st_mtime
                    if (f.name, mt) in done or mt < start - 600:
                        continue
                    done.add((f.name, mt))
                    try:
                        text = f.read_text("utf-8-sig")
                        wg = parse_wireguard(text)
                    except (ConfigError, OSError, UnicodeDecodeError):
                        continue
                    if self._already_have(wg):
                        continue
                    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
                    (CONFIGS_DIR / (f.stem + ".conf")).write_text(text, "utf-8")
                    added, last_add = added + 1, time.time()
                if added and time.time() - last_add > 8:     # espera terminar os downloads
                    self.notify(f"{added} servidor(es) importado(s). Conectando…")
                    added = 0
                    if self.settings["autostart"]:
                        set_autostart(True)
                    self.disconnect(quiet=True)
                    self._wait_idle()
                    self.connect()
            except Exception:
                pass
        self.watching = False

    def open_configs_folder(self):
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(CONFIGS_DIR)

    def test_servers(self):
        def work():
            if self.state != "on":
                msgbox("Conecte a VPN primeiro.", icon=0x30)
                return
            best = self.pick_best()
            if not best:
                msgbox("Nenhum servidor respondeu.", icon=0x30)
                return
            lines = [f"{'→' if n == best else '   '} {self.pretty(n)}: {d} ms"
                     for n, d in sorted(self.delays.items(), key=lambda x: x[1])]
            text = "Latência até cada servidor (menor = melhor):\n\n" + "\n".join(lines)
            fail = [n for n in self.proxy_names if n not in self.delays]
            if fail:
                text += "\n\nSem resposta: " + ", ".join(self.pretty(n) for n in fail)
            msgbox(text + f"\n\nUsando agora: {self.pretty(best)}")
            self.set_state("on")
        threading.Thread(target=work, daemon=True).start()

    # ---- bandeja
    def toggle(self, key):
        def action(icon, item):
            self.settings[key] = not self.settings[key]
            save_settings(self.settings)
            if key == "autostart":
                threading.Thread(target=set_autostart, args=(self.settings[key],), daemon=True).start()
            icon.update_menu()
        return action

    def quit(self, icon, item):
        self.quit_evt.set()
        self.want = False
        self._stop_core()
        icon.stop()

    def build_menu(self):
        M, I = pystray.MenuItem, pystray.Menu
        return I(
            M(f"Discord VPN v{VERSION}", None, enabled=False),
            M(lambda item: f"Status: {self.status_text()}", None, enabled=False),
            M("Conectar", lambda icon, item: self.connect(),
              visible=lambda item: self.state in ("off", "error")),
            M("Desconectar", lambda icon, item: self.disconnect(),
              visible=lambda item: self.state in ("on", "connecting")),
            M("Abrir Discord", lambda icon, item: threading.Thread(
                target=self.launch_discord, daemon=True).start()),
            M("Diagnóstico (conexões do Discord)", lambda icon, item: self.diagnose()),
            I.SEPARATOR,
            M("Entrar na Proton (login)…", lambda icon, item: self.login_dialog()),
            M("Atualizar rotas (melhores servidores Free)", lambda icon, item: self.refresh_routes()),
            M("Testar servidores e usar o melhor", lambda icon, item: self.test_servers()),
            M("Mais opções", I(
                M("Adicionar .conf manualmente…", lambda icon, item: self.add_configs()),
                M("Baixar .conf da Proton (assistente)", lambda icon, item: self.start_assistant()),
                M("Abrir pasta dos .conf", lambda icon, item: self.open_configs_folder()),
                M("Sair da conta Proton neste PC", lambda icon, item: self.logout_proton()),
            )),
            M("Iniciar com o Windows", self.toggle("autostart"),
              checked=lambda item: self.settings["autostart"]),
            M("Este programa abre o Discord após a VPN", self.toggle("launch_discord"),
              checked=lambda item: self.settings["launch_discord"]),
            I.SEPARATOR,
            M("Sair", self.quit),
        )

    def _setup(self, icon):
        icon.visible = True
        threading.Thread(target=self.monitor, daemon=True).start()
        if self.config_files():
            self.connect()
            if self.settings["autostart"] and "--autostart" not in sys.argv:
                threading.Thread(target=set_autostart, args=(True,), daemon=True).start()
        else:
            self.first_run_prompt()

    def run(self):
        self.icon = pystray.Icon(APP, make_icon(COLORS["off"]), "Discord VPN", self.build_menu())
        self.icon.run(setup=self._setup)


def main():
    if not is_admin():  # necessário para criar o adaptador de rede (TUN)
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        if not getattr(sys, "frozen", False):
            params = f'"{Path(__file__).resolve()}" {params}'
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\DiscordVPN_single_instance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # já está rodando
        return
    DATA.mkdir(parents=True, exist_ok=True)
    App().run()


if __name__ == "__main__":
    main()
