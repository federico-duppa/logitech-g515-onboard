# Attribution

The G515 ProfileManagement save sequence and fixed-color effect-slot selection
were established by Ken Sanislo (`ksanislo`) and shared in the discussion of
[Solaar PR #3149](https://github.com/pwr-Solaar/Solaar/pull/3149).
The starting reference was the
[`set_color.py` attachment](https://github.com/user-attachments/files/26924643/set_color.py).
Its unpublished `dryrun_build_profile` dependency is not included here. We do not
redistribute the attachment; this implementation reconstructs the needed profile
and directory records from the connected keyboard's factory data.

Solaar (GPL-2.0-or-later), originally by Daniel Pavel and maintained by its
contributors, supplied the HID++ transport and RGB code used in the initial
working prototype. The public tool replaces that runtime dependency with a
standard-library Linux hidraw transport. HID++ reply matching and error handling
were cross-checked against Solaar's `logitech_receiver/base.py`.

This project's contributions include the working persistent-yellow device result,
reconstruction and verification of the profile/directory changes, dynamic
feature discovery for this firmware, the reusable tool, automatic backups,
tests, and documentation. Credit for the earlier protocol research remains with
its authors. No Logitech binaries or private device backups are distributed.
