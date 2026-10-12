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
#
# Zmod sends its other messages from its own print and sensor macros.
# FLSun's macros don't, so this component watches Klipper's status instead
# and sends:
#   - "Printer on" when Klipper becomes ready after a boot   (notify_on)
#   - "Filament runout detected" while printing              (notify_filament)
#   - progress every notify_percent percent                  (notify_percent)
# The notify_* switches are Klipper saved variables, the same ones the
# _NOTIFY macro reads.
#
# Copyright (C) 2026 DIEHARDave
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import configparser
import io
import json
import logging
import pathlib

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from .klippy_apis import KlippyAPI
    from .notifier import Notifier

SECTION = "notify"
# Klippy becoming ready this soon after the system boots counts as a power on.
BOOT_WINDOW = 300.
ACTIVE_STATES = ("printing", "paused")


class FlsunNotify:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        data_path = pathlib.Path(self.server.get_app_args()["data_path"])
        self.secrets_file = data_path.joinpath("moonraker.secrets")
        self.settings_file = pathlib.Path(config.get(
            "settings_file", str(data_path.joinpath("config/flsun_notify.txt"))
        )).expanduser()
        self.sensor = config.get(
            "filament_sensor", "filament_switch_sensor filament_sensor")
        self.flag_file = data_path.joinpath(".flsun_notify_updated")
        self.boot_checked = False
        self.status: Dict[str, Dict[str, Any]] = {}
        self.notified_percent = 0
        self.runout_sent = False

        self._restore_settings()
        self.server.register_remote_method(
            "flsun_notify_update", self._handle_update)
        self.server.register_event_handler(
            "server:klippy_ready", self._handle_klippy_ready)
        self.server.register_event_handler(
            "file_manager:filelist_changed", self._handle_file_changed)

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

    # Saved in flsun_notify.txt but not copied to the secrets yet, i.e.
    # UPDATE_NOTIFY hasn't been run since the last edit.
    def _settings_pending(self) -> bool:
        try:
            values = self._read_settings()
        except (OSError, ValueError, configparser.Error):
            return False
        current = self._read_secrets().get(SECTION)
        if not isinstance(current, dict):
            return True
        return any(
            str(current.get(k, "")).strip() != str(v).strip()
            for k, v in values.items()
        )

    def _remind_if_pending(self) -> None:
        if self._settings_pending():
            self._respond(
                f"FLSUN_notify: {self.settings_file.name} has changes that "
                "aren't in use yet. Run UPDATE_NOTIFY to apply them.")

    def _handle_file_changed(self, info: Dict[str, Any]) -> None:
        item = info.get("item", {})
        if (
            info.get("action") in ("create_file", "modify_file")
            and item.get("root") == "config"
            and item.get("path") == self.settings_file.name
        ):
            self._remind_if_pending()

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
        await self._subscribe()
        if self.flag_file.exists():
            self.flag_file.unlink()
            self.boot_checked = True
            await self._send("Notifications are set up", photo=False)
            return
        self._remind_if_pending()
        if self.boot_checked:
            return
        self.boot_checked = True
        if _uptime() < BOOT_WINDOW:
            await self._send("Printer on", "on", photo=False)

    async def _subscribe(self) -> None:
        kapis: KlippyAPI = self.server.lookup_component("klippy_apis")
        objects: Dict[str, Optional[list]] = {
            "print_stats": ["state", "filename"],
            "virtual_sdcard": ["progress"],
        }
        available = await kapis.get_object_list(default=[])
        if "save_variables" in available:
            objects["save_variables"] = ["variables"]
        if self.sensor in available:
            objects[self.sensor] = ["enabled", "filament_detected"]
        else:
            logging.info(f"flsun_notify: no [{self.sensor}], runout off")
        status = await kapis.subscribe_objects(
            objects, self._handle_status, default=None)
        if status is None:
            logging.info("flsun_notify: Klipper status subscription failed")
            return
        self.status = {k: dict(v) for k, v in status.items()}
        # A print already running (Moonraker restarted mid-print) carries on
        # from where it is, without repeating messages already sent.
        self.notified_percent = 0
        self.runout_sent = False
        if self._state() in ACTIVE_STATES:
            self.notified_percent = int(self._progress())
            self.runout_sent = self._runout()

    def _handle_status(self, status: Dict[str, Any], eventtime: float) -> None:
        for name, fields in status.items():
            self.status.setdefault(name, {}).update(fields)
        if not any(k in status for k in (
            "print_stats", "virtual_sdcard", self.sensor
        )):
            return
        state = self._state()
        if state not in ACTIVE_STATES:
            self.notified_percent = 0
            self.runout_sent = False
            return
        runout = self._runout()
        if runout and not self.runout_sent:
            self.runout_sent = True
            self._spawn(self._send("Filament runout detected", "filament"))
        elif not runout:
            self.runout_sent = False
        step = _as_int(self._variable("notify_percent", 0))
        if step <= 0:
            return
        percent = self._progress()
        threshold = (self.notified_percent // step + 1) * step
        if threshold <= percent < 100 and percent > self.notified_percent:
            self.notified_percent = int(percent)
            self._spawn(self._send_progress(int(percent)))

    def _state(self) -> str:
        return self.status.get("print_stats", {}).get("state", "")

    def _progress(self) -> float:
        progress = self.status.get("virtual_sdcard", {}).get("progress", 0.)
        return round(float(progress or 0.) * 100., 1)

    def _runout(self) -> bool:
        sensor = self.status.get(self.sensor)
        if not sensor:
            return False
        return bool(sensor.get("enabled")) and \
            sensor.get("filament_detected") is False

    def _variable(self, name: str, default: Any) -> Any:
        variables = self.status.get("save_variables", {}).get("variables")
        if not isinstance(variables, dict):
            return default
        return variables.get(name, default)

    def _spawn(self, coro) -> None:
        self.server.get_event_loop().register_callback(lambda: coro)

    async def _send_progress(self, percent: int) -> None:
        kapis: KlippyAPI = self.server.lookup_component("klippy_apis")
        temps = await kapis.query_objects(
            {"extruder": ["temperature", "target"],
             "heater_bed": ["temperature", "target"]}, default={})
        ext = temps.get("extruder", {})
        bed = temps.get("heater_bed", {})
        filename = self.status.get("print_stats", {}).get("filename") or ""
        basename = filename.replace("\\", "/").split("/")[-1] or "Unknown"
        msg = "%s (%d%%) | %.1f/%.1f°C | %.1f/%.1f°C" % (
            basename, percent,
            ext.get("temperature", 0.), ext.get("target", 0.),
            bed.get("temperature", 0.), bed.get("target", 0.))
        await self._send(msg)

    # Same rules as the _NOTIFY macro: skipped while notify_<kind> is 0,
    # photo unless notify_photo is 0.
    async def _send(
        self, msg: str, kind: str = "ok", photo: bool = True
    ) -> None:
        if _as_int(self._variable(f"notify_{kind}", 1)) != 1:
            return
        if photo and _as_int(self._variable("notify_photo", 1)) == 1:
            name = "notifier_photo"
        else:
            name = "notifier"
        notifier: Optional[Notifier] = self.server.lookup_component(
            "notifier", None)
        if notifier is None:
            logging.info("flsun_notify: Moonraker's notifier isn't loaded")
            return
        try:
            await notifier.notify_action(name, msg)
        except Exception:
            logging.exception(f"flsun_notify: sending '{msg}' failed")


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _uptime() -> float:
    try:
        return float(pathlib.Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return BOOT_WINDOW


def load_component(config: ConfigHelper) -> FlsunNotify:
    return FlsunNotify(config)
