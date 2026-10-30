"""Windows handle-relative File ID groundwork: offline and genuine host tests."""
import os
from pathlib import PureWindowsPath

import pytest

from scripts import queue_win32_handle_identity as win


def test_parse_absolute_drive_path_without_reinterpreting_ancestors():
    assert win._drive_parts(r"C:\work\item\RUNNING\slice.txt") == (
        "C:", ("work", "item", "RUNNING", "slice.txt")
    )
    assert win._drive_parts(r"c:\work\item") == ("C:", ("work", "item"))


@pytest.mark.parametrize("path", [
    r"C:relative\item", r"..\private\file", r"\relative",
    r"\\server\share\item", r"\\?\C:\item", r"\\.\C:\item",
    r"C:\linked\..\item", r"C:\nonexistent\..\item",
    r"C:\name:secret", "C:\\name\\unsafe\\\x00part",
])
def test_ambiguous_windows_item_paths_are_fail_closed(path):
    with pytest.raises(win.UnsafeWindowsIdentity):
        win._drive_parts(path)


@pytest.mark.parametrize("component", [
    "", ".", "..", "x/y", r"x\y", "a:stream", "name. ",
    "name.", "name ", "any\x00thing", "x" * 256
])
def test_child_native_name_must_be_exact_single_component(component):
    with pytest.raises(win.UnsafeWindowsIdentity):
        win._require_component(component)


def test_relative_native_names_preserve_accepted_unicode():
    for name in ("繁體中文.txt", "Stage_1.txt", ".success-publish-staging"):
        assert win._require_component(name) == name


def test_win_file_id_is_128_bits_not_old_64_bit_indices():
    assert len(win._FileIdInfo().FileId) == 16
    assert win.FILE_ID_INFO_CLASS == 18
    assert win.OBJ_DONT_REPARSE != 0
    assert win.FILE_OPEN_REPARSE_POINT != 0


def test_walk_pins_every_parent_and_releases_in_reverse_on_success():
    actions = []

    class FakeNative:
        def open_drive_root(self, drive):
            assert drive == "C:"
            actions.append(("root", drive))
            return 1

        def open_child(self, parent, name, *, directory):
            actions.append(("child", parent, name, directory))
            return {1: 2, 2: 3, 3: 4}[parent]

        def identity(self, handle):
            assert handle == 4
            return win.HandleIdentity(123, bytes(range(16)), 2, False)

        def close(self, handle):
            actions.append(("close", handle))

    result = win._walk_identity(
        FakeNative(), "C:", ("item", "TODO"), "source.txt",
        leaf_is_directory=False,
    )
    assert result.number_of_links == 2
    assert len(result.file_id) == 16
    assert actions == [
        ("root", "C:"),
        ("child", 1, "item", True),
        ("child", 2, "TODO", True),
        ("child", 3, "source.txt", False),
        ("close", 4), ("close", 3), ("close", 2), ("close", 1),
    ]


def test_walk_closes_all_held_ancestor_handles_when_child_refused():
    actions = []

    class FakeNative:
        def open_drive_root(self, drive):
            return 10

        def open_child(self, parent, name, *, directory):
            if parent == 10:
                return 20
            raise win.UnsafeWindowsIdentity("WINDOWS_REPARSE_POINT_REFUSED")

        def close(self, handle):
            actions.append(handle)

    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_REPARSE_POINT_REFUSED"):
        win._walk_identity(
            FakeNative(), "C:", ("item",), "suspicious",
            leaf_is_directory=False,
        )
    assert actions == [20, 10]


def test_non_windows_probe_fails_closed_without_attempted_path_open():
    if os.name == "nt":
        pytest.skip("native Windows acceptance tested separately")
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_NATIVE_UNAVAILABLE"):
        win.probe_handle_identity("C:\\private\\item")


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows kernel handles")
def test_windows_real_handle_identity_matches_two_hardlinks(tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    a = item / "first.txt"
    b = item / "second.txt"
    a.write_bytes(b"PRIVATE_SOURCE_NOT_READ")
    try:
        os.link(a, b)
    except OSError:
        pytest.skip("hardlinks are unsupported by operator filesystem")
    orig = win.probe_handle_identity(a)
    other = win.probe_handle_identity(b)
    assert orig == other
    assert orig.number_of_links >= 2
    assert not orig.is_directory


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows kernel handles")
def test_windows_real_native_directory_handle_and_type_checks(tmp_path):
    sub = tmp_path / "queue"
    sub.mkdir()
    identity = win.probe_handle_identity(sub, is_directory=True)
    assert identity.is_directory
    assert len(identity.file_id) == 16
    with pytest.raises(win.UnsafeWindowsIdentity):
        win.probe_handle_identity(sub, is_directory=False)


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows kernel handles")
def test_windows_real_native_symlink_refused_without_following(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "secret.txt").write_text("PRIVATE")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("privilege for directory symlink unavailable")
    with pytest.raises(win.UnsafeWindowsIdentity):
        win.probe_handle_identity(alias, is_directory=True)
    with pytest.raises(win.UnsafeWindowsIdentity):
        win.probe_handle_identity(alias / "secret.txt")
