#!/bin/bash
# Removes FLSUN_notify. flsun_notify.txt (your URL and printer name) is kept,
# so reinstalling picks it up again; delete it yourself if you don't need it.

set -e

COMPONENTS_DIR="${HOME}/moonraker/moonraker/components"
DATA_DIR="${HOME}/printer_data"
CONFIG_DIR="${DATA_DIR}/config"
MOONRAKER_CONF="${CONFIG_DIR}/moonraker.conf"
PRINTER_CFG="${CONFIG_DIR}/printer.cfg"
SECRETS="${DATA_DIR}/moonraker.secrets"

msg() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }

[ "$(id -u)" -ne 0 ] || { echo "run as the pi user, not root" >&2; exit 1; }

msg "Removing the Moonraker component"
[ -L "${COMPONENTS_DIR}/flsun_notify.py" ] && rm -f "${COMPONENTS_DIR}/flsun_notify.py"

msg "Removing the Klipper macros"
sed -i '/^\[include flsun_notify\.cfg\]/d' "$PRINTER_CFG"
[ -L "${CONFIG_DIR}/flsun_notify.cfg" ] && rm -f "${CONFIG_DIR}/flsun_notify.cfg"

msg "Removing the Moonraker settings"
sed -i '/^\[include flsun_notify\.conf\]/d; /^\[include flsun_notify_custom\.conf\]/d' "$MOONRAKER_CONF"
[ -L "${CONFIG_DIR}/flsun_notify.conf" ] && rm -f "${CONFIG_DIR}/flsun_notify.conf"
rm -f "${CONFIG_DIR}/flsun_notify_custom.conf" "${DATA_DIR}/.flsun_notify_updated"

# Drop the [notify] section from the secrets; delete the file if that was
# all it held.
if [ -f "$SECRETS" ] && grep -q '^\[notify\]' "$SECRETS"; then
    sed -i '/^\[notify\]/,/^\[/{/^\[notify\]/d;/^\[/!d}' "$SECRETS"
    grep -q '[^[:space:]]' "$SECRETS" || rm -f "$SECRETS"
fi

# The flsun-timesync boot service from prepare.sh is left in place on
# purpose: a correct clock helps everything else on the printer too.

msg "Restarting Moonraker and Klipper"
sudo systemctl restart moonraker
sudo systemctl restart klipper

msg "Done. Delete ~/FLSUN_notify to finish."
