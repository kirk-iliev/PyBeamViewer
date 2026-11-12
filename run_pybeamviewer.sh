#!/usr/bin/env bash
# Launch PyBeamViewer with a pre-flight EPICS check and per-run logging.
# Used by the desktop shortcut; can also be run from a terminal.

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$APP_DIR/.venv/bin/python"
LOG_DIR="$HOME/.local/state/pybeamviewer"
LOG_FILE="$LOG_DIR/pybeamviewer_$(date +%Y%m%d_%H%M%S).log"

have_gui() { [ -n "$DISPLAY$WAYLAND_DISPLAY" ] && command -v zenity >/dev/null; }

cd "$APP_DIR" || exit 1

# Pre-flight: can we reach the active camera's PVs? Prints a reason on failure.
# Native mode (host empty): Channel Access search for the active width PV.
# Tunnel mode (host set): TCP connect to host:port.
PROBLEM="$("$PY" - <<'EOF' 2>/dev/null
import json, socket, sys
try:
    cfg = json.load(open("config/config.json"))
    prefix = cfg["active_prefix"]
    pv = cfg["pv_prefixes"][prefix].get("width_pv") or cfg["pv_prefixes"][prefix]["image_pv"]
    host = (cfg.get("epics") or {}).get("host", "")
    port = int((cfg.get("epics") or {}).get("port", 5064))
except Exception as e:
    print(f"Could not read config/config.json: {e}"); sys.exit()
if host:
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError:
        print(f"Active camera: {prefix} (SSH tunnel mode)\n\n"
              f"Nothing is listening on {host}:{port}.\n"
              f"Is the SSH tunnel to the IOC open?")
else:
    from caproto.threading.client import Context
    ctx = Context()
    try:
        (p,) = ctx.get_pvs(pv, timeout=3)
        p.wait_for_connection(timeout=3)
    except Exception:
        print(f"Active camera: {prefix}\n\n"
              f"Could not reach {pv} over EPICS.\n"
              f"Is this laptop on the beamline controls network?\n"
              f"(Working remotely? Use an SSH tunnel and set \"host\" in config/config.json.)")
    finally:
        try: ctx.disconnect()
        except Exception: pass
EOF
)"

if [ -n "$PROBLEM" ]; then
    if have_gui; then
        zenity --question --title="PyBeamViewer - camera not reachable" --width=460 \
               --ok-label="Start anyway" --cancel-label="Cancel" \
               --text="$PROBLEM

You can still start the viewer; it will show nothing until the PVs are reachable." || exit 0
    else
        printf 'WARNING: %s\n' "$PROBLEM" >&2
    fi
fi

mkdir -p "$LOG_DIR"
# Keep only the 20 most recent logs
ls -1t "$LOG_DIR"/pybeamviewer_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f

"$PY" main.py "$@" 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

if [ "$STATUS" -ne 0 ] && have_gui; then
    zenity --error --title="PyBeamViewer exited with an error" --width=600 \
           --text="PyBeamViewer stopped with exit code $STATUS.\n\nFull log: $LOG_FILE\n\nLast lines:\n$(tail -n 15 "$LOG_FILE" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
fi
exit "$STATUS"
