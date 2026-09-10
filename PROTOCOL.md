# Observed G515 profile protocol

These notes describe one tested G515 LIGHTSPEED TKL, firmware MPK 25.00.B0010,
on Ubuntu 24.04. They are observations, not an official Logitech specification.

## Hardware validation

The original Solaar-based prototype successfully:

1. Read the factory profile and directory.
2. Staged and read back the new profile in RAM.
3. Saved and read back both user flash records.
4. Activated the user profile with software RGB control off.
5. Produced steady yellow that the owner confirmed survived a physical off/on
   cycle on 2026-09-10, without a lighting app running.

The standalone tool uses the same profile bytes and command sequence. Its
hardware validation is recorded separately below to avoid implying every code
path has been exercised against the device. Restoration and error paths are
covered by offline tests; other models/firmware are not certified.

The standalone builder was compared byte-for-byte with the successfully saved
yellow profile and directory: both match exactly. Its 17 offline tests pass on
Python 3.12. After restoring the temporary hidraw ACL, the standalone USB
transport passed a read-only preview against the same keyboard, reporting the
saved profile with zero changes. The ACL was removed by USB re-enumeration before
that check; the optional udev rule avoids this on a configured personal machine.

## Transport and storage

- USB VID/PID: `046d:c355`, configuration interface `input2`.
- HID++ device address: `0xff`; long report: `0x11`, 20 bytes total.
- Discover feature `0x8101` with a root query. It was index `0x0e` on the tested
  firmware; the contributor's prototype used `0x0f`. Never hard-code this index.
- Profile size: 99 bytes; directory entry: 16 bytes.
- Factory profile: `0x0101`; factory directory: `0x0100` (read only in this tool).
- User profile: `0x0008`; user directory: `0x0000`.
- Uninitialized user records returned HID++ error `0x04` on read.

## Profile layout used here

| Offset | Length | Treatment |
| --- | --- | --- |
| 0 | 2 | Expected header `01 01`, preserved |
| 2 | 2 | Idle value, big endian, preserved (60 on tested keyboard) |
| 4 | 2 | Sleep value, big endian, preserved (300 on tested keyboard) |
| 6 | 24 | Name area, preserved |
| 30 | 44 | Four 11-byte lighting records |
| 74 | 1 | Lighting flags, changed to `00` for the parameter path |
| 75 | 16 | Disabled-control bitmap, preserved |
| 91 | 8 | Remaining bytes, preserved |

For a fixed color, records 0 and 2 are all zero; record 1 is
`01 RR GG BB 00 00 00 00 00 00 00`. Record 3 uses the same format with each RGB
channel divided by two, rounded down. This slot choice follows the contributor's
profile writer. The factory profile instead had effects `0x18` and `0x19` in
records 0 and 2 and flags `03`.

The directory is cloned from the factory entry. Its own CRC32 covers bytes 4–15
and is stored big endian at 0–3. Bytes 4–9 must match `01 01 81 01 40 63`; byte 15
must be `ff`. We put CRC32 of the full new profile at 10–13, set byte 14 to `08`
(user-profile location per the reference writer), and recalculate the entry CRC.

**Unresolved factory detail:** the profile-hash field in the factory directory
did not equal CRC32 of the 99 bytes read from the factory profile. The directory's
own CRC did validate. We did not change the factory records. A freshly calculated
CRC32 was accepted for the new user profile and its complete readback matched.
The tool validates user-profile CRCs but does not pretend the factory discrepancy
has been explained.

## Save sequence

All function numbers below are the high nibble; the low nibble is a request tag.

1. `0x20`: start a write buffer with big-endian 16-bit length.
2. `0x30`: append data in chunks of up to 16 bytes.
3. `0xc0`: read buffer at big-endian 16-bit offsets; verify before flash writes.
4. `0x70`: save `[address:u16, length:u16, checksum:u32]`, all big endian.
5. `0x80`: load `[address:u16, length:u16]`, then `0xc0` to verify flash readback.

Save the profile at `0x0008` with its full CRC32, then the directory at `0x0000`
with the CRC stored in its first four bytes. After both verify:

- `0x60`, payload `0b`: onboard mode.
- `0x90`, payload `81 01 01 00 01 00 63` followed by the profile CRC32: configure.
- `0x60`, payload `00`: read mode. The tested firmware returned `03 00 01`.

After configure, the last two bytes report logical file ID `0x0001`, rather than
the physical flash slot `0x0008`. An initial check expected `0x0008` and was
corrected after the successful hardware observation.

## Why the earlier temporary approach was insufficient

Sending a live yellow RGB effect under software control worked only until the
next power cycle. It also disabled normal firmware power management. Building
Solaar settings registered a cleanup callback which sent a lighting shutdown
command when the test script exited, briefly displaying yellow and then going
dark. The onboard approach does not take software RGB ownership and does not
register those callbacks.

The two user flash writes are not an atomic transaction. The tool saves a backup
before either write and stops on any unexpected response. A matching backup can
restore profile content after an interrupted write, without touching factory
storage. Disconnect/reconnect may also remove the temporary Linux ACL.
