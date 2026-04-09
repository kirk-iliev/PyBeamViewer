#!/usr/bin/env bash
# validate.sh — Run all beam viewer validation checks against a running container
#
# Usage (from your Mac):
#   ssh appsdev2 "bash ~/projects/PyBeamViewer/.claude/skills/beam-viewer-deploy/scripts/validate.sh"
#
# Or copy to appsdev2 and run locally:
#   bash validate.sh [--host localhost] [--port 8007]
#
# Exit code: 0 if all critical checks pass, 1 if any fail

set -euo pipefail

HOST="${1:---host}"
PORT="8007"
BASE_URL="http://localhost:${PORT}"
CONTAINER="beam-viewer-test"

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --host) HOST="$2"; shift 2 ;;
        --port) PORT="$2"; BASE_URL="http://${HOST}:${PORT}"; shift 2 ;;
        *) shift ;;
    esac
done
BASE_URL="http://localhost:${PORT}"

PASS=0
FAIL=0
WARN=0
SKIP=0

pass() { echo "  PASS: $1"; ((PASS++)); }
fail() { echo "  FAIL: $1"; ((FAIL++)); }
warn() { echo "  WARN: $1"; ((WARN++)); }
skip() { echo "  SKIP: $1"; ((SKIP++)); }

echo "=========================================="
echo " Beam Viewer Validation"
echo " Target: ${BASE_URL}"
echo " Container: ${CONTAINER}"
echo "=========================================="
echo ""

# --- Tier 1: Container ---
echo "--- Tier 1: Container Health ---"

if podman ps --filter "name=${CONTAINER}" --format '{{.Names}}' 2>/dev/null | grep -q "${CONTAINER}"; then
    STATUS=$(podman ps --filter "name=${CONTAINER}" --format '{{.Status}}')
    pass "Container running (${STATUS})"
else
    fail "Container not running"
    echo ""
    echo "Container is not running. Remaining checks will fail."
    echo "Check: podman logs ${CONTAINER}"
    exit 1
fi
echo ""

# --- Tier 2: API ---
echo "--- Tier 2: API Health ---"

HEALTH=$(curl -sf --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HEALTH=""
if [ -z "$HEALTH" ]; then
    fail "Health endpoint unreachable"
    echo "  API is not responding. Check container logs."
    exit 1
fi

STATUS_VAL=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
CONNECTED=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('connected',False))" 2>/dev/null)
STREAMING=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('streaming',False))" 2>/dev/null)
FRAME_COUNT=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('frame_count',0))" 2>/dev/null)

if [ "$STATUS_VAL" = "ok" ]; then
    pass "Health: ok (connected=${CONNECTED}, streaming=${STREAMING}, frames=${FRAME_COUNT})"
elif [ "$STATUS_VAL" = "degraded" ]; then
    REASON=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reason','unknown'))" 2>/dev/null)
    warn "Health: degraded (${REASON})"
else
    fail "Health: unexpected status '${STATUS_VAL}'"
fi

# OpenAPI routes
ROUTE_COUNT=$(curl -sf --max-time 5 "${BASE_URL}/openapi.json" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('paths',{})))" 2>/dev/null) || ROUTE_COUNT=0
if [ "$ROUTE_COUNT" -gt 10 ]; then
    pass "API routes: ${ROUTE_COUNT} registered"
else
    fail "API routes: only ${ROUTE_COUNT} found (expected >10)"
fi
echo ""

# --- Tier 3: EPICS Data ---
echo "--- Tier 3: EPICS Data Pipeline ---"

# Camera info
CAMERA_INFO=$(curl -sf --max-time 5 "${BASE_URL}/camera/info" 2>/dev/null) || CAMERA_INFO=""
if [ -n "$CAMERA_INFO" ]; then
    PREFIX=$(echo "$CAMERA_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('active_prefix',''))" 2>/dev/null)
    pass "Camera info: active prefix = ${PREFIX}"
else
    fail "Camera info: endpoint failed"
fi

# Current frame
HTTP_CODE=$(curl -sf --max-time 10 "${BASE_URL}/frames/current" -o /tmp/beam_validate.png -w '%{http_code}' 2>/dev/null) || HTTP_CODE="000"
if [ "$HTTP_CODE" = "200" ]; then
    FILE_SIZE=$(stat -c%s /tmp/beam_validate.png 2>/dev/null || stat -f%z /tmp/beam_validate.png 2>/dev/null || echo "0")
    if [ "$FILE_SIZE" -gt 1000 ]; then
        pass "Current frame: ${FILE_SIZE} bytes PNG"
    else
        warn "Current frame: returned but only ${FILE_SIZE} bytes (may be placeholder)"
    fi
else
    if [ "$CONNECTED" = "False" ]; then
        skip "Current frame: EPICS not connected (expected)"
    else
        fail "Current frame: HTTP ${HTTP_CODE}"
    fi
fi

# Analysis
ANALYSIS=$(curl -sf --max-time 5 "${BASE_URL}/analysis/beam" 2>/dev/null) || ANALYSIS=""
if [ -n "$ANALYSIS" ]; then
    FIT_VALID=$(echo "$ANALYSIS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('fit_valid',False))" 2>/dev/null)
    if [ "$FIT_VALID" = "True" ]; then
        pass "Beam analysis: fit valid"
    else
        warn "Beam analysis: fit_valid=False (beam may be off or saturated)"
    fi
else
    if [ "$CONNECTED" = "False" ]; then
        skip "Beam analysis: EPICS not connected (expected)"
    else
        fail "Beam analysis: endpoint failed"
    fi
fi
echo ""

# --- Tier 4: Real-Time ---
echo "--- Tier 4: Real-Time Features ---"

# Static files
PANEL_CODE=$(curl -sf --max-time 5 -o /dev/null -w '%{http_code}' "${BASE_URL}/panel/" 2>/dev/null) || PANEL_CODE="000"
if [ "$PANEL_CODE" = "200" ]; then
    pass "Web panel: static files served"
else
    fail "Web panel: HTTP ${PANEL_CODE}"
fi

# WebSocket (requires websockets package)
python3 -c "import websockets" 2>/dev/null
if [ $? -eq 0 ] && [ "$CONNECTED" = "True" ]; then
    WS_RESULT=$(python3 -c "
import asyncio, json, time, websockets

async def test():
    async with websockets.connect('ws://localhost:${PORT}/ws/frames') as ws:
        start = time.time()
        count = 0
        while time.time() - start < 5:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'frame_jpeg_b64' in data:
                    count += 1
            except asyncio.TimeoutError:
                break
        elapsed = time.time() - start
        fps = count / elapsed if elapsed > 0 else 0
        print(f'{fps:.1f}')

asyncio.run(test())
" 2>/dev/null) || WS_RESULT="0"

    FPS=$(echo "$WS_RESULT" | head -1)
    if (( $(echo "$FPS >= 5" | bc -l 2>/dev/null || echo 0) )); then
        pass "WebSocket: ${FPS} Hz"
    elif (( $(echo "$FPS > 0" | bc -l 2>/dev/null || echo 0) )); then
        warn "WebSocket: ${FPS} Hz (below 5 Hz target)"
    else
        fail "WebSocket: no frames received"
    fi
elif [ "$CONNECTED" = "False" ]; then
    skip "WebSocket: EPICS not connected"
else
    skip "WebSocket: websockets package not installed"
fi
echo ""

# --- Summary ---
echo "=========================================="
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo " Results: ${PASS} pass, ${FAIL} fail, ${WARN} warn, ${SKIP} skip (${TOTAL} total)"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
    echo " Status: SOME CHECKS FAILED"
    exit 1
else
    echo " Status: ALL CRITICAL CHECKS PASSED"
    exit 0
fi
