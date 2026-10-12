# FLSUN_notify - Moonraker helper for the FLSun T1 Pro
#
# The notifications themselves are sent by Moonraker's own [notifier]
# sections (Apprise), which read the URL and printer name from
# ~/printer_data/moonraker.secrets. That file is hidden from Mainsail and
# Fluidd, so the user edits flsun_notify.txt in the config folder instead and
# runs UPDATE_NOTIFY, which calls this component to:
#   - copy the [notify] section into moonraker.secrets, keeping anything
#     else already in that file,
#   - restart Moonraker so the notifiers load the new URL,
#   - send a confirmation message once Moonraker is back.
# It also sends "Printer on" (the _NOTIFY TYPE=on message) after a boot.
#
# Copyright (C) 2026 DIEHARDave
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import configparser
import io
import json
import logging
import pathlib

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from .klippy_apis import KlippyAPI

SECTION = "notify"
# Klippy becoming ready this soon after the system boots counts as a power on.
BOOT_WINDOW = 300.


class FlsunNotify:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        data_path = pathlib.Path(self.server.get_app_args()["data_path"])
        self.secrets_file = data_path.joinpath("moonraker.secrets")
        self.settings_file = pathlib.Path(config.get(
            "settings_file", str(data_path.joinpath("config/flsun_notify.txt"))
        )).expanduser()
        self.flag_file = data_path.joinpath(".flsun_notify_updated")
        self.boot_checked = False

        self._restore_settings()
        self.server.register_remote_method(
            "flsun_notify_update", self._handle_update)
        self.server.register_event_handler(
            "server:klippy_ready", self._handle_klippy_ready)

    # flsun_notify.txt is the user's copy; if it went missing (FLSun firmware
    # updates can reset the config folder), rebuild it from the secrets.
    def _restore_settings(self) -> None:
        if self.settings_file.exists():
            return
        values = self._read_secrets().get(SECTION)
        if not isinstance(values, dict):
            return
        lines = [f"[{SECTION}]"] + [f"{k}: {v}" for k, v in values.items()]
        try:
            self.settings_file.write_text("\n".join(lines) + "\n")
        except OSError:
            logging.exception("flsun_notify: could not restore settings")

    def _read_secrets(self) -> Dict[str, Any]:
        if not self.secrets_file.is_file():
            return {}
        data = self.secrets_file.read_text()
        try:
            vals = json.loads(data)
        except json.JSONDecodeError:
            pass
        else:
            return vals if isinstance(vals, dict) else {}
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(data)
        except configparser.Error:
            return {}
        return {s: dict(parser[s]) for s in parser.sections()}

    def _read_settings(self) -> Dict[str, str]:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(self.settings_file.read_text())
        if not parser.has_section(SECTION):
            raise ValueError(f"no [{SECTION}] section")
        values = dict(parser[SECTION])
        url = values.get("url", "").strip()
        if not url or "://" not in url:
            raise ValueError("'url:' is missing or isn't an Apprise URL")
        if "{" in url:
            raise ValueError(
                "'url:' still contains a placeholder such as {bottoken}")
        values.setdefault("name", "")
        return values

    def _write_secrets(self, values: Dict[str, str]) -> None:
        data = (
            self.secrets_file.read_text() if self.secrets_file.is_file() else ""
        )
        try:
            vals = json.loads(data) if data.strip() else None
        except json.JSONDecodeError:
            vals = None
        if isinstance(vals, dict):
            vals[SECTION] = values
            out = json.dumps(vals, indent=2) + "\n"
        else:
            parser = configparser.ConfigParser(interpolation=None)
            if data.strip():
                parser.read_string(data)
            if parser.has_section(SECTION):
                parser.remove_section(SECTION)
            parser.add_section(SECTION)
            for key, val in values.items():
                parser.set(SECTION, key, val)
            buf = io.StringIO()
            parser.write(buf)
            out = buf.getvalue()
        tmp = self.secrets_file.with_suffix(".tmp")
        tmp.write_text(out)
        tmp.chmod(0o600)
        tmp.replace(self.secrets_file)

    def _respond(self, msg: str) -> None:
        self.server.send_event("server:gcode_response", f"// {msg}")

    async def _handle_update(self) -> None:
        try:
            values = self._read_settings()
        except FileNotFoundError:
            self._respond(f"FLSUN_notify: {self.settings_file} not found")
            return
        except (ValueError, configparser.Error) as e:
            self._respond(f"FLSUN_notify: {self.settings_file.name}: {e}")
            return
        try:
            self._write_secrets(values)
            self.flag_file.touch()
        except (OSError, configparser.Error) as e:
            logging.exception("flsun_notify: could not write secrets")
            self._respond(f"FLSUN_notify: could not save the settings: {e}")
            return
        self._respond(
            "FLSUN_notify: settings saved; restarting Moonraker. A test "
            "message follows in about 20 seconds.")
        # systemd restarts Moonraker (Restart=always), which reloads the
        # notifiers with the new secrets.
        self.server.get_event_loop().delay_callback(
            1., self.server._stop_server, "restart")

    async def _handle_klippy_ready(self) -> None:
        if self.flag_file.exists():
            self.flag_file.unlink()
            self.boot_checked = True
            await self._run_gcode(
                '_NOTIFY MSG="Notifications are set up" PHOTO=0')
            return
        if self.boot_checked:
            return
        self.boot_checked = True
        if _uptime() < BOOT_WINDOW:
            await self._run_gcode('_NOTIFY MSG="Printer on" TYPE=on PHOTO=0')

    async def _run_gcode(self, script: str) -> None:
        kapis: KlippyAPI = self.server.lookup_component("klippy_apis")
        try:
            await kapis.run_gcode(script)
        except self.server.error as e:
            logging.info(f"flsun_notify: '{script}' failed: {e}")


def _uptime() -> float:
    try:
        return float(pathlib.Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return BOOT_WINDOW


def load_component(config: ConfigHelper) -> FlsunNotify:
    return FlsunNotify(config)
