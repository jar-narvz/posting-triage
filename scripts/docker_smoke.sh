#!/usr/bin/env bash
# Smoke-test a built image: scripts/docker_smoke.sh posting-triage:ci
# CI runs this on every push; it runs the same way locally. It uses a dummy token and key
# and the example profile, and every check stops before the pipeline would call Claude,
# so it needs no secrets and costs nothing.
set -euo pipefail

IMAGE="${1:?usage: scripts/docker_smoke.sh IMAGE}"
HOST_PORT="${HOST_PORT:-18080}"
NAME="triage-smoke-$$"
URL="http://127.0.0.1:${HOST_PORT}"
TOKEN="smoke-test-token"

cleanup() {
    if [ "${failed:-1}" = 1 ]; then
        echo "--- container logs"
        docker logs "$NAME" 2>&1 | tail -30 || true
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() { echo "FAIL: $*"; exit 1; }

expect_status() {  # expect_status WANT DESCRIPTION CURL_ARGS...
    local want="$1" what="$2"; shift 2
    local got
    got=$(curl -s -o /dev/null -w '%{http_code}' "$@")
    [ "$got" = "$want" ] || fail "$what: expected $want, got $got"
    echo "ok   $what ($got)"
}

docker run -d --name "$NAME" -p "${HOST_PORT}:8080" \
    -e TRIAGE_API_TOKEN="$TOKEN" -e ANTHROPIC_API_KEY=not-a-real-key \
    -v "$(pwd)/profile.example.yaml:/app/profile.yaml:ro" "$IMAGE" >/dev/null

# The image's own HEALTHCHECK decides when the API is up.
for _ in $(seq 60); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$NAME")
    [ "$status" = healthy ] && break
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = true ] || fail "container exited"
    sleep 1
done
[ "$status" = healthy ] || fail "not healthy after 60 s (status: $status)"
echo "ok   container healthy"

curl -s "$URL/health" | grep -q '"status":"ok"' || fail "/health body"
echo "ok   /health says ok"
expect_status 401 "no token is refused" \
    -X POST "$URL/triage" -H 'Content-Type: application/json' -d '{"url": "https://example.com/"}'
expect_status 401 "wrong token is refused" \
    -X POST "$URL/triage" -H "Authorization: Bearer wrong" -H 'Content-Type: application/json' \
    -d '{"url": "https://example.com/"}'
expect_status 400 "cloud metadata address is blocked" \
    -X POST "$URL/triage" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"url": "http://169.254.169.254/latest/meta-data/"}'
expect_status 400 "the container's own localhost is blocked" \
    -X POST "$URL/triage" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"url": "http://localhost:8080/health"}'

# Chromium starts as the image's user, through the proxy, with the JIT off, and leaves no zombies.
docker exec "$NAME" python -c '
import subprocess
from posting_triage.liveness import Browser
with Browser() as b:
    page = b._browser.new_page()
    page.set_content("<p>ok</p>")
    assert page.inner_text("p") == "ok"
    assert page.evaluate("typeof WebAssembly") == "undefined", "JIT is on"
zombies = subprocess.run("ps -eo stat | grep -c ^Z", shell=True, capture_output=True, text=True).stdout.strip()
assert zombies == "0", f"{zombies} zombie processes"
' || fail "Chromium inside the container"
echo "ok   Chromium launches, JIT off, no zombies"

docker exec "$NAME" sh -c '[ "$(id -u)" != 0 ]' || fail "running as root"
echo "ok   not running as root"

# The same image runs the CLI (decision 10).
docker run --rm "$IMAGE" triage run --help >/dev/null || fail "CLI mode"
echo "ok   CLI mode runs"

failed=0
echo "all smoke checks passed"
