"""Tests for finding disks and free space on the gameserver.

The motivating case: a server with a second 1 TB drive that was never
formatted. `df` cannot see it, so `lsblk` has to surface it as spare capacity.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gameservers as gs  # noqa: E402

GB = 1024 ** 3

# sda: 240G system disk, partitioned and mounted. sdb: 1TB, untouched.
LSBLK = '\n'.join([
    'NAME="sda" SIZE="256060514304" TYPE="disk" FSTYPE="" LABEL="" MOUNTPOINT="" MODEL="KINGSTON SA400"',
    'NAME="sda1" SIZE="1073741824" TYPE="part" FSTYPE="vfat" LABEL="EFI" MOUNTPOINT="/boot/efi" MODEL=""',
    'NAME="sda2" SIZE="254986772480" TYPE="part" FSTYPE="ext4" LABEL="root" MOUNTPOINT="/" MODEL=""',
    'NAME="sdb" SIZE="1000204886016" TYPE="disk" FSTYPE="" LABEL="" MOUNTPOINT="" MODEL="WDC WD10EZEX"',
    'NAME="sr0" SIZE="1073741312" TYPE="rom" FSTYPE="" LABEL="" MOUNTPOINT="" MODEL="DVD-ROM"',
])

DF = '\n'.join([
    "Filesystem     Type   1B-blocks        Used       Avail Use% Mounted on",
    "/dev/sda2      ext4  254986772480 180000000000 62000000000  75% /",
    "/dev/sda1      vfat    1073741824    12000000  1061741824   2% /boot/efi",
])


def test_lsblk_parses_every_device():
    devs = gs._parse_lsblk(LSBLK)
    assert len(devs) == 5
    sdb = next(d for d in devs if d["name"] == "sdb")
    assert sdb["size_bytes"] == 1000204886016
    assert sdb["model"] == "WDC WD10EZEX"
    assert sdb["fstype"] == "" and sdb["mountpoint"] == ""


def test_finds_the_unformatted_terabyte():
    devs = gs._parse_lsblk(LSBLK)
    spare = gs.unused_disks(devs)
    assert [d["name"] for d in spare] == ["sdb"]
    assert round(spare[0]["size_bytes"] / GB) == 932   # 1 TB as the OS counts it


def test_system_disk_is_not_reported_as_spare():
    """sda has mounted partitions - offering to format it would be destructive."""
    spare = gs.unused_disks(gs._parse_lsblk(LSBLK))
    assert "sda" not in [d["name"] for d in spare]


def test_optical_drive_is_not_spare_capacity():
    assert "sr0" not in [d["name"] for d in gs.unused_disks(gs._parse_lsblk(LSBLK))]


def test_df_parses_free_space():
    fs = gs._parse_df(DF)
    assert len(fs) == 2
    root = next(f for f in fs if f["mount"] == "/")
    assert root["avail_bytes"] == 62000000000
    assert root["use_pct"] == "75%"


def test_df_handles_mountpoints_containing_spaces():
    line = ("Filesystem Type 1B-blocks Used Avail Use% Mounted on\n"
            "/dev/sdc1 ext4 100 40 60 40% /mnt/game data")
    assert gs._parse_df(line)[0]["mount"] == "/mnt/game data"


def test_df_skips_malformed_rows():
    assert gs._parse_df("hdr\n/dev/sda2 ext4 notanumber 1 2 3% /") == []


# ------------------------------------------------------------ fits() -------
def report(**kw):
    r = {"filesystems": gs._parse_df(DF),
         "unused_disks": gs.unused_disks(gs._parse_lsblk(LSBLK))}
    r.update(kw)
    return r


def test_install_fits_when_there_is_room(monkeypatch):
    monkeypatch.setattr(gs, "BASE_DIR", gs.Path("/opt/gameservers"))
    ok, msg = gs.fits(report(), 50 * GB)
    assert ok and "free on /" in msg


def test_install_does_not_fit_and_points_at_the_spare_disk(monkeypatch):
    monkeypatch.setattr(gs, "BASE_DIR", gs.Path("/opt/gameservers"))
    ok, msg = gs.fits(report(), 200 * GB)
    assert not ok
    assert "short" in msg
    assert "/dev/sdb" in msg and "unformatted" in msg


def test_no_spare_disk_means_no_false_suggestion(monkeypatch):
    monkeypatch.setattr(gs, "BASE_DIR", gs.Path("/opt/gameservers"))
    ok, msg = gs.fits(report(unused_disks=[]), 200 * GB)
    assert not ok and "unformatted" not in msg


def test_picks_the_most_specific_mountpoint(monkeypatch):
    """An install root on its own mount must be measured against that mount."""
    monkeypatch.setattr(gs, "BASE_DIR", gs.Path("/boot/efi/x"))
    ok, msg = gs.fits(report(), 50 * GB)
    assert not ok and "/boot/efi" in msg


@pytest.mark.parametrize("n,want", [
    (0, "0 B"), (512, "512 B"), (5 * GB, "5.0 GB"),
    (151 * GB, "151.0 GB"), (1000204886016, "931.5 GB"),
])
def test_human_bytes(n, want):
    assert gs.human_bytes(n) == want
