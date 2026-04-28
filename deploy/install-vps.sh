#!/usr/bin/env bash
# Install / re-install cleaners-hub on the VPS.
#
# Idempotent: run as many times as you want. On a fresh VPS it does the full
# install (clone, venv, systemd unit, cloudflared ingress, DNS CNAME). On a
# subsequent run with the unit already installed, it does a code update +
# venv refresh + service restart.
#
# Prerequisites (one-time, run BEFORE first execution):
#   1. Both keys planted via systemd-creds:
#        sudo systemd-creds encrypt --name=xai-api-key    - /etc/credstore.encrypted/xai-api-key
#        sudo systemd-creds encrypt --name=resend-api-key - /etc/credstore.encrypted/resend-api-key
#   2. Cloudflare PAT planted at /etc/credstore.encrypted/github-pat
#      (already in place on this VPS post-2026-04-27 lockdown)
#   3. CF API token + Zone ID planted at /etc/credstore.encrypted/{cf-api-token,cf-zone-id}
#
# Usage:
#   sudo /var/www/dashboard/apps/cleaners-hub/deploy/install-vps.sh
#
# Or, on a fresh VPS where the repo isn't cloned yet:
#   sudo bash <(curl -s https://raw.githubusercontent.com/maxthebot99-bit/cleaners-hub/main/deploy/install-vps.sh)
#   (requires github-pat-askpass for the private repo clone)

set -euo pipefail

# ─── tunables ────────────────────────────────────────────────────────────────

APP_NAME="cleaners-hub"
SUBDOMAIN="cleaners"
DOMAIN="maxcommandcenter.com"
HOSTNAME_FQDN="${SUBDOMAIN}.${DOMAIN}"
PORT_RANGE_START=8180
PORT_RANGE_END=8250

REPO_URL="https://github.com/maxthebot99-bit/${APP_NAME}.git"
SOURCE_DIR="/home/kianna/github-repos/${APP_NAME}"
APP_DIR="/var/www/dashboard/apps/${APP_NAME}"
STATE_DIR="/var/lib/${APP_NAME}"
OUTPUTS_DIR="/var/lib/${APP_NAME}/outputs"
UNIT_PATH="/etc/systemd/system/${APP_NAME}.service"
CLOUDFLARED_CONFIG="/etc/cloudflared/config.yml"

# ─── preflight ───────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    echo "[install] ERROR: must run as root (use sudo)."
    exit 1
fi

for f in /etc/credstore.encrypted/xai-api-key \
         /etc/credstore.encrypted/resend-api-key \
         /etc/credstore.encrypted/github-pat \
         /etc/credstore.encrypted/cf-api-token \
         /etc/credstore.encrypted/cf-zone-id; do
    if [[ ! -f "$f" ]]; then
        echo "[install] ERROR: missing credential $f. See deploy/install-vps.sh prereqs."
        exit 1
    fi
done

if ! command -v rsync >/dev/null 2>&1; then
    echo "[install] installing rsync..."
    apt-get install -y -qq rsync >/dev/null
fi

# ─── source: clone or pull ───────────────────────────────────────────────────

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    echo "[install] cloning $REPO_URL ..."
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/usr/local/bin/github-pat-askpass \
        git -c credential.helper= clone "$REPO_URL" "$SOURCE_DIR"
    chown -R kianna:kianna "$SOURCE_DIR"
else
    echo "[install] pulling latest in $SOURCE_DIR ..."
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/usr/local/bin/github-pat-askpass \
        git -C "$SOURCE_DIR" -c credential.helper= pull --ff-only origin main
fi

# ─── deploy: rsync to app dir ────────────────────────────────────────────────

echo "[install] rsync source → $APP_DIR ..."
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='node_modules/' \
    --exclude='ui/node_modules/' \
    --exclude='.local-data/' \
    --exclude='.local-tmp/' \
    "$SOURCE_DIR/" \
    "$APP_DIR/"

# ─── venv: create or refresh ─────────────────────────────────────────────────

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    echo "[install] creating venv ..."
    python3 -m venv "$APP_DIR/.venv"
fi

echo "[install] pip install -e . (~30s if cached, ~2min if fresh) ..."
"$APP_DIR/.venv/bin/pip" install --quiet --no-input --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet --no-input -e "$APP_DIR"

# ─── persistent state + outputs dir ──────────────────────────────────────────
# State dir holds spend.sqlite3, history.sqlite3, settings.json, alerts.sqlite3
# Outputs dir holds completed run CSVs (survive systemctl restart)

mkdir -p "$STATE_DIR" "$OUTPUTS_DIR"
chown -R www-data:www-data "$STATE_DIR"

# ─── ownership + permissions ─────────────────────────────────────────────────

echo "[install] chown -R www-data ..."
chown -R www-data:www-data "$APP_DIR"
chmod +x "$APP_DIR/deploy/start.sh"

# ─── pick a port (only on first install) ─────────────────────────────────────

PORT=""
if grep -q "hostname: ${HOSTNAME_FQDN}" "$CLOUDFLARED_CONFIG" 2>/dev/null; then
    # Already in cloudflared — reuse the existing port.
    PORT=$(grep -A1 "hostname: ${HOSTNAME_FQDN}" "$CLOUDFLARED_CONFIG" \
        | grep -oP 'localhost:\K[0-9]+' || echo "")
fi

if [[ -z "$PORT" ]]; then
    echo "[install] picking a free port in ${PORT_RANGE_START}-${PORT_RANGE_END} ..."
    USED=$(grep -oP 'localhost:\K[0-9]+' "$CLOUDFLARED_CONFIG" | sort -nu)
    for p in $(seq "$PORT_RANGE_START" "$PORT_RANGE_END"); do
        echo "$USED" | grep -q "^${p}$" && continue
        ss -tlnp 2>/dev/null | grep -q ":${p} " && continue
        PORT=$p; break
    done
    if [[ -z "$PORT" ]]; then
        echo "[install] ERROR: no free ports in range."
        exit 1
    fi
fi
echo "[install] using PORT=$PORT"

# ─── install / refresh systemd unit ──────────────────────────────────────────

echo "[install] installing systemd unit ..."
cp "$APP_DIR/deploy/cleaners-hub.service" "$UNIT_PATH"
sed -i "s|^Environment=PORT=.*|Environment=PORT=${PORT}|" "$UNIT_PATH"
chmod 644 "$UNIT_PATH"

systemctl daemon-reload
systemctl reset-failed "${APP_NAME}.service" 2>/dev/null || true

# ─── ensure cloudflared ingress exists ───────────────────────────────────────

NEED_CF_RESTART=0

if ! grep -q "hostname: ${HOSTNAME_FQDN}" "$CLOUDFLARED_CONFIG"; then
    echo "[install] adding cloudflared ingress ${HOSTNAME_FQDN} → localhost:${PORT} ..."
    /usr/local/bin/cloudflared-ingress-helper add "$APP_NAME" "$PORT"
    # The helper uses ${APP_NAME} as the hostname prefix; rename to match
    # SUBDOMAIN if they differ.
    if [[ "$APP_NAME" != "$SUBDOMAIN" ]]; then
        sed -i "s|${APP_NAME}\\.${DOMAIN}|${HOSTNAME_FQDN}|" "$CLOUDFLARED_CONFIG"
    fi
    cloudflared --config "$CLOUDFLARED_CONFIG" tunnel ingress validate
    NEED_CF_RESTART=1
else
    echo "[install] cloudflared ingress already present."
fi

# ─── ensure DNS CNAME exists ─────────────────────────────────────────────────

CF_TOKEN=$(systemd-creds decrypt --name=cf-api-token /etc/credstore.encrypted/cf-api-token -)
CF_ZONE=$(systemd-creds decrypt --name=cf-zone-id /etc/credstore.encrypted/cf-zone-id -)
TUNNEL_ID=$(grep -E '^tunnel:' "$CLOUDFLARED_CONFIG" | awk '{print $2}')

DNS_CHECK=$(curl -s "https://api.cloudflare.com/client/v4/zones/${CF_ZONE}/dns_records?name=${HOSTNAME_FQDN}" \
    -H "Authorization: Bearer ${CF_TOKEN}")
DNS_COUNT=$(echo "$DNS_CHECK" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',[])))" 2>/dev/null || echo 0)

if [[ "$DNS_COUNT" -lt 1 ]]; then
    echo "[install] creating DNS CNAME ${HOSTNAME_FQDN} → tunnel ..."
    curl -s -o /dev/null -X POST \
        "https://api.cloudflare.com/client/v4/zones/${CF_ZONE}/dns_records" \
        -H "Authorization: Bearer ${CF_TOKEN}" \
        -H "Content-Type: application/json" \
        --data "{\"type\":\"CNAME\",\"name\":\"${SUBDOMAIN}\",\"content\":\"${TUNNEL_ID}.cfargotunnel.com\",\"proxied\":true,\"ttl\":1}"
else
    echo "[install] DNS CNAME already exists."
fi

unset CF_TOKEN CF_ZONE

# ─── start the app + cloudflared ─────────────────────────────────────────────

echo "[install] enabling + restarting ${APP_NAME}.service ..."
# `enable --now` is a no-op when the service is already running — it only
# starts a stopped unit. We need an explicit restart so the live Python
# process picks up source changes from this rsync pass. Without this, the
# binary on disk is the new code but the running process keeps the old.
systemctl enable "${APP_NAME}.service"
systemctl restart "${APP_NAME}.service"
sleep 3

# ─── auto-deploy timer (idempotent) ──────────────────────────────────────────
# Polls origin/main every 60s and re-runs this script if a new commit is
# present. After the first install of these files, every git push to main
# is picked up within ~60s without anyone touching the VPS.

AUTODEPLOY_UNIT="${APP_NAME}-autodeploy"
AUTODEPLOY_SVC_PATH="/etc/systemd/system/${AUTODEPLOY_UNIT}.service"
AUTODEPLOY_TIMER_PATH="/etc/systemd/system/${AUTODEPLOY_UNIT}.timer"

if [[ -f "$APP_DIR/deploy/${AUTODEPLOY_UNIT}.service" \
   && -f "$APP_DIR/deploy/${AUTODEPLOY_UNIT}.timer" \
   && -f "$APP_DIR/deploy/auto-deploy.sh" ]]; then
    echo "[install] installing ${AUTODEPLOY_UNIT}.timer ..."
    chmod 755 "$APP_DIR/deploy/auto-deploy.sh"
    cp "$APP_DIR/deploy/${AUTODEPLOY_UNIT}.service" "$AUTODEPLOY_SVC_PATH"
    cp "$APP_DIR/deploy/${AUTODEPLOY_UNIT}.timer"   "$AUTODEPLOY_TIMER_PATH"
    chmod 644 "$AUTODEPLOY_SVC_PATH" "$AUTODEPLOY_TIMER_PATH"
    systemctl daemon-reload
    systemctl enable --now "${AUTODEPLOY_UNIT}.timer"
fi

if [[ $NEED_CF_RESTART -eq 1 ]]; then
    echo "[install] restarting cloudflared (nohup so SSH survives) ..."
    nohup systemctl restart cloudflared.service >/dev/null 2>&1 &
    disown
    sleep 12
fi

# ─── verify ──────────────────────────────────────────────────────────────────

echo
echo "── verification ──"
echo "cleaners-hub:  $(systemctl is-active "${APP_NAME}.service")"
echo "cloudflared:   $(systemctl is-active cloudflared.service)"
echo "/api/health:   $(curl -s -m 5 "http://127.0.0.1:${PORT}/api/health" || echo '(no response)')"
echo
echo "Public URL:    https://${HOSTNAME_FQDN}"
echo "Logs:          journalctl -u ${APP_NAME}.service -f"
echo "Auto-deploy:   $(systemctl is-active "${APP_NAME}-autodeploy.timer" 2>/dev/null || echo 'inactive')"
echo "Kill switch:   systemctl stop ${APP_NAME}.service"
echo
echo "[install] done."
