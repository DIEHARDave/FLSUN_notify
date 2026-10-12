#!/bin/bash
# FLSUN_notify installer for the FLSun T1 Pro.
# Run as the pi user from the cloned repo: ~/FLSUN_notify/install.sh
# Safe to re-run, e.g. after a FLSun firmware update.

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENTS_DIR="${HOME}/moonraker/moonraker/components"
DATA_DIR="${HOME}/printer_data"
CONFIG_DIR="${DATA_DIR}/config"
MOONRAKER_CONF="${CONFIG_DIR}/moonraker.conf"
PRINTER_CFG="${CONFIG_DIR}/printer.cfg"
SECRETS="${DATA_DIR}/moonraker.secrets"
MOONRAKER_URL="http://127.0.0.1:7125"

msg() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run as the pi user, not root (sudo is used where needed)"
[ -d "$COMPONENTS_DIR" ] || die "Moonraker components not found at $COMPONENTS_DIR"
[ -f "${COMPONENTS_DIR}/notifier.py" ] || die "this Moonraker has no notifier component"
[ -f "$MOONRAKER_CONF" ] || die "$MOONRAKER_CONF not found"
[ -f "$PRINTER_CFG" ] || die "$PRINTER_CFG not found"
"${HOME}/moonraker-env/bin/python" -c "import apprise" 2> /dev/null \
    || die "Apprise is not installed in Moonraker's Python environment"

# Restarting Klipper mid-print would kill the print.
state=$(curl -s -m 5 "${MOONRAKER_URL}/printer/objects/query?print_stats=state" \
    | sed -n 's/.*"state": *"\([a-z]*\)".*/\1/p')
case "$state" in
    printing|paused) die "a print is $state; run this again when the printer is idle" ;;
esac

# Clock, certificates and git https support; see prepare.sh. Notifications
# go out over HTTPS, so they need the same fixes as updates do.
"${REPO_DIR}/prepare.sh"

msg "Installing the boot service that sets the clock"
sudo install -m 755 "${REPO_DIR}/system/flsun-timesync" /usr/local/bin/flsun-timesync
sudo install -m 644 "${REPO_DIR}/system/flsun-timesync.service" /etc/systemd/system/flsun-timesync.service
sudo systemctl daemon-reload
sudo systemctl enable flsun-timesync.service > /dev/null 2>&1

msg "Linking the Moonraker component"
ln -sfn "${REPO_DIR}/component/flsun_notify.py" "${COMPONENTS_DIR}/flsun_notify.py"

msg "Linking the Klipper macros"
ln -sfn "${REPO_DIR}/klipper/flsun_notify.cfg" "${CONFIG_DIR}/flsun_notify.cfg"
if ! grep -q '^\[include flsun_notify\.cfg\]' "$PRINTER_CFG"; then
    cp "$PRINTER_CFG" "${PRINTER_CFG}.flsun_notify.bak"
    printf '\n[include flsun_notify.cfg]\n' >> "$PRINTER_CFG"
fi
if ! grep -q '^\[save_variables\]' "$PRINTER_CFG" "${CONFIG_DIR}"/*.cfg 2> /dev/null; then
    warn "no [save_variables] section found; the macros need it for their switches"
fi

msg "Adding the Moonraker settings"
ln -sfn "${REPO_DIR}/moonraker/flsun_notify.conf" "${CONFIG_DIR}/flsun_notify.conf"
if [ ! -f "${CONFIG_DIR}/flsun_notify_custom.conf" ]; then
    cp "${REPO_DIR}/config/flsun_notify_custom.conf" "${CONFIG_DIR}/flsun_notify_custom.conf"
fi
if ! grep -q '^\[include flsun_notify\.conf\]' "$MOONRAKER_CONF"; then
    cp "$MOONRAKER_CONF" "${MOONRAKER_CONF}.flsun_notify.bak"
    printf '\n[include flsun_notify.conf]\n[include flsun_notify_custom.conf]\n' >> "$MOONRAKER_CONF"
fi

msg "Adding the notification settings"
if [ ! -f "${CONFIG_DIR}/flsun_notify.txt" ]; then
    cp "${REPO_DIR}/config/flsun_notify.txt" "${CONFIG_DIR}/flsun_notify.txt"
fi
# The notifiers read {secrets.notify.*} when Moonraker starts and fail to
# load without them, so seed the secrets with the placeholders until the
# user runs UPDATE_NOTIFY.
if [ ! -f "$SECRETS" ]; then
    sed -n '/^\[notify\]/,$p' "${REPO_DIR}/config/flsun_notify.txt" > "$SECRETS"
    chmod 600 "$SECRETS"
elif ! grep -q '^\[notify\]' "$SECRETS" && ! grep -q '"notify"' "$SECRETS"; then
    if grep -q '^[[:space:]]*{' "$SECRETS"; then
        warn "$SECRETS is JSON; run UPDATE_NOTIFY after filling in flsun_notify.txt"
    else
        printf '\n' >> "$SECRETS"
        sed -n '/^\[notify\]/,$p' "${REPO_DIR}/config/flsun_notify.txt" >> "$SECRETS"
    fi
fi

msg "Restarting Moonraker and Klipper"
sudo systemctl restart moonraker
sudo systemctl restart klipper

msg "Done. Fill in ~/printer_data/config/flsun_notify.txt (Mainsail or Fluidd:"
msg "Machine > flsun_notify.txt), then run UPDATE_NOTIFY in the console."
