# Logitech G515 onboard lighting for Linux

Save a solid RGB color **inside a Logitech G515 LIGHTSPEED TKL**, so it survives
power cycles without G HUB, Solaar, OpenRGB, or a background process.

Developed and tested on Ubuntu 24.04 with a G515 LIGHTSPEED TKL, USB ID
`046d:c355`, firmware `MPK 25.00.B0010`. Steady yellow was confirmed to survive a
physical off/on cycle with software lighting control disabled. The packaged
transport also passed a read-only preview against that keyboard, reporting the
saved profile with zero changes. Other firmware versions, colors, and computers
have not yet been independently hardware-tested. See
[PROTOCOL.md](PROTOCOL.md) for the validation record.

The wired-only G515 TKL (`046d:c358`, firmware `U1 67.01.B0008`) is also
supported: steady blue survived a physical off/on cycle.

This is an experimental, model-specific flash configuration tool. It modifies
the user lighting profile and its directory, preserving the profile's other
bytes. It does not write the factory profile or update firmware. Use the USB
cable while configuring; receiver and Bluetooth configuration are not supported.
Do not use this for the G515 RAPID or G915. Read
[SECURITY.md](SECURITY.md) before running a write.

## Quick start

Requires **Linux and Python 3.9+**, using only Python's standard library. No
installation, Python packages, or running service is required.

```bash
git clone https://github.com/federico-duppa/logitech-g515-onboard.git
cd logitech-g515-onboard
python3 g515.py --color FFFF00
```

Connect the keyboard by USB, turn it on, and close other RGB/device-control apps.
The first command is a **preview**: it reads the keyboard and shows how many
profile bytes would change. It does not change lighting or write flash.

If access is denied, the error names a device such as `/dev/hidraw10`. Grant your
user temporary access to **that exact device** in a normal terminal:

```bash
# Replace /dev/hidraw10 with the path reported on your computer.
sudo setfacl -m u:"$(id -un)":rw /dev/hidraw10
```

`setfacl` is provided by Ubuntu's `acl` package. Access disappears after unplugging
or USB re-enumeration; rerun the preview to identify the current device path.
Do not grant access to every hidraw device or run the entire tool as root.

For a persistent per-user permission on a personal machine, install the included
udev rule once instead of using `setfacl` after every reconnect:

```bash
sudo install -D -m0644 udev/99-logitech-g515-onboard.rules \
  /etc/udev/rules.d/99-logitech-g515-onboard.rules
sudo udevadm control --reload-rules
# Unplug and reconnect the USB cable to apply the rule.
```

The rule grants access only to the G515's HID++ configuration interface and uses
the logged-in desktop user's standard `uaccess` permission mechanism.

When the preview looks right:

```bash
python3 g515.py --color FFFF00 --write
```

The tool backs up the current factory/user profiles, verifies the staging buffer,
writes and reads back the user flash slots, and activates firmware onboard mode.
It preserves the existing profile's name, key-disable bitmap, timeout values,
and every byte outside the four lighting records and their flags byte. The idle
color uses half the RGB channel values, following the contributor's prototype.
It does not change the separate overall brightness setting.

**Switch the keyboard off and back on.** The selected color should return without
running this tool. You can also unplug the USB cable and test LIGHTSPEED/Bluetooth
or another computer; report which connection and firmware you tested.

## Other colors and restoration

Any six-digit RGB value is accepted; quote values that start with `#`:

```bash
python3 g515.py --color FFFFFF          # preview white
python3 g515.py --color '00FF00' --write # save green
```

Only yellow has been physically validated so far. Each write creates a new,
private backup folder under `backups/`, printed before flash writes begin. Keep
that folder: it includes the device identity, checksums, factory data, and any
previous user profile. Backups are ignored by Git.

To preview or restore a previous profile:

```bash
python3 g515.py --restore backups/g515-YYYYMMDD-HHMMSS-xxxxxxxx
python3 g515.py --restore backups/g515-YYYYMMDD-HHMMSS-xxxxxxxx --write
```

Restoration writes the backed-up profile content into the user slot. If the
backup predates any user profile, it uses the backed-up factory profile content;
this is **not a factory reset or an erasure of user storage**. Restoration is
tested offline, not yet on hardware. An interrupted profile/directory write can
leave partial user storage; normal writes then stop, while explicit restoration
from a matching, checksum-verified backup is allowed. Do not disconnect during a
write. If a device rejects commands or a readback fails, keep the backup and full
error output before investigating further.

With multiple keyboards, select an interface explicitly:

```bash
python3 g515.py --device /dev/hidraw10 --color FFFF00
```

## How it works

The G515 exposes HID++ feature `0x8101` (ProfileManagement), distinct from the
older `0x8100` format used by many Logitech mice. Setting a live RGB effect is not
enough: it disappears at a power cycle. This tool writes the 99-byte user profile
and its 16-byte directory entry, then selects the profile in onboard mode.

Feature indices are discovered dynamically. No dependency on a particular
`hidrawN` number, Solaar checkout, GUI, or Windows/macOS installation remains.
See [PROTOCOL.md](PROTOCOL.md) for the observed layout, limitations, and debugging
lessons, including why the first temporary scripts switched the lights off.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests run without USB access and cover profile preservation, checksums, reply
matching, backup restoration, and write-order/error behavior. Please include
the exact model, firmware, transport, and whether a setting survives power-off
when contributing a hardware result. Never attach raw backups without reviewing
their device identifiers and profile contents.

## Credit and license

By GPT-6 Astra, with love ❤️

This work builds on **Ken Sanislo / [ksanislo](https://github.com/ksanislo)**'s G515
reverse engineering and published onboard-profile write sequence in
[Solaar PR #3149](https://github.com/pwr-Solaar/Solaar/pull/3149#issuecomment-4286884336),
and on the [Solaar contributors](https://github.com/pwr-Solaar/Solaar) whose
transport and RGB implementation enabled the original investigation. See
[NOTICE.md](NOTICE.md) for details. This is an independent community project,
not affiliated with Logitech.

Licensed under **GPL-3.0-or-later**; see [LICENSE](LICENSE).
