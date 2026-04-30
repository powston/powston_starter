#!/usr/bin/env bash
# Codespaces post-create: download the powston-simulator wheel from the
# Powston API using the customer's API key, then install it with example
# extras.
#
# The server should respond with the wheel bytes. If it sets
# `Content-Disposition: attachment; filename=...`, we use that name; if not,
# we reconstruct the canonical wheel filename by reading the archive's own
# .dist-info/WHEEL metadata. Either way pip gets a properly-named file.
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

# Codespaces secrets store the raw string — if the user wrapped the value in
# quotes when pasting, the literal quote chars get sent in the Authorization
# header and the API rejects them. Strip wrapping quotes defensively.
if [[ "$POWSTON_API_KEY" =~ ^[\"\'].*[\"\']$ ]]; then
    echo "Warning: stripping wrapping quotes from POWSTON_API_KEY." >&2
    POWSTON_API_KEY="${POWSTON_API_KEY#[\"\']}"
    POWSTON_API_KEY="${POWSTON_API_KEY%[\"\']}"
fi

API_BASE="${POWSTON_API_BASE:-https://app.powston.com}"
WHEEL_API_PATH="${WHEEL_API_PATH:-/api/v1/wheels/latest}"
PYTHON_TAG="${PYTHON_TAG:-cp312}"
PLATFORM="${PLATFORM:-linux_x86_64}"
WHEEL_DIR="${WHEEL_DIR:-/tmp/powston-wheels}"

mkdir -p "$WHEEL_DIR"
rm -f "$WHEEL_DIR"/*.whl "$WHEEL_DIR"/.download.tmp

URL="${API_BASE}${WHEEL_API_PATH}?platform=${PLATFORM}&py=${PYTHON_TAG}"
TMP="$WHEEL_DIR/.download.tmp"

echo ">> Fetching wheel from ${URL}"
curl --fail --silent --show-error --location \
    --header "Authorization: Bearer ${POWSTON_API_KEY}" \
    --output "$TMP" \
    "$URL"

# Reconstruct the canonical wheel filename (`{name}-{ver}-{py}-{abi}-{plat}.whl`)
# by reading the .dist-info/WHEEL file inside the archive. This works whether
# or not the server sends Content-Disposition.
WHEEL_NAME=$(python3 - "$TMP" <<'PY'
import sys, zipfile

path = sys.argv[1]
try:
    with zipfile.ZipFile(path) as z:
        distinfo = next(
            n.split("/", 1)[0] for n in z.namelist()
            if n.endswith(".dist-info/WHEEL")
        )
        name_ver = distinfo[:-len(".dist-info")]
        meta = z.read(f"{distinfo}/WHEEL").decode()
        tag = next(
            line[len("Tag: "):] for line in meta.splitlines()
            if line.startswith("Tag: ")
        )
    print(f"{name_ver}-{tag}.whl")
except (zipfile.BadZipFile, StopIteration) as e:
    sys.stderr.write(
        f"Downloaded file is not a wheel ({type(e).__name__}). "
        "Check the API response.\n"
    )
    sys.exit(1)
PY
)

mv "$TMP" "$WHEEL_DIR/$WHEEL_NAME"

# Working directories run-site-sim.py writes to. `tune_logs/` and `sims/`
# are created lazily by the script, but `cache/` is written to without an
# `os.makedirs`, so create all three up front.
mkdir -p cache tune_logs sims

echo ">> Installing $WHEEL_NAME + [examples] extras"
python -m pip install --upgrade pip
python -m pip install "$WHEEL_DIR/$WHEEL_NAME"
# Reinstall with extras now that the dist name is known to pip.
python -m pip install "powston-simulator[examples]"
python -m pip install aemo_to_tariff
# So `quickstart.ipynb` opens cleanly without VS Code prompting for kernels.
python -m pip install ipykernel

cat <<'EOF'

powston-simulator installed. Try a one-week tune:
  python run-site-sim.py --inverter_id <YOUR_INVERTER_ID> --days 7

The script prints the best variable values it finds — copy them back
into your Powston rule manually.

EOF
