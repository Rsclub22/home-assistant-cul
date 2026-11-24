# home-assistant-cul

Home Assistant integration for the busware **CUL** with **culfw**. It talks to the CUL directly, without FHEM.

Supported devices:

- **FHT80b** room thermostats: climate, mode, temperatures, weekly program, holiday, battery, window, actuator.
- **FHT80TF** window contacts: window state, battery, reliability.

The CUL can be plugged into the Home Assistant machine (USB) or into another machine that shares it via ser2net (TCP).

> **Beta.** Tested with a CUL V3 868 MHz (culfw 1.43), three FHT80b and four FHT80TF. Please report problems in the [issues](https://github.com/Rsclub22/home-assistant-cul/issues).

## Why not FHEM any more?

This is the successor of [home-assistant-fht](https://github.com/Rsclub22/home-assistant-fht), which read FHT values from FHEM's web API. That approach had limits:

- The FHEM web API had to be open without a password.
- Every value meant another HTTP request, and nothing could be cached properly.
- FHEM had to run next to Home Assistant just to bridge the radio.

This integration reads the CUL's radio telegrams itself (local push):

- Values appear as soon as a device sends them.
- Commands go through a send queue that respects the CUL's buffer and send limit.
- Pairing FHT80b thermostats works from the Home Assistant UI.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Rsclub22&repository=home-assistant-cul&category=integration)

1. HACS → three-dot menu → *Custom repositories* → add `https://github.com/Rsclub22/home-assistant-cul`, category *Integration*.
2. Download **CUL (culfw)** and restart Home Assistant.

### Manual

Copy `custom_components/cul` into `<config>/custom_components/cul` and restart Home Assistant.

Requires Home Assistant 2026.10 or later.

## Setup

Only one program may own the CUL. Stop FHEM (or anything else using it) first.

### USB

Plug the CUL in. Home Assistant discovers it (busware CUL, USB `03eb:204b`) and offers **CUL found** under *Settings → Devices & services*.

Without discovery, add the integration **CUL (culfw)** and choose **USB / serial**. Prefer the path under `/dev/serial/by-id/`, because it survives reboots. Baud rate 9600; a CUL on a UART (e.g. COC) usually needs 38400.

In a container, pass the device through, e.g. `--device /dev/serial/by-id/usb-busware.de_CUL868-if00`.

### Network (ser2net)

On the machine with the CUL, run ser2net in raw mode with one connection:

```yaml
connection: &cul
  accepter: tcp,2323
  connector: serialdev,/dev/serial/by-id/usb-busware.de_CUL868-if00,9600n81,local
  options:
    max-connections: 1
```

Then add **CUL (culfw)** in Home Assistant, choose **Network (ser2net)** and enter host and port.

### FHT ID

The FHT ID is the CUL's address as FHT central; FHT80b thermostats are paired to it. The integration reads it from the CUL (`T01`).

Only if the CUL has none yet (`0000`), it asks for one and proposes a random ID. It must differ from any other FHT central within radio range.

If your FHT80b were paired to another CUL before, enter that ID (FHEM: attribute `fhtid`), and nothing has to be paired again.

If the CUL moves (e.g. from ser2net to USB), add the integration again. It recognises the CUL by its FHT ID and only updates the connection of the existing entry.

## Pair an FHT80b

An FHT80b only accepts commands from its central. To make the CUL its central:

1. On the FHT80b, hold PROG until `Sond` appears.
2. Turn to `CEnt`, set it to `nA` and confirm with PROG. The thermostat now waits for a central.
3. In the same menu, read code 1 and code 2 under `CodE`, e.g. `028` and `080`.
4. **Beta workaround:** press **Restart** on the CUL device in Home Assistant first (see [Known issues](#known-issues)).
5. On the CUL entry, choose *Configure → Pair FHT80b* and enter code 1 and code 2.

The CUL sends one report request. The FHT80b picks it up within about 2 minutes, confirms it, and `CEnt` switches to `On`. Then the time, weekly program and other values arrive.

The dialog waits up to 15 minutes and may be closed. A notification shows the result. The events are `cul_fht_paired` and `cul_fht_pair_failed`.

You can also use the action `cul.fht_pair` with `code: "028 080"`. 4 hex digits (`1c50`) work too.

### FHT80TF window contacts

Window contacts are paired to their FHT80b, not to the CUL. The CUL hears them anyway, and they show up as their own devices right away.

1. On the FHT80b, hold PROG until `Sond` appears.
2. Turn to `FEn` and press PROG.
3. Choose a free slot (`nA`).
4. Hold FUNKTION until `CodE` appears.
5. Press the button on the contact until its LED lights. The FHT80b shows `EA`; press PROG.

The FHT80b may take up to 20 minutes to report an open window to the central.

## Migrating from home-assistant-fht (FHEM)

1. Back up `.storage/core.entity_registry` and `.storage/core.device_registry`.
2. When adding the integration, enable **Take over fht_heating entities**.

This only happens during the first setup. The `cul` entry takes over the `fht_heating` entities, keeping entity IDs, names, areas and customisations, and disables the old entry. Then stop FHEM and let the integration own the CUL.

Rollback: stop Home Assistant, restore the two backed-up files, start FHEM again, start Home Assistant.

## Actions and events

| Action | Purpose |
|---|---|
| `cul.fht_pair` | Pair an FHT80b |
| `cul.fht_set_holiday` | Holiday mode with end and temperature |
| `cul.fht_set_schedule` | Weekly program of one day |
| `cul.fht_refresh` | Ask the FHT80b to report its values |
| `cul.fht_sync_time` | Set the FHT80b clock |
| `cul.fht_report` | Send report requests |
| `cul.send_raw` | Raw culfw command, admins only. `T01…` needs `confirm: true` |

Event `cul_command_failed` fires when an FHT80b does not confirm a command within 15 minutes.

Commands are only sent to FHT80b heard recently (default 2 hours, configurable). Otherwise they would fill the CUL's FHT buffer, because culfw holds them until the thermostat picks them up.

## Known issues

- **Stuck commands in the CUL (culfw 1.43).** While an FHT80b is set to `CEnt nA`, a stray entry such as `1C50:00A6,10FB` showed up at the front of the CUL's FHT buffer, and the thermostat never picked up the commands behind it. Pressing **Restart** on the CUL (`B00`) clears the buffer. Until this is handled automatically, restart the CUL before pairing.
- Only FHT80b and FHT80TF are supported so far. Want another culfw device (FS20, EM, HMS …)? See [Adding a device type](CONTRIBUTING.md#adding-a-device-type); telegrams from real hardware help most.

## Troubleshooting

Log every line to and from the CUL (`<-` / `->`):

```yaml
logger:
  logs:
    custom_components.cul: debug
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-3.0, see [LICENSE](LICENSE). culfw is by Rudolf Koenig and contributors.
