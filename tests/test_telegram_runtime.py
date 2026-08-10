"""Telegram runtime policy and desktop launcher regressions."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts/ubuntu/install.sh"
MARKER = "# Managed by macos-ubuntu-bootstrap: telegram-external-updater-v1"


def _run_policy(home: Path, *, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RLDYOUR_DRY_RUN"] = "1" if dry_run else "0"
    env.pop("XDG_DATA_HOME", None)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"\nrldyour::ubuntu::install_telegram_update_policy',
            "_",
            str(INSTALL),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_desktop_entries(home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RLDYOUR_DRY_RUN"] = "0"
    env["RLDYOUR_GUI_ENABLED"] = "1"
    env.pop("XDG_DATA_HOME", None)
    return subprocess.run(
        [
            "bash",
            "-c",
            (
                'source "$1"\n'
                'install_desktop_entries\n'
                'rldyour::ubuntu::retire_telegram_legacy_managed_entry'
            ),
            "_",
            str(INSTALL),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_desktop_assets(
    home: Path, *, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RLDYOUR_DRY_RUN"] = "1" if dry_run else "0"
    env["RLDYOUR_GUI_ENABLED"] = "1"
    env.pop("XDG_DATA_HOME", None)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"\nrldyour::ubuntu::install_telegram_desktop_assets',
            "_",
            str(INSTALL),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_retire_integrations(home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RLDYOUR_DRY_RUN"] = "0"
    env.pop("XDG_DATA_HOME", None)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"\nrldyour::ubuntu::retire_telegram_generated_integrations',
            "_",
            str(INSTALL),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _managed_telegram(home: Path) -> tuple[Path, Path]:
    real = home / ".local/share/rldyour/telegram/7.0.7/Telegram/Telegram"
    real.parent.mkdir(parents=True)
    real.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    real.chmod(0o755)
    launcher = home / ".local/bin/telegram-desktop"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(real)
    return launcher, real


def test_telegram_policy_lists_launcher_and_receipt_bound_binary(tmp_path: Path) -> None:
    launcher, real = _managed_telegram(tmp_path)
    result = _run_policy(tmp_path)
    assert result.returncode == 0, result.stderr

    policy = (
        tmp_path
        / ".local/share/TelegramDesktop/externalupdater.d/macos-ubuntu-bootstrap"
    )
    assert policy.read_text(encoding="utf-8").splitlines() == [
        MARKER,
        str(launcher),
        str(real),
    ]
    assert policy.stat().st_mode & 0o777 == 0o644

    again = _run_policy(tmp_path)
    assert again.returncode == 0, again.stderr
    assert "already current" in again.stdout


def test_telegram_policy_preserves_unmanaged_file(tmp_path: Path) -> None:
    _managed_telegram(tmp_path)
    policy = (
        tmp_path
        / ".local/share/TelegramDesktop/externalupdater.d/macos-ubuntu-bootstrap"
    )
    policy.parent.mkdir(parents=True)
    policy.write_text("user-owned\n", encoding="utf-8")

    result = _run_policy(tmp_path)
    assert result.returncode != 0
    assert "unmanaged Telegram updater policy differs" in result.stdout
    assert policy.read_text(encoding="utf-8") == "user-owned\n"


def test_telegram_policy_dry_run_needs_no_installed_binary(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, dry_run=True)
    assert result.returncode == 0, result.stderr
    assert "Telegram external-updater policy" in result.stdout
    assert not (tmp_path / ".local/share/TelegramDesktop").exists()


def test_user_tool_install_attempts_telegram_after_an_earlier_failure(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "calls"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["RLDYOUR_DRY_RUN"] = "0"
    env["CALLS_FILE"] = str(calls)
    result = subprocess.run(
        [
            "bash",
            "-c",
            """source "$1"
ensure_pinned_source_tool() {
  printf '%s\n' "${1%%;*}" >>"$CALLS_FILE"
  [ "${1%%;*}" != herdr ]
}
install_user_tools
""",
            "_",
            str(INSTALL),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["herdr", "telegram"]


def test_mandatory_browser_repair_precedes_optional_user_tools() -> None:
    source = INSTALL.read_text(encoding="utf-8")
    main = source.split("main() {", 1)[1]
    assert main.index("rldyour::install_browser_providers") < main.index(
        "if ! install_user_tools"
    )


def test_telegram_favorite_migrates_before_legacy_launchers_are_retired() -> None:
    source = INSTALL.read_text(encoding="utf-8")
    main = source.split("main() {", 1)[1]
    configure = main.index(
        "rldyour::ubuntu::configure_telegram_desktop_integration"
    )
    retire_legacy = main.index(
        "rldyour::ubuntu::retire_telegram_legacy_managed_entry"
    )
    retire_generated = main.index(
        "rldyour::ubuntu::retire_telegram_generated_integrations"
    )
    assert configure < retire_legacy
    assert configure < retire_generated


def test_telegram_desktop_assets_are_pinned_to_the_v707_source_commit() -> None:
    contract = json.loads(
        (ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8")
    )
    desktop = contract["desktop_entries"]["telegram"]
    installer = INSTALL.read_text(encoding="utf-8")

    assert desktop["upstream_source_commit"] == (
        "ee93b401ced86ece3f2582fc2ca4da72dfc4f06a"
    )
    assert len(desktop["icon_assets"]) == 4
    for asset in desktop["icon_assets"]:
        assert asset["source_url"] in installer
        assert asset["sha256"] in installer
        assert asset["target"].split("${HOME}/.local/share/", 1)[1] in installer


def test_telegram_desktop_asset_dry_run_does_not_download(tmp_path: Path) -> None:
    result = _run_desktop_assets(tmp_path, dry_run=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("[DRY-RUN] install pinned Telegram desktop asset") == 4
    assert not (tmp_path / ".local/share/icons").exists()


def test_divergent_telegram_desktop_asset_is_preserved(tmp_path: Path) -> None:
    icon = (
        tmp_path
        / ".local/share/icons/hicolor/256x256/apps/org.telegram.desktop.png"
    )
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"user-owned-icon")

    result = _run_desktop_assets(tmp_path)
    assert result.returncode != 0
    assert "Telegram desktop asset diverged; preserved" in result.stdout
    assert icon.read_bytes() == b"user-owned-icon"


def test_managed_telegram_v1_desktop_entry_is_backed_up_and_migrated(
    tmp_path: Path,
) -> None:
    applications = tmp_path / ".local/share/applications"
    applications.mkdir(parents=True)
    legacy_target = applications / "telegram.desktop"
    target = applications / "org.telegram.desktop.desktop"
    legacy = """[Desktop Entry]
Type=Application
Name=Telegram Desktop
Comment=New era of messaging
# Managed by macos-ubuntu-bootstrap: desktop-entry-telegram-v1
Exec=telegram-desktop -- %U
Icon=telegram
Terminal=false
StartupWMClass=TelegramDesktop
Categories=Chat;Network;InstantMessaging;
MimeType=x-scheme-handler/tg;
Keywords=tg;chat;im;messaging;messenger;
"""
    legacy_target.write_text(legacy, encoding="utf-8")

    result = _run_desktop_entries(tmp_path)
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == (
        ROOT / "templates/desktop/org.telegram.desktop.desktop"
    ).read_text(encoding="utf-8")
    assert not legacy_target.exists()

    backups = list(
        (tmp_path / ".local/share/rldyour/backups/desktop-entries").glob(
            "retired-telegram.*/telegram.desktop"
        )
    )
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == legacy


def test_generated_telegram_integrations_are_retired_recoverably(
    tmp_path: Path,
) -> None:
    launcher, _real = _managed_telegram(tmp_path)
    identity = "org.telegram.desktop._0123456789abcdef0123456789abcdef"
    desktop = tmp_path / f".local/share/applications/{identity}.desktop"
    service = tmp_path / f".local/share/dbus-1/services/{identity}.service"
    desktop.parent.mkdir(parents=True)
    service.parent.mkdir(parents=True)
    desktop.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                f"TryExec={launcher}",
                f"Exec={launcher} -- %U",
                "DBusActivatable=true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    service.write_text(
        "\n".join(
            [
                "[D-BUS Service]",
                f"Name={identity}",
                f"Exec={launcher}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_retire_integrations(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not desktop.exists()
    assert not service.exists()
    backup_dirs = list(
        (tmp_path / ".local/share/rldyour/backups/telegram-integrations").glob(
            "generated.*"
        )
    )
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / desktop.name).is_file()
    assert (backup_dirs[0] / service.name).is_file()


def test_divergent_generated_telegram_integration_is_preserved(
    tmp_path: Path,
) -> None:
    _managed_telegram(tmp_path)
    identity = "org.telegram.desktop._0123456789abcdef0123456789abcdef"
    desktop = tmp_path / f".local/share/applications/{identity}.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text("user-owned\n", encoding="utf-8")

    result = _run_retire_integrations(tmp_path)
    assert result.returncode != 0
    assert "diverged; preserved" in result.stdout
    assert desktop.read_text(encoding="utf-8") == "user-owned\n"
