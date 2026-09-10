import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

import g515


def fixture():
    # Synthetic data: no device serials, names, or raw personal backups.
    profile = bytearray(range(99))
    profile[:6] = bytes.fromhex("0101003c012c")
    entry = bytearray(bytes(4) + bytes.fromhex("010181014063") + bytes(4) + b"\x01\xff")
    entry[:4] = zlib.crc32(entry[4:]).to_bytes(4, "big")
    return bytes(profile), bytes(entry)


class ProfileTests(unittest.TestCase):
    def test_only_lighting_bytes_change(self):
        base, _ = fixture()
        result = g515.build_profile(base, b"\xff\xff\x00")
        self.assertEqual(result[:30], base[:30])
        self.assertEqual(result[75:], base[75:])
        self.assertEqual(result[30:41], bytes(11))
        self.assertEqual(result[41:52], bytes.fromhex("01ffff0000000000000000"))
        self.assertEqual(result[52:63], bytes(11))
        self.assertEqual(result[63:74], bytes.fromhex("017f7f0000000000000000"))
        self.assertEqual(result[74], 0)

    def test_black_and_odd_channels(self):
        base, _ = fixture()
        black = g515.build_profile(base, bytes(3))
        self.assertEqual(black[41:45], bytes.fromhex("01000000"))
        result = g515.build_profile(base, bytes([1, 3, 255]))
        self.assertEqual(result[64:67], bytes([0, 1, 127]))

    def test_directory_checksums_and_address(self):
        base, entry = fixture()
        profile = g515.build_profile(base, bytes.fromhex("abcdef"))
        result = g515.build_directory(entry, profile)
        g515.validate_directory(result)
        self.assertEqual(int.from_bytes(result[10:14], "big"), zlib.crc32(profile))
        self.assertEqual(result[14:], b"\x08\xff")
        self.assertEqual(result[4:10], entry[4:10])

    def test_unknown_or_corrupt_formats_rejected(self):
        base, entry = fixture()
        for invalid in [base[:-1], b"\x02" + base[1:]]:
            with self.assertRaises(RuntimeError):
                g515.build_profile(invalid, bytes(3))
        for invalid in [entry[:-1], bytes([entry[0] ^ 1]) + entry[1:]]:
            with self.assertRaises(RuntimeError):
                g515.build_directory(invalid, base)

    def test_color_parser(self):
        self.assertEqual(g515.parse_color("#FFff00"), b"\xff\xff\x00")
        for value in ["ff ff ", "FFFF", "GGGGGG", "0xFFFF00"]:
            with self.assertRaises(argparse.ArgumentTypeError):
                g515.parse_color(value)


class TransportTests(unittest.TestCase):
    def test_preview_never_backs_up_or_writes(self):
        profile, entry = fixture()
        keyboard = Mock()
        keyboard.path = "/dev/hidraw-test"
        data = {"factory-profile": profile, "factory-directory": entry,
                "user-profile": None, "user-directory": None}
        with patch.object(g515, "Keyboard", return_value=keyboard), \
             patch.object(g515, "snapshot", return_value=data), \
             patch.object(g515, "backup") as backup, \
             patch.object(g515, "apply") as apply:
            self.assertEqual(g515.main(["--device", keyboard.path, "--color", "FFFF00"]), 0)
            backup.assert_not_called()
            apply.assert_not_called()
        keyboard.close.assert_called_once()

    def test_directory_failure_does_not_activate(self):
        profile, entry = fixture()
        keyboard = Mock()
        keyboard.save.side_effect = [None, RuntimeError("directory write failed")]
        data = {"factory-directory": entry, "user-profile": None, "user-directory": None}
        with self.assertRaises(RuntimeError):
            g515.apply(keyboard, data, profile)
        self.assertEqual(keyboard.save.call_count, 2)
        keyboard.request.assert_not_called()

    def test_reply_must_match_device_feature_and_tag(self):
        self.assertEqual(g515.decode_reply(bytes.fromhex("11ff0eab010203"), 14, 0xab), b"\x01\x02\x03")
        for frame in ["11ff0eac010203", "11ff0fab010203", "11010eab010203", "11ff0ea0010203", "00"]:
            self.assertIsNone(g515.decode_reply(bytes.fromhex(frame), 14, 0xab))

    def test_hidpp_errors_are_not_timeouts(self):
        for marker in [0xff, 0x8f]:
            with self.assertRaises(g515.DeviceError) as error:
                g515.decode_reply(bytes([0x11, 0xff, marker, 14, 0xab, 4, 0]), 14, 0xab)
            self.assertEqual(error.exception.code, 4)

    def test_bad_staging_buffer_never_reaches_flash(self):
        keyboard = g515.Keyboard.__new__(g515.Keyboard)
        keyboard.request = Mock()
        keyboard.buffer = Mock(return_value=b"bad")
        with self.assertRaises(RuntimeError):
            keyboard.save(8, bytes(99), 0)
        self.assertNotIn(0x70, [call.args[0] for call in keyboard.request.call_args_list])

    def test_factory_write_prohibited(self):
        keyboard = g515.Keyboard.__new__(g515.Keyboard)
        keyboard.request = Mock()
        with self.assertRaises(RuntimeError):
            keyboard.save(0x0101, bytes(99), 0)
        keyboard.request.assert_not_called()

    def test_profile_failure_stops_directory_and_activation(self):
        profile, entry = fixture()
        keyboard = Mock()
        keyboard.save.side_effect = RuntimeError("verification failed")
        data = {"factory-directory": entry, "user-profile": None, "user-directory": None}
        with self.assertRaises(RuntimeError):
            g515.apply(keyboard, data, profile)
        self.assertEqual(keyboard.save.call_count, 1)
        keyboard.request.assert_not_called()

    def test_identical_profile_skips_flash(self):
        profile, factory_entry = fixture()
        entry = g515.build_directory(factory_entry, profile)
        keyboard = Mock()
        keyboard.request.return_value = bytes.fromhex("030001")
        keyboard.read.side_effect = [profile, entry]
        g515.apply(keyboard, {"factory-directory": factory_entry,
                            "user-profile": profile, "user-directory": entry}, profile)
        keyboard.save.assert_not_called()


class BackupTests(unittest.TestCase):
    def setUp(self):
        profile, entry = fixture()
        self.info = {"HID_ID": g515.MODEL_ID, "HID_UNIQ": "TEST-SYNTHETIC"}
        self.data = {"factory-profile": profile, "factory-directory": entry,
                     "user-profile": None, "user-directory": None}

    def test_unique_backups_and_factory_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            first = g515.backup(self.data, self.info, Path(temp))
            second = g515.backup(self.data, self.info, Path(temp))
            self.assertNotEqual(first, second)
            self.assertEqual(g515.restore_profile(first, self.info), self.data["factory-profile"])
            with self.assertRaises(RuntimeError):
                g515.restore_profile(first, {**self.info, "HID_UNIQ": "DIFFERENT"})

    def test_corrupt_backup_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = g515.backup(self.data, self.info, Path(temp))
            (path / "factory-profile.bin").write_bytes(bytes(99))
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                g515.restore_profile(path, self.info)

    def test_previous_user_profile_is_restored(self):
        profile = g515.build_profile(self.data["factory-profile"], bytes.fromhex("ff0000"))
        self.data["user-profile"] = profile
        self.data["user-directory"] = g515.build_directory(self.data["factory-directory"], profile)
        with tempfile.TemporaryDirectory() as temp:
            path = g515.backup(self.data, self.info, Path(temp))
            self.assertEqual(g515.restore_profile(path, self.info), profile)

    def test_partial_user_storage_requires_explicit_restore(self):
        keyboard = Mock()
        results = [self.data["factory-profile"], self.data["factory-directory"],
                   self.data["factory-profile"], g515.DeviceError(4)]
        keyboard.read.side_effect = results
        with self.assertRaisesRegex(RuntimeError, "Partial"):
            g515.snapshot(keyboard)
        keyboard.read.side_effect = results
        self.assertIsNone(g515.snapshot(keyboard, restoring=True)["user-directory"])


if __name__ == "__main__":
    unittest.main()
