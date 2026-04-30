#!/usr/bin/env bash
# Codespaces post-create: download the powston-simulator wheel from the
# Powston API using the customer's API key, then install it with example
# extras.
#
# Override env (set in devcontainer.json or via Codespaces secrets):
#   POWSTON_API_KEY   — required, same key as run-site-sim.py uses
#   POWSTON_API_BASE  — defaults to https://app.powston.com
#   PYTHON_TAG        — defaults to cp312 (matches the container's Python)
#   PLATFORM          — defaults to linux_x86_64 (Codespaces is always this)
set -euo pipefail

if [[ -z "${POWSTON_API_KEY:-}" ]]; then
    cat >&2 <<'EOF'
POWSTON_API_KEY is not set.

Add it as a Codespaces secret on this repo:
  Settings -> Secrets and variables -> Codespaces -> New repository secret
Then stop and recreate this Codespace.
EOF
    exit 1
fi

API_BASE="${POWSTON_API_BASE:-https://app.powston.com}"
PYTHON_TAG="${PYTHON_TAG:-cp312}"
PLATFORM="${PLATFORM:-linux_x86_64}"
WHEEL_DIR="${WHEEL_DIR:-/tmp/powston-wheels}"

mkdir -p "$WHEEL_DIR"
rm -f "$WHEEL_DIR"/*.whl

URL="${API_BASE}/api/wheels?platform=${PLATFORM}&py=${PYTHON_TAG}"
echo ">> Fetching wheel from ${URL}"
curl --fail --silent --show-error --location \
    --header "Authorization: Bearer ${POWSTON_API_KEY}" \
    --output "$WHEEL_DIR/powston_simulator.whl" \
    "$URL"

echo ">> Installing wheel + [examples] extras"
python -m pip install --upgrade pip
python -m pip install "$WHEEL_DIR/powston_simulator.whl"
# Reinstall with extras now that the dist name is known to pip.
python -m pip install "powston-simulator[examples]"

cat <<'EOF'

powston-simulator installed. Try a one-week tune:
  python run-site-sim.py --inverter_id <YOUR_INVERTER_ID> --days 7

The script prints the best variable values it finds — copy them back
into your Powston rule manually.

EOF
