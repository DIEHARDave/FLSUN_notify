# FLSUN_notify

Print notifications for the **FLSun T1 Pro**, sent to Telegram, Discord, Matrix, ntfy, e-mail or any of the [100+ services Apprise supports](https://github.com/caronc/apprise/wiki), with a camera photo attached.

It's a port of ghzserg's [notify plugin for Zmod](https://github.com/ghzserg/notify) (Flashforge AD5X/AD5M). The macros, switches and settings file work the same way, so Zmod's instructions apply here too. Like the original, it uses the notifier and Apprise already built into the T1 Pro's Moonraker, so it doesn't need an external server or bot.

## What you get

| Notification | Sent by | Turn it off |
| :--- | :--- | :--- |
| Print started, finished, error, cancelled, paused, resumed | Moonraker | `flsun_notify_custom.conf`, see [Settings](#settings) |
| Printer turned on | FLSUN_notify | `SAVE_VARIABLE VARIABLE=notify_on VALUE=0` |
| Filament runout | FLSUN_notify | `SAVE_VARIABLE VARIABLE=notify_filament VALUE=0` |
| Progress every N percent (off by default) | FLSUN_notify | `SAVE_VARIABLE VARIABLE=notify_percent VALUE=0` |
| Your own messages from G-code (`_NOTIFY`) | FLSUN_notify | – |

Each message starts with your printer's name and includes a snapshot from the T1 Pro's built-in camera, unless you turn photos off.

## Install

SSH into the printer as `pi` (the default password is `1`).

1. Prepare the system. FLSun's system image can't reach GitHub as shipped: the clock starts about a year and a half in the past, the certificate links are missing, and git's https support was removed. Notifications need the same fixes, because they go out over HTTPS. These commands fix all three (skip them if [FLSUN_Timelapse](https://github.com/DIEHARDave/FLSUN_Timelapse), [FLSUN_RemoteScreen](https://github.com/DIEHARDave/FLSUN_RemoteScreen) or [FLSUN_Updater](https://github.com/DIEHARDave/FLSUN_Updater) is already installed, since each of them makes the same fixes):

   ```sh
   sudo ntpdate -u -b time.google.com
   curl -fsSL --cacert /etc/ssl/certs/ca-certificates.crt https://raw.githubusercontent.com/DIEHARDave/FLSUN_notify/main/prepare.sh | bash
   ```

   Don't use `timedatectl set-ntp true`: on this image it stops the time service rather than starting it.

2. Download and install the plugin while the printer is idle:

   ```sh
   cd ~
   git clone https://github.com/DIEHARDave/FLSUN_notify.git
   ~/FLSUN_notify/install.sh
   ```

The installer restarts Moonraker and Klipper. It is safe to run again, for example after a FLSun firmware update that resets your config.

## Set up

1. In Mainsail or Fluidd, open the config files and edit `flsun_notify.txt`:

   ```ini
   [notify]
   url: tgram://{bottoken}/{ChatID}
   name: {printer_name}
   ```

   Replace `url` with your service's [Apprise URL](https://github.com/caronc/apprise/wiki) and `name` with your printer's name. Don't remove the `url:` line.

2. Save, then run `UPDATE_NOTIFY` in the console. Moonraker restarts, and after about 20 seconds you should get the message "Notifications are set up". Saving the file alone changes nothing; until you run `UPDATE_NOTIFY`, the console reminds you that the changes aren't in use.

3. To send a test message at any time, run `_NOTIFY MSG=Test` in the console.

Moonraker keeps the URL in `~/printer_data/moonraker.secrets`, which Mainsail and Fluidd can't show. `flsun_notify.txt` is the copy you edit; `UPDATE_NOTIFY` copies it over.

### Telegram

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, pick any name, then a username ending in `_bot`.
2. BotFather replies with a token like `1234567890:AAAAAAAABBBBBBBBBBCCCCCCCDDDEEEEEEE`. Put it in place of `{bottoken}`.
3. **Find your new bot in Telegram and send it any message**; it can't message you until you do.
4. Message [@userinfobot](https://t.me/userinfobot) and send `/start`. It replies with your ID, like `123456789`. Put it in place of `{ChatID}`.

The finished file looks like this:

```ini
[notify]
url: tgram://1234567890:AAAAAAAABBBBBBBBBBCCCCCCCDDDEEEEEEE/123456789
name: My T1 Pro
```

### Discord

In your Discord server, open the channel's settings → Integrations → Webhooks → New Webhook, then **Copy Webhook URL** and paste it as `url` unchanged:

```ini
[notify]
url: https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz
name: My T1 Pro
```

With a Discord webhook, FLSUN_notify sends Discord embeds laid out like [FlashForgeUI](https://github.com/Parallel-7/FlashForgeUI-Electron)'s instead of plain text: a colored card with the status, nozzle and bed temperatures, and while printing a progress bar, print time, ETA, layer and file name, with the camera photo inside the card. A finished print gets a "✅ Print Complete!" card with the total time. Your own `_NOTIFY` text, a runout warning or "Printer on" appears at the top of the card.

The layer number is worked out from the nozzle height, because FLSun's Klipper doesn't report layers; the ETA uses the slicer's time estimate and shows in each reader's own time zone. If Discord rejects an embed, the message is sent as plain text instead. To always get plain text, add this to `flsun_notify_custom.conf` and restart Moonraker:

```ini
[flsun_notify]
discord_embeds: False
```

The `body:` text of Moonraker's notifiers isn't used for embeds, so changes to it in `flsun_notify_custom.conf` only show up with `discord_embeds: False` or on other services.

### Other services

For other services (Matrix, ntfy, Pushover, e-mail and more), see the [Apprise URL list](https://github.com/caronc/apprise/wiki). The [Zmod notify README](https://github.com/ghzserg/notify#matrix-setup-example) has a worked Matrix example.

## Settings

### Switches

Set these in the console. They're stored in Klipper's saved variables, so they survive a reboot.

| Command | Effect |
| :--- | :--- |
| `SAVE_VARIABLE VARIABLE=notify_percent VALUE=5` | Progress message every 5% (any whole number from 1 to 99; 0 turns it off) |
| `SAVE_VARIABLE VARIABLE=notify_photo VALUE=0` | No photos on FLSUN_notify's messages (1 turns them back on) |
| `SAVE_VARIABLE VARIABLE=notify_on VALUE=0` | No "Printer on" message |
| `SAVE_VARIABLE VARIABLE=notify_filament VALUE=0` | No filament runout message |

Progress messages look like `benchy.gcode (25%) | 219.8/220.0°C | 60.1/60.0°C` (nozzle, then bed: current/target).

### Moonraker's print notifications

The start, finish, error, cancel, pause and resume messages come from Moonraker. To change or turn one off, add a section to `flsun_notify_custom.conf`, then restart Moonraker:

```ini
[notifier print_start]
events: none
```

The names are `print_start`, `print_complete`, `print_error`, `print_cancelled`, `print_paused` and `print_resumed`. To send one without a photo, add an empty `attach:` line instead. The installer creates this file once and never overwrites it.

## Use in G-code

`_NOTIFY` sends a message from a macro or from your slicer's G-code:

```
_NOTIFY MSG="Bed is hot, starting" PHOTO=0
```

- `MSG`: the text to send.
- `PHOTO`: `1` attaches a camera snapshot (default), `0` doesn't.
- `TYPE` (optional): a name for a switch. `TYPE=door` is skipped while `notify_door` is 0, so you can mute your own message types the same way as the built-in ones.

## How it differs from Zmod's plugin

- Zmod calls the notification macros from its own print and sensor macros. FLSun's macros don't, so a small Moonraker component (`flsun_notify`) watches Klipper's status and sends the progress, filament runout and "Printer on" messages itself, with the same switches. FLSun's `printer.cfg` isn't changed apart from one `[include]` line.
- "Printer on" is sent when Klipper becomes ready within 5 minutes of a boot, so restarting Klipper or Moonraker later doesn't send it.
- Zmod sends "The printer has finished printing" from `END_PRINT` (switch `notify_end`). Here Moonraker's own finished message covers it.
- Zmod's `UPDATE_NOTIFY` reboots the printer. Here the component only restarts Moonraker.
- Messages are in English only for now.

## Files

| Path | What it is |
| :--- | :--- |
| `~/printer_data/config/flsun_notify.txt` | Your URL and printer name. Kept on uninstall. |
| `~/printer_data/config/flsun_notify_custom.conf` | Your Moonraker overrides. |
| `~/printer_data/config/flsun_notify.cfg` | Link to the Klipper macros; included from `printer.cfg`. |
| `~/printer_data/config/flsun_notify.conf` | Link to the Moonraker notifiers; included from `moonraker.conf`. |
| `~/printer_data/moonraker.secrets` | Moonraker's copy of the URL and name, written by `UPDATE_NOTIFY`. |

Updates come through Mainsail's and Fluidd's update manager (`flsun_notify`).

## Uninstall

```sh
~/FLSUN_notify/uninstall.sh
rm -rf ~/FLSUN_notify
```

The uninstaller keeps `flsun_notify.txt` and the clock-sync service from step 1.

## Credits

Based on [notify](https://github.com/ghzserg/notify) by ghzserg (Sergei Rozhkov), part of [Zmod](https://github.com/ghzserg/zmod). Notifications are sent by [Moonraker](https://github.com/Arksine/moonraker)'s notifier and [Apprise](https://github.com/caronc/apprise). Licensed under the GNU GPLv3, the same as the original.
