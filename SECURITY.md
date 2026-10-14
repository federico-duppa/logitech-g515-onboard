# Safety and security

This tool writes non-volatile profile data to a keyboard. Treat `--write` as a
device-flashing operation.

- Use the USB cable and confirm the model and firmware before writing.
- Run the preview first. It performs reads only and is the default.
- Close G HUB, Solaar, OpenRGB, and other Logitech/RGB tools before writing.
- Grant access only to the exact G515 `hidraw` interface. Do not run the tool as
  root or grant broad access to every HID device.
- If you install the optional udev rule, inspect it first: it matches Logitech
  USB products `c355`/`c358` and interface `02`, then grants only the active desktop
  user's `uaccess` permission.
- Keep the printed backup directory. It is deliberately ignored by Git because
  it can contain device-specific identifiers and profile data.
- Do not disconnect the cable during either user-flash write.
- The tool refuses factory-storage addresses, verifies staging before flash, and
  verifies both user writes afterward. If a check fails, stop and preserve the
  backup and error output.

The supported model is the USB G515 TKL (`046d:c355`/`c358`, HID++
ProfileManagement `0x8101`). Other devices are rejected. The profile format is
reverse-engineered and not an official Logitech specification.

For a suspected defect that could damage a keyboard, open a GitHub issue without
attaching raw backups. Include the model, firmware, Linux distribution, exact
command (omit personal paths), and the complete error text. For a security issue
in the tool, use GitHub's private vulnerability reporting when enabled; otherwise
contact the maintainer through the repository profile before publishing details.
