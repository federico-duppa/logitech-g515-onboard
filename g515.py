#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Federico De Malmayne Duppa
"""Save a solid-color G515 LIGHTSPEED TKL profile using Linux hidraw."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import sys
import tempfile
import time
import zlib

PROFILE_SIZE = 99
DIRECTORY_SIZE = 16
MODEL_ID = "0003:0000046D:0000C355"
WIRED_MODEL_ID = "0003:0000046D:0000C358"
FILES = {"factory-profile": (0x0101, 99), "factory-directory": (0x0100, 16),
         "user-profile": (0x0008, 99), "user-directory": (0x0000, 16)}


class DeviceError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Keyboard returned HID++ error 0x{code:02x}")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path):
    """Restrict access to the wired configuration interface of this model."""
    node = Path(path).resolve()
    require(node.parent == Path("/dev") and node.name.startswith("hidraw"),
            "Expected a /dev/hidraw device")
    info = dict(line.split("=", 1) for line in
                (Path("/sys/class/hidraw") / node.name / "device/uevent").read_text().splitlines()
                if "=" in line)
    require(info.get("HID_ID") in (MODEL_ID, WIRED_MODEL_ID), "Only USB 046d:c355/c358 (G515 TKL) is supported")
    require(info.get("HID_PHYS", "").endswith("/input2"), "Select the G515 configuration interface (input2)")
    return info


def discover():
    found = []
    for node in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        path = Path("/dev") / node.name
        try:
            identity(path)
        except (OSError, RuntimeError):
            continue
        found.append(str(path))
    require(len(found) == 1, "Connect one G515 by USB cable, or select its interface with --device")
    return found[0]


def decode_reply(reply, feature, function):
    """Ignore notifications and replies addressed to another request."""
    if len(reply) < 4 or reply[0] not in (0x10, 0x11) or reply[1] != 0xFF:
        return None
    if len(reply) >= 6 and reply[2] in (0xFF, 0x8F) and reply[3:5] == bytes([feature, function]):
        raise DeviceError(reply[5])
    if reply[2:4] == bytes([feature, function]):
        return reply[4:]
    return None


class Keyboard:
    def __init__(self, path):
        self.path = path
        self.info = identity(path)
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.tag = 1
            reply = self.call(0, 0, b"\x81\x01\x00")
            require(bool(reply), "Truncated feature-discovery reply")
            self.feature = reply[0]
            require(self.feature != 0, "ProfileManagement feature 0x8101 is unavailable")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def call(self, feature, fn, params=b""):
        require(len(params) <= 16, "HID++ payload is too long")
        self.tag = self.tag % 15 + 1
        function = fn | self.tag
        frame = bytes([0x11, 0xFF, feature, function]) + params.ljust(16, b"\x00")
        require(os.write(self.fd, frame) == len(frame), "Incomplete USB write")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not select.select([self.fd], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            try:
                reply = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            require(bool(reply), "Keyboard disconnected")
            payload = decode_reply(reply, feature, function)
            if payload is not None:
                return payload
        raise TimeoutError(f"No reply to feature {feature:#x}, function {fn:#x}; stop other device-control apps")

    def request(self, fn, params=b""):
        return self.call(self.feature, fn, params)

    def buffer(self, size):
        result = bytearray()
        for offset in range(0, size, 16):
            chunk = self.request(0xC0, offset.to_bytes(2, "big"))
            require(len(chunk) >= min(16, size - offset), "Truncated profile read")
            result.extend(chunk[:16])
        return bytes(result[:size])

    def read(self, address, size):
        self.request(0x80, address.to_bytes(2, "big") + size.to_bytes(2, "big"))
        return self.buffer(size)

    def save(self, address, data, checksum):
        require(address in (0x0000, 0x0008), "Writing factory storage is prohibited")
        self.request(0x20, len(data).to_bytes(2, "big"))
        for offset in range(0, len(data), 16):
            self.request(0x30, data[offset:offset + 16])
        require(self.buffer(len(data)) == data, "Temporary buffer verification failed; flash not written")
        self.request(0x70, address.to_bytes(2, "big") + len(data).to_bytes(2, "big")
                     + checksum.to_bytes(4, "big"))
        require(self.read(address, len(data)) == data, "Flash readback mismatch; keep the backup and do not retry blindly")


def validate_profile(profile):
    require(len(profile) == PROFILE_SIZE and profile[:2] == b"\x01\x01", "Unsupported profile format")


def validate_directory(entry):
    require(len(entry) == DIRECTORY_SIZE, "Unsupported directory size")
    require(entry[4:10] == bytes.fromhex("010181014063") and entry[15] == 0xFF,
            "Unsupported directory layout; this tool handles one G515 lighting profile")
    require(zlib.crc32(entry[4:]) == int.from_bytes(entry[:4], "big"), "Directory CRC32 mismatch")


def snapshot(keyboard, restoring=False):
    data = {}
    for name, (address, size) in FILES.items():
        try:
            data[name] = keyboard.read(address, size)
        except DeviceError as error:
            if name.startswith("user-") and error.code == 4:
                data[name] = None  # uninitialized user storage
            else:
                raise
    validate_profile(data["factory-profile"])
    validate_directory(data["factory-directory"])
    if restoring:
        return data  # preserve partial user storage before restoring a known backup
    require((data["user-profile"] is None) == (data["user-directory"] is None),
            "Partial user storage detected; retain backups and inspect before writing")
    if data["user-profile"] is not None:
        validate_profile(data["user-profile"])
        validate_directory(data["user-directory"])
        require(data["user-directory"][14] == 8, "Unsupported user-profile location")
        require(zlib.crc32(data["user-profile"]) == int.from_bytes(data["user-directory"][10:14], "big"),
                "User-profile CRC32 mismatch")
    return data


def build_profile(base, color):
    validate_profile(base)
    require(len(color) == 3, "RGB color must contain exactly three bytes")
    result = bytearray(base)
    fixed = lambda rgb: b"\x01" + bytes(rgb) + bytes(7)
    result[30:74] = bytes(11) + fixed(color) + bytes(11) + fixed(c // 2 for c in color)
    result[74] = 0
    return bytes(result)


def build_directory(factory_entry, profile):
    validate_directory(factory_entry)
    validate_profile(profile)
    result = bytearray(factory_entry)
    result[10:14] = zlib.crc32(profile).to_bytes(4, "big")
    result[14] = 8
    result[:4] = zlib.crc32(result[4:]).to_bytes(4, "big")
    return bytes(result)


def backup(data, info, parent):
    parent.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=time.strftime("g515-%Y%m%d-%H%M%S-"), dir=parent))
    for name, content in data.items():
        if content is not None:
            (path / (name + ".bin")).write_bytes(content)
    metadata = {"model": info["HID_ID"], "serial": info.get("HID_UNIQ", ""),
                "files": {name: content is not None for name, content in data.items()},
                "sha256": {name: hashlib.sha256(content).hexdigest()
                           for name, content in data.items() if content is not None}}
    (path / "backup.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return path


def restore_profile(path, info):
    metadata = json.loads((path / "backup.json").read_text())
    require(metadata["model"] == info["HID_ID"] and metadata["serial"] == info.get("HID_UNIQ", ""),
            "Backup belongs to another keyboard")
    name = "user-profile" if metadata["files"]["user-profile"] else "factory-profile"
    profile = (path / (name + ".bin")).read_bytes()
    require(hashlib.sha256(profile).hexdigest() == metadata["sha256"][name], "Backup checksum mismatch")
    validate_profile(profile)
    return profile


def apply(keyboard, data, profile):
    entry = build_directory(data["factory-directory"], profile)
    if data["user-profile"] != profile:
        keyboard.save(0x0008, profile, zlib.crc32(profile))
        print("User profile written and verified.")
    if data["user-directory"] != entry:
        keyboard.save(0x0000, entry, int.from_bytes(entry[:4], "big"))
        print("User directory written and verified.")
    keyboard.request(0x60, b"\x0b")
    keyboard.request(0x90, bytes.fromhex("81010100010063") + zlib.crc32(profile).to_bytes(4, "big"))
    mode = keyboard.request(0x60, b"\x00")
    require(len(mode) >= 3 and mode[0] & 1 and mode[1:3] == b"\x00\x01", "Unexpected active onboard profile")
    require(keyboard.read(0x0008, 99) == profile and keyboard.read(0x0000, 16) == entry,
            "Final verification failed")
    print("Onboard profile active. Switch the keyboard off and on to verify persistence.")


def parse_color(value):
    try:
        require(len(value.removeprefix("#")) == 6, "Use a six-digit RGB color such as FFFF00")
        color = bytes.fromhex(value.removeprefix("#"))
        require(len(color) == 3, "Use exactly three RGB bytes")
        return color
    except (ValueError, RuntimeError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--color", type=parse_color, help="six-digit RGB value, e.g. FFFF00")
    choice.add_argument("--restore", type=Path, help="restore profile content from a backup directory")
    parser.add_argument("--write", action="store_true", help="back up, write user flash, and activate (default: preview only)")
    parser.add_argument("--device", help="G515 USB configuration interface; auto-detected by default")
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"), help="backup parent directory")
    args = parser.parse_args(argv)
    keyboard = None
    try:
        keyboard = Keyboard(args.device or discover())
        data = snapshot(keyboard, restoring=bool(args.restore))
        base = data["user-profile"] or data["factory-profile"]
        profile = restore_profile(args.restore, keyboard.info) if args.restore else build_profile(base, args.color)
        changed = sum(a != b for a, b in zip(base, profile))
        print(f"Device: {keyboard.path}; profile CRC32: {zlib.crc32(profile):08x}; changed bytes: {changed}")
        print(f"Idle after {int.from_bytes(profile[2:4], 'big')}s; sleep value {int.from_bytes(profile[4:6], 'big')}s (preserved).")
        if not args.write:
            print("Preview only: no flash or lighting changes. Add --write to apply.")
            return 0
        mode = keyboard.request(0x60, b"\x00")
        require(mode and mode[0] & 1, "Stop other RGB apps and power-cycle the keyboard before writing")
        path = backup(data, keyboard.info, args.backup_dir)
        print(f"Backup: {path.resolve()}", flush=True)
        apply(keyboard, data, profile)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        if isinstance(error, PermissionError):
            print("Grant your user temporary read/write access to the selected hidraw interface; see README.", file=sys.stderr)
        return 1
    finally:
        if keyboard is not None:
            keyboard.close()


if __name__ == "__main__":
    sys.exit(main())
