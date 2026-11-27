#!/usr/bin/env python3
# Descripción: regenera automatizaciones.json con la última ejecución real de cada automatización.
# Uso:
#   En el NAS:  python3 /volume1/docker/opencode2/proyectos-generales/automatizaciones/update.py
#   En contenedor: python3 /workspace/proyectos-generales/automatizaciones/update.py
#   Cron NAS cada hora: 0 * * * * emlami python3 /volume1/docker/opencode2/proyectos-generales/automatizaciones/update.py >> /tmp/automatizaciones-update.log 2>&1
# Fecha: 2026-11-20 · Proyecto: proyectos-generales/automatizaciones
import json, os, re, sys, glob, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

def detect_base():
    # NAS o contenedor: el script vive dentro de la carpeta destino
    here = Path(__file__).resolve().parent
    # base repo: 3 niveles arriba de automatizaciones/ -> repo root?
    # automatizaciones/ está en proyectos-generales/automatizaciones/
    repo = here.parent.parent
    if (Path("/volume1/docker/opencode2/nas/.env")).exists():
        repo_nas = Path("/volume1/docker/opencode2")
        return repo_nas
    if (Path("/workspace/nas/.env")).exists():
        return Path("/workspace")
    return repo

BASE = detect_base()
OUT = Path(__file__).resolve().parent / "automatizaciones.json"
ENV_FILE = BASE / "nas" / ".env"

def load_env(p):
    d = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            d[k.strip()] = v
    except FileNotFoundError:
        pass
    return d

ENV = load_env(ENV_FILE)
N8N_USER = ENV.get("N8N_USER", "")
N8N_PASS = ENV.get("N8N_PASSWORD", "")
N8N_HOSTS = ["http://localhost:5678", "http://192.168.1.41:5678"]
if ENV.get("NAS_HOST"):
    N8N_HOSTS.insert(0, f"http://{ENV['NAS_HOST']}:5678")

def n8n_last():
    """Devuelve dict workflowId -> {lastRun, status, id}. Solo lectura."""
    out = {}
    for host in N8N_HOSTS:
        try:
            login = urllib.request.Request(
                host + "/rest/login",
                data=json.dumps({"emailOrLdapLoginId": N8N_USER, "password": N8N_PASS}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(login, timeout=10) as r:
                cookie = r.headers.get("Set-Cookie", "").split(";")[0]
            if not cookie:
                continue
            req = urllib.request.Request(host + "/rest/executions?limit=100", headers={"Cookie": cookie})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            for e in d.get("data", {}).get("results", []):
                wid = e.get("workflowId")
                if wid not in out:
                    out[wid] = {"lastRun": e.get("startedAt"), "status": e.get("status"), "execId": e.get("id")}
            if out:
                return out
        except Exception:
            continue
    return out

def mtime_iso(p):
    try:
        ts = Path(p).stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except FileNotFoundError:
        return None

def tail(path, n=30):
    try:
        with open(path, errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except FileNotFoundError:
        return ""

def main():
    n8n = n8n_last()

    def n8n_item(wid):
        e = n8n.get(wid)
        if not e:
            return None, None
        # n8n da UTC con Z; lo dejamos tal cual (el HTML lo muestra en local)
        return e["lastRun"], f"id {e['execId']} {e['status']}"

    # --- cron / logs (rutas en BASE) ---
    ofertas_log = BASE / "ofertas-ia-langgraph" / "logs" / "cron.log"
    modelos_log = BASE / "modelos-opencode-langgraph" / "logs" / "langgraph.log"
    diario_dir = BASE / "Inglés" / "Errores" / "diario"
    vikunja_log = Path("/home/emlami/vikunja-digest.log")
    pwd_log = Path("/home/emlami/opencode-password-sync.log")  # cron retirado 2026-11-20
    pwd_txt = BASE / "opencode-password.txt"
    gdrive_log = Path("/tmp/gdrive-refresh.log")
    plex_log = Path("/volume1/docker/plex-ingest/ingest.log")
    kanban_json = BASE / "proyectos-generales" / "kanban" / "kanban.json"

    # ofertas-ia: última línea con fecha del log, si no mtime
    t_ofertas = tail(ofertas_log, 40)
    m = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", t_ofertas)
    ofertas_last = None
    if m:
        try:
            ofertas_last = datetime.strptime(m[-1], "%Y-%m-%d %H:%M:%S").astimezone().isoformat(timespec="seconds")
        except ValueError:
            ofertas_last = mtime_iso(ofertas_log)
    else:
        ofertas_last = mtime_iso(ofertas_log)

    # modelos: último "OK YYYY-MM-DD"
    t_modelos = tail(modelos_log, 10)
    mm = re.findall(r"OK (\d{4}-\d{2}-\d{2})", t_modelos)
    modelos_last = None
    if mm:
        modelos_last = mm[-1] + "T07:00:00+01:00"

    # errores inglés: último YYYY-MM-DD.md del diario (ignora LEEME.md)
    ingles_last, ingles_det = None, ""
    try:
        files = sorted(f for f in glob.glob(str(diario_dir / "*.md")) if re.search(r"/\d{4}-\d{2}-\d{2}\.md$", f))
        if files:
            last = files[-1]
            ingles_last = mtime_iso(last)
            ingles_det = os.path.basename(last)
    except Exception:
        pass

    # conserva valores previos cuando el dato no existe en este entorno
    # (ej: /home/emlami/*.log no existe en el contenedor, sí en el NAS)
    prev = {}
    try:
        prev = {it.get("id"): it for it in json.loads(OUT.read_text()).get("items", [])}
    except Exception:
        pass

    def keep(id_, new_val):
        if new_val:
            return new_val
        return (prev.get(id_) or {}).get("lastRun")

    # vikunja: "2026-11-19 18:58:59 enviado"
    t_vik = tail(vikunja_log, 10)
    mv = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) enviado", t_vik)
    vik_last = None
    if mv:
        try:
            vik_last = datetime.strptime(mv[-1], "%Y-%m-%d %H:%M:%S").astimezone().isoformat(timespec="seconds")
        except ValueError:
            pass
    if not vik_last:
        vik_last = mtime_iso(vikunja_log)

    # docker / salud desde n8n
    docker_last, docker_det = n8n_item("0E35wJjMa740Cd2A")
    salud_last, salud_det = n8n_item("QnPcqWrGlfjM4NCd")

    # plex-ingest: estado real desde su log. El cron manda stdout a /dev/null,
    # pero el propio script escribe /volume1/docker/plex-ingest/ingest.log.
    t_plex = tail(plex_log, 200)
    mplex = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", t_plex)
    plex_last = mtime_iso(plex_log)
    plex_edad_min = None
    if mplex:
        try:
            plex_dt = datetime.strptime(mplex[-1], "%Y-%m-%d %H:%M:%S")
            plex_last = plex_dt.astimezone().isoformat(timespec="seconds")
            plex_edad_min = (datetime.now() - plex_dt).total_seconds() / 60
        except ValueError:
            pass
    # Sólo cuentan los errores de la última pasada (no los ya resueltos que
    # siguen dentro de las últimas 200 líneas).
    ultima_pasada = t_plex.rsplit("pasada:", 1)[-1]
    plex_errs = [l for l in ultima_pasada.splitlines() if "[ERROR]" in l]
    if not plex_last:
        plex_estado = "fallo"
        plex_det = "sin log legible en /volume1/docker/plex-ingest (¿cron parado?)"
    elif plex_edad_min is not None and plex_edad_min > 30:
        plex_estado = "fallo"
        plex_det = f"sin pasadas desde hace {int(plex_edad_min)} min (cron cada 10) · log ingest.log"
    else:
        plex_estado = "ok"
        plex_det = "modo link · log /volume1/docker/plex-ingest/ingest.log"
    if plex_errs and plex_estado == "ok":
        plex_estado = "fallo"
        plex_det += " · último error: " + plex_errs[-1].split("[ERROR]", 1)[-1].strip()[:90]

    ahora = datetime.now().astimezone().isoformat(timespec="seconds")
    kanban_last = keep("kanban-sync", mtime_iso(kanban_json))
    vik_last = keep("vikunja-digest", vik_last)
    ingles_last = keep("errores-diarios-ingles", ingles_last)
    ofertas_last = keep("ofertas-ia", ofertas_last)
    modelos_last = keep("modelos-opencode", modelos_last)
    # ofertas-ia: cadencia 4 d → estancada si >8 d sin ejecución real.
    # (Antes: "fallo" hardcoded si aparecía 2026-11-15; mentía tras cada run.)
    try:
        _of_dt = datetime.fromisoformat(ofertas_last) if ofertas_last else None
        _of_edad = ((datetime.now().astimezone() - _of_dt).total_seconds() / 86400
                    if _of_dt else None)
    except ValueError:
        _of_edad = None
    ofertas_estado = "ok" if _of_edad is not None and _of_edad <= 5 else "fallo"

    # newsletter-radar-tech: el sello solo se toca si el envío sale bien,
    # así que su mtime = último envío correcto. Estancada si >7 d (cadencia 6 d).
    news_dir = BASE / "proyectos-generales" / "newsletter-radar-tech"
    news_stamp = news_dir / "logs" / ".ultima-ejecucion"
    try:
        news_nums = sorted(news_dir.glob("numero-*.html"))
        news_ult = news_nums[-1].name if news_nums else "—"
    except Exception:
        news_ult = "—"
    news_last = keep("newsletter-radar-tech", mtime_iso(news_stamp))
    try:
        _nw_dt = datetime.fromisoformat(news_last) if news_last else None
        _nw_edad = ((datetime.now().astimezone() - _nw_dt).total_seconds() / 86400
                    if _nw_dt else None)
    except ValueError:
        _nw_edad = None
    news_estado = "ok" if _nw_edad is not None and _nw_edad <= 7 else "fallo"

    items = [
        {"id":"docker-auto-update","nombre":"Docker Auto-Update","tipo":"n8n","donde":"NAS Docker (n8n-n8n-1)","schedule":"cada 7 h","estado":"ok" if docker_last else "fallo","lastRun":keep("docker-auto-update", docker_last),"detalle":docker_det or "sin ejecuciones vía API"},
        {"id":"monitor-nas-salud","nombre":"Monitor NAS Salud","tipo":"n8n","donde":"NAS Docker (n8n-n8n-1)","schedule":"cada 6 h","estado":"ok" if salud_last else "fallo","lastRun":keep("monitor-nas-salud", salud_last),"detalle":(salud_det or "sin ejecuciones vía API") + " · doc nas/docs/n8n-monitor-nas-salud.md"},
        {"id":"errores-diarios-ingles","nombre":"Errores diarios de inglés","tipo":"cron","donde":"NAS cron → contenedor smanx_opencode-1","schedule":"23:55 diario","estado":"ok","lastRun":ingles_last,"detalle":f"{ingles_det} · log /home/emlami/errores-diarios.log"},
        {"id":"modelos-opencode","nombre":"Modelos IA OpenCode","tipo":"cron","donde":"NAS cron + LangGraph","schedule":"07:00, cada 14 días","estado":"ok","lastRun":modelos_last,"detalle":"chequeo diario, real cada 14 d · log modelos-opencode-langgraph/logs/langgraph.log"},
        {"id":"ofertas-ia","nombre":"Ofertas IA","tipo":"cron","donde":"NAS cron + LangGraph","schedule":"07:00 chequeo diario → cada 4 d","estado":ofertas_estado,"lastRun":ofertas_last,"detalle":"cron 0 7 * * * + cada-4-dias.sh · log ofertas-ia-langgraph/logs/cron.log"},
        {"id":"newsletter-radar-tech","nombre":"Newsletter Radar Tech","tipo":"cron","donde":"NAS cron","schedule":"07:05 chequeo diario → cada 6 d","estado":news_estado,"lastRun":news_last,"detalle":f"envía el numero-*.html más reciente (ahora {news_ult}) · cron /etc/cron.d/newsletter-radar + cada-6-dias.sh · log newsletter-radar-tech/logs/cron.log"},
        {"id":"plex-ingest","nombre":"Ingesta Plex","tipo":"cron","donde":"NAS cron","schedule":"cada 10 min","estado":plex_estado,"lastRun":keep("plex-ingest", plex_last),"detalle":plex_det},
        {"id":"gdrive-refresh","nombre":"Refresh token Google Drive","tipo":"cron","donde":"NAS cron","schedule":"cada 45 min","estado":"roto","lastRun":None,"detalle":"ruta /volume1/docker/opencode/... no existe · decisión 2026-11-15: no tocar · " + (tail(gdrive_log,1).strip()[:120] if tail(gdrive_log,1) else "")},
        {"id":"anki-push","nombre":"Push de mazos Anki","tipo":"manual","donde":"NAS manual","schedule":"manual","estado":"manual","lastRun":None,"detalle":"script nas/scripts/anki-push.sh · sin cron"},
        {"id":"backup-opencode","nombre":"Backup de opencode","tipo":"manual","donde":"NAS manual","schedule":"manual","estado":"manual","lastRun":None,"detalle":"script nas/scripts/backup-opencode.sh · pendiente decidir horario"},
        {"id":"kanban-sync","nombre":"Kanban auto-sync","tipo":"sync","donde":"contenedor static-tools :8081","schedule":"al guardar","estado":"ok","lastRun":kanban_last,"detalle":"PUT kanban/kanban.json"},
        {"id":"vikunja-digest","nombre":"Pendientes Vikunja","tipo":"cron","donde":"NAS cron → contenedor opencode","schedule":"08:00 días alternos","estado":"ok","lastRun":vik_last,"detalle":"log /home/emlami/vikunja-digest.log"},
        {"id":"opencode-password-file","nombre":"Contraseña opencode en .txt","tipo":"manual","donde":"NAS → contenedor opencode","schedule":"al rotar (manual)","estado":"manual","lastRun":keep("opencode-password-file", mtime_iso(pwd_txt)),"detalle":"sin cron desde 2026-11-20 (era cada minuto) · fecha = última vez que cambió la clave · script nas/scripts/rotar-password-opencode.sh (--sync) · doc nas/docs/opencode-password-txt.md"},
    ]

    data = {"generado": ahora, "items": items}
    tmp = str(OUT) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f"OK {OUT} {len(items)} items generado={ahora}")

if __name__ == "__main__":
    sys.exit(main())
