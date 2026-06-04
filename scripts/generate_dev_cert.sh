#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CERT_DIR="$PROJECT_DIR/certs"
CERT_PATH="$CERT_DIR/dev-cert.pem"
KEY_PATH="$CERT_DIR/dev-key.pem"
TMP_CONFIG=$(mktemp)

mkdir -p "$CERT_DIR"

HOSTS="localhost 127.0.0.1 $(hostname)"

if command -v ipconfig >/dev/null 2>&1; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || true)
    if [ -z "$LAN_IP" ]; then
        LAN_IP=$(ipconfig getifaddr en1 2>/dev/null || true)
    fi
    if [ -n "$LAN_IP" ]; then
        HOSTS="$HOSTS $LAN_IP"
    fi
fi

if [ -n "${DEV_CERT_HOSTS:-}" ]; then
    HOSTS="$HOSTS $DEV_CERT_HOSTS"
fi

if [ "$#" -gt 0 ]; then
    HOSTS="$HOSTS $*"
fi

{
    echo "[req]"
    echo "default_bits = 2048"
    echo "prompt = no"
    echo "default_md = sha256"
    echo "x509_extensions = v3_req"
    echo "distinguished_name = dn"
    echo
    echo "[dn]"
    echo "CN = localhost"
    echo
    echo "[v3_req]"
    echo "subjectAltName = @alt_names"
    echo
    echo "[alt_names]"

    INDEX=1
    for HOST in $HOSTS; do
        [ -n "$HOST" ] || continue
        case "$HOST" in
            *[!0-9.]*)
                echo "DNS.$INDEX = $HOST"
                ;;
            *)
                echo "IP.$INDEX = $HOST"
                ;;
        esac
        INDEX=$((INDEX + 1))
    done
} > "$TMP_CONFIG"

cleanup() {
    rm -f "$TMP_CONFIG"
}
trap cleanup EXIT

openssl req \
    -x509 \
    -nodes \
    -days 825 \
    -newkey rsa:2048 \
    -keyout "$KEY_PATH" \
    -out "$CERT_PATH" \
    -config "$TMP_CONFIG"

printf "Created:\n  %s\n  %s\n" "$CERT_PATH" "$KEY_PATH"
printf "Start HTTPS with:\n  LOCAL_HTTPS=1 python3 app.py\n"
printf "If you need to add a specific LAN IP, rerun:\n  ./scripts/generate_dev_cert.sh 192.168.x.x\n"
