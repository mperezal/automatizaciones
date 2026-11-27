# Automatizaciones — dashboard de control

> Fecha: 2026-11-20 · Fuente de verdad: `INVENTARIO.md` §2 (12 automatizaciones visibles; los 2 workflows n8n apagados se ocultan por decisión 2026-11-20).

Dashboard estilo kanban que muestra **qué automatizaciones hay y cuándo corrieron por última vez**, con **actualización cada hora**.

## Archivos

| Archivo | Qué es |
|---|---|
| `automatizaciones.html` | La app (tabla, filtro, auto-refresh cada hora) |
| `automatizaciones.json` | El estado: 12 items + `generado` |
| `update.py` | Regenera el JSON (n8n API + logs NAS) |
| `README.md` | Este doc |

## Cómo funciona

- Al abrir, `automatizaciones.html` hace `GET automatizaciones.json` y pinta la tabla.
- La propia página **se refresca sola cada hora** (`setInterval` 3600 s + cuenta atrás) sin recargar.
- El JSON lo regenera `update.py` **cada hora en el NAS** vía `/etc/cron.d/automatizaciones-dashboard`:
  - n8n: últimas ejecuciones de `Docker Auto-Update`, `Monitor NAS Salud` (+ apagados como referencia).
  - cron: `errores-diarios-ingles`, `modelos-opencode`, `ofertas-ia`, `vikunja-digest`, `plex-ingest`, `gdrive-refresh`, `kanban-sync`.
  - manuales (`anki-push`, `backup-opencode`, `opencode-password-file`) quedan en `manual` sin cadencia: se lanzan a mano.
- En el contenedor (`/workspace`) el script conserva los valores previos del NAS para los logs que solo existen allí (`/home/emlami/*.log`).

## URL

- NAS: `http://192.168.1.41:8081/automatizaciones/automatizaciones.html`
- Fuera (Tailscale): `http://100.127.141.110:8081/automatizaciones/automatizaciones.html`

No hace falta tocar nginx: `static-tools` ya sirve todo `proyectos-generales/` y el JSON es solo lectura (sin PUT).

## Cron horario (NAS)

Se instala una vez desde el contenedor (ver bloque en el mensaje de entrega). Después:

```bash
cat /etc/cron.d/automatizaciones-dashboard
python3 /volume1/docker/opencode2/proyectos-generales/automatizaciones/update.py
cat /volume1/docker/opencode2/proyectos-generales/automatizaciones/automatizaciones.json | head -20
```
