from __future__ import annotations

import argparse
import getpass
import json
import select
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import cc, desktop, paths, sessions, status
from .keychain import Keychain
from .util import (
    ToolError,
    confirm,
    human_ms,
    read_json_optional,
    short_uuid,
    validate_label,
)

VERSION = "1.0.0"


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _table(rows: List[List[str]], headers: List[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = []
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    data = status.build_status()
    if args.json:
        _print_json(data)
        return 0

    cc_data = data["claude_code"]
    live = cc_data.get("live") or {}
    active_label = cc_data.get("current_label") or "(not saved)"
    print("Claude Code")
    print("  active login : %s" % active_label)
    print("  email        : %s" % (live.get("email") or "-"))
    print("  plan         : %s" % (live.get("subscription_type") or "-"))
    print("  token expiry : %s" % human_ms(live.get("expires_at")))
    print("  accounts     : %s" % ", ".join(a["label"] for a in cc_data["accounts"]) or "-")

    desk = data["desktop"]
    print("")
    print("Claude Desktop")
    print("  active login : %s" % (desk.get("current_label") or "(unknown)"))
    print("  running      : %s" % ("yes" if desk.get("running") else "no"))
    print("  account uuid : %s" % short_uuid(desk.get("live_account_uuid")))
    print("  profiles     : %s" % ", ".join(a["label"] for a in desk["accounts"]) or "-")
    print("")
    print("state: %s" % cc_data.get("state_dir"))
    return 0


def cmd_cc_add(args: argparse.Namespace) -> int:
    info = cc.add(args.label, force=args.force)
    print(
        "saved Claude Code login %r (%s, %s)"
        % (args.label, info.get("email") or "unknown email", info.get("subscription_type") or "unknown plan")
    )
    if not info.get("account_uuid"):
        print(
            "warning: no oauthAccount metadata found in ~/.claude.json; "
            "switching back may keep billing the previous organization"
        )
    print("switch with: claude-switch cc use %s" % args.label)
    return 0


def cmd_cc_login(args: argparse.Namespace) -> int:
    print("Opening the browser for Claude subscription login…")
    result = cc.login(
        args.label,
        force=args.force,
        timeout=args.timeout,
        email=args.email,
    )
    if result.get("preserved_label"):
        print("previous login preserved as %r" % result["preserved_label"])
    if result.get("same_account"):
        print("warning: you signed in to the same account that was already active")
    info = result["info"]
    print(
        "added Claude Code login %r (%s, %s)"
        % (
            args.label,
            info.get("email") or "unknown email",
            info.get("subscription_type") or "unknown plan",
        )
    )
    return 0


def cmd_cc_use(args: argparse.Namespace) -> int:
    info = cc.use(args.label, force=args.force)
    print(
        "Claude Code now uses %r (%s). Restart running sessions to pick it up."
        % (args.label, info.get("email") or "unknown email")
    )
    return 0


def cmd_cc_list(args: argparse.Namespace) -> int:
    keychain = Keychain()
    rows = cc.list_accounts(keychain)
    if args.json:
        _print_json(rows)
        return 0
    if not rows:
        print("no saved Claude Code logins; run: claude-switch cc add <label>")
        return 0
    table = [
        [
            "*" if row.get("active") else "",
            row["label"],
            row.get("email") or "-",
            row.get("subscription_type") or "-",
            human_ms(row.get("expires_at")),
        ]
        for row in rows
    ]
    print(_table(table, ["", "LABEL", "EMAIL", "PLAN", "TOKEN EXPIRES"]))
    return 0


def cmd_cc_current(args: argparse.Namespace) -> int:
    live = cc.live_summary(Keychain())
    if args.json:
        _print_json(live)
        return 0
    print("label        : %s" % (live.get("label") or "(not saved)"))
    print("email        : %s" % (live.get("email") or "-"))
    print("plan         : %s" % (live.get("subscription_type") or "-"))
    print("token expiry : %s" % human_ms(live.get("expires_at")))
    print("refresh exp  : %s" % human_ms(live.get("refresh_expires_at")))
    return 0


def cmd_cc_remove(args: argparse.Namespace) -> int:
    cc.remove(args.label)
    print("removed Claude Code login %r" % args.label)
    return 0


def cmd_desktop_save(args: argparse.Namespace) -> int:
    validate_label(args.label)
    confirm(
        "Quit Claude Desktop, snapshot the current session as %r, then reopen it?"
        % args.label,
        args.yes,
    )
    was_running = desktop.is_running()
    if was_running:
        desktop.quit_app()
    try:
        meta = desktop.snapshot(args.label, force=args.force)
        print(
            "saved Claude Desktop profile %r (%s entries, %.1f MB, account %s)"
            % (
                args.label,
                len(meta.get("entries", [])),
                (meta.get("size_bytes") or 0) / (1024.0 * 1024.0),
                short_uuid(meta.get("account_uuid")),
            )
        )
    finally:
        if not args.no_launch:
            desktop.launch_app()
    return 0


def _wait_for_desktop_login(timeout: int, ignore_uuid: Optional[str]) -> str:
    interactive = sys.stdin.isatty()
    if interactive:
        print("Sign in to the new account in Claude Desktop, then press Enter (or wait for auto-detect).")
    started = time.time()
    while time.time() - started < timeout:
        uuid = desktop.live_account_uuid()
        if uuid and uuid != ignore_uuid:
            return uuid
        if interactive:
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if ready:
                sys.stdin.readline()
                uuid = desktop.live_account_uuid()
                if uuid:
                    return uuid
                print("still not signed in; keep waiting…")
        else:
            time.sleep(1.0)
    raise ToolError(
        "timed out waiting for the new Claude Desktop login; "
        "run `claude-switch desktop save <label>` after signing in"
    )


def _auto_desktop_label(account_uuid: str) -> str:
    base = "auto-" + account_uuid[:8]
    label = base
    taken = {meta.get("label"): meta.get("account_uuid") for meta in desktop.list_profiles()}
    suffix = 2
    while label in taken and taken[label] != account_uuid:
        label = "%s-%d" % (base, suffix)
        suffix += 1
    return label


def cmd_desktop_add(args: argparse.Namespace) -> int:
    validate_label(args.label)
    if (desktop.profiles_dir() / args.label).exists() and not args.force:
        raise ToolError("profile %r already exists; pass --force to overwrite" % args.label)
    confirm(
        "Quit Claude Desktop, save the current session, clear the local login, "
        "then reopen it so you can sign in to a new account?",
        args.yes,
    )
    old_uuid = desktop.live_account_uuid()
    was_running = desktop.is_running()
    if was_running:
        desktop.quit_app()
    try:
        current = desktop.current_label()
        if old_uuid:
            if current:
                desktop.snapshot(current, force=True)
                print("checkpointed current session as %r" % current)
            else:
                auto = _auto_desktop_label(old_uuid)
                desktop.snapshot(auto, force=True)
                print("current session had no label; saved as %r" % auto)
        desktop.clear_live()
        desktop.launch_app()
        new_uuid = _wait_for_desktop_login(args.timeout, old_uuid)
        print("detected new account %s; snapshotting…" % short_uuid(new_uuid))
        desktop.quit_app()
        meta = desktop.snapshot(args.label, force=args.force)
        print(
            "added Claude Desktop profile %r (account %s, %.1f MB)"
            % (
                args.label,
                short_uuid(meta.get("account_uuid")),
                (meta.get("size_bytes") or 0) / (1024.0 * 1024.0),
            )
        )
    finally:
        if not args.no_launch and not desktop.is_running():
            desktop.launch_app()
    return 0


def cmd_desktop_import_browser(args: argparse.Namespace) -> int:
    validate_label(args.label)
    confirm(
        "Quit Claude Desktop and copy the embedded-browser data saved in profile %r "
        "into the live app?" % args.label,
        args.yes,
    )
    was_running = desktop.is_running()
    if was_running:
        desktop.quit_app()
    try:
        result = desktop.import_browser(args.label)
        print(
            "imported %d browser entries from %r (previous live browser data: %s)"
            % (result["entries"], args.label, result["backup"])
        )
    finally:
        if not args.no_launch:
            desktop.launch_app()
    return 0


def cmd_desktop_use(args: argparse.Namespace) -> int:
    validate_label(args.label)
    confirm(
        "Quit Claude Desktop, switch to %r, then reopen it? Unsaved in-app state will be lost."
        % args.label,
        args.yes,
    )
    was_running = desktop.is_running()
    if was_running:
        desktop.quit_app()
    try:
        result = desktop.restore(args.label)
        meta = result["meta"]
        if result.get("checkpointed"):
            print(
                "checkpointed current browser/session state as %r"
                % result["checkpointed"]
            )
        print(
            "Claude Desktop now uses %r (account %s)"
            % (args.label, short_uuid(meta.get("account_uuid")))
        )
    finally:
        if not args.no_launch:
            desktop.launch_app()
    return 0


def cmd_desktop_list(args: argparse.Namespace) -> int:
    rows = desktop.list_profiles()
    current = desktop.current_label()
    if args.json:
        _print_json({"current": current, "profiles": rows})
        return 0
    if not rows:
        print("no saved Claude Desktop profiles; run: claude-switch desktop save <label>")
        return 0
    table = []
    for meta in rows:
        label = meta.get("label") or "?"
        table.append(
            [
                "*" if label == current else "",
                label,
                short_uuid(meta.get("account_uuid")),
                meta.get("saved_at") or "-",
                "%.1f MB" % ((meta.get("size_bytes") or 0) / (1024.0 * 1024.0)),
            ]
        )
    print(_table(table, ["", "LABEL", "ACCOUNT", "SAVED AT", "SIZE"]))
    return 0


def cmd_desktop_current(args: argparse.Namespace) -> int:
    data = {
        "label": desktop.current_label(),
        "account_uuid": desktop.live_account_uuid(),
        "running": desktop.is_running(),
    }
    if args.json:
        _print_json(data)
        return 0
    print("label        : %s" % (data["label"] or "(unknown)"))
    print("account uuid : %s" % short_uuid(data["account_uuid"]))
    print("running      : %s" % ("yes" if data["running"] else "no"))
    return 0


def cmd_desktop_remove(args: argparse.Namespace) -> int:
    validate_label(args.label)
    confirm("Delete Claude Desktop profile %r?" % args.label, args.yes)
    desktop.remove(args.label)
    print("removed Claude Desktop profile %r" % args.label)
    return 0


def cmd_desktop_clear(args: argparse.Namespace) -> int:
    confirm(
        "Clear the local Claude Desktop login so you can sign in with another account? "
        "The current session is backed up first.",
        args.yes,
    )
    was_running = desktop.is_running()
    if was_running:
        desktop.quit_app()
    try:
        backup = desktop.clear_live()
        print("cleared live login (backup: %s)" % backup)
    finally:
        if not args.no_launch:
            desktop.launch_app()
    return 0


def cmd_sessions_status(args: argparse.Namespace) -> int:
    data = sessions.status()
    if getattr(args, "json", False):
        _print_json(data)
        return 0
    print("Claude Desktop Code sessions")
    rows = data["claude_desktop_code_sessions"]
    if not rows:
        print("  (none)")
    for row in rows:
        print(
            "  %s / %s : %d sessions, %d deleted"
            % (
                short_uuid(row["account_uuid"]),
                short_uuid(row["org_uuid"]),
                row["sessions"],
                row["deleted"],
            )
        )
    cli = data["claude_code_cli"]
    print("")
    print(
        "Claude Code CLI: %d projects, %d transcripts (shared across accounts)"
        % (cli["projects"], cli["transcripts"])
    )
    return 0


def cmd_sessions_sync(args: argparse.Namespace) -> int:
    if args.dry_run:
        result = sessions.sync(dry_run=True)
        print(
            "would copy %d session(s) across %d account dirs "
            "(%d up to date, %d skipped because deleted)"
            % (
                result["copies"],
                result["directories"],
                result["up_to_date"],
                result["skipped_deleted"],
            )
        )
        for item in result["details"][:50]:
            print(
                "  %s %s/%s %s"
                % (
                    item["action"],
                    short_uuid(item["account_uuid"]),
                    short_uuid(item["org_uuid"]),
                    item["session"],
                )
            )
        return 0

    was_running = desktop.is_running()
    if was_running and not args.no_quit:
        confirm(
            "Quit Claude Desktop before syncing session metadata, then reopen it?",
            args.yes,
        )
        desktop.quit_app()
    elif was_running:
        print("warning: Claude Desktop is running; syncing without quitting (best effort)")

    try:
        result = sessions.sync()
    finally:
        if was_running and not args.no_quit and not args.no_launch:
            desktop.launch_app()

    print(
        "synced %d session(s) across %d account dirs "
        "(%d up to date, %d skipped because deleted)"
        % (
            result["copies"],
            result["directories"],
            result["up_to_date"],
            result["skipped_deleted"],
        )
    )
    if result.get("backups"):
        print("backups: %s" % result["backups"])
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0
    state = paths.state_dir()
    print("keychain backend : %s" % paths.keychain_backend())
    try:
        keychain = Keychain()
        live = keychain.get(cc.LIVE_SERVICE, getpass.getuser())
        print("live credentials : %s" % ("found" if live else "missing"))
        if not live:
            problems += 1
    except ToolError as exc:
        print("live credentials : ERROR %s" % exc)
        problems += 1

    cc_cfg = read_json_optional(paths.cc_json())
    print("claude json      : %s" % ("found" if cc_cfg else "missing"))
    if not isinstance(cc_cfg, dict):
        problems += 1

    if state.exists():
        mode = state.stat().st_mode & 0o777
        print("state dir mode   : %04o" % mode)
        if mode & 0o077:
            print("WARNING: state dir is accessible by other users")
            problems += 1
    else:
        print("state dir        : not created yet")

    cc_rows = cc.list_accounts(Keychain())
    uuids: Dict[str, List[str]] = {}
    for row in cc_rows:
        uid = row.get("account_uuid")
        if uid:
            uuids.setdefault(uid, []).append(row["label"])
    for uid, labels in uuids.items():
        if len(labels) > 1:
            print("WARNING: duplicate Claude Code account in profiles: %s" % ", ".join(labels))
            problems += 1

    desk_rows = desktop.list_profiles()
    print("desktop profiles : %d" % len(desk_rows))
    for meta in desk_rows:
        if meta.get("account_uuid") is None:
            print("WARNING: desktop profile %r has no account uuid" % meta.get("label"))
            problems += 1
    print("claude desktop   : %s" % ("installed" if desktop.CLAUDE_APP.exists() else "not found"))
    print("")
    print("ok" if problems == 0 else "%d problem(s) found" % problems)
    return 0 if problems == 0 else 1


def cmd_menubar(args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parent.parent
    app = repo / "menubar" / "ClaudeSwitchBar.app"
    if not app.is_dir():
        raise ToolError("menubar app not built; run scripts/build-menubar.sh")
    from .util import run

    run(["open", str(app)])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-switch",
        description="Switch Claude Code and Claude Desktop logins while keeping settings.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", help="show both targets")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_cc = sub.add_parser("cc", help="Claude Code login switching")
    cc_sub = p_cc.add_subparsers(dest="cc_command")

    p = cc_sub.add_parser("add", help="save the current login")
    p.add_argument("label")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_cc_add)

    p = cc_sub.add_parser("login", help="sign in to another account and save it")
    p.add_argument("label")
    p.add_argument("--force", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--email")
    p.set_defaults(func=cmd_cc_login)

    p = cc_sub.add_parser("use", help="switch to a saved login")
    p.add_argument("label")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_cc_use)

    p = cc_sub.add_parser("list", help="list saved logins")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cc_list)

    p = cc_sub.add_parser("current", help="show the live login")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cc_current)

    p = cc_sub.add_parser("remove", help="delete a saved login")
    p.add_argument("label")
    p.set_defaults(func=cmd_cc_remove)

    p_desktop = sub.add_parser("desktop", help="Claude Desktop profile switching")
    d_sub = p_desktop.add_subparsers(dest="desktop_command")

    p = d_sub.add_parser("save", help="snapshot the current signed-in session")
    p.add_argument("label")
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_desktop_save)

    p = d_sub.add_parser(
        "add", help="save the current session, then sign in to a new account"
    )
    p.add_argument("label")
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_desktop_add)

    p = d_sub.add_parser("use", help="switch to a saved session")
    p.add_argument("label")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_desktop_use)

    p = d_sub.add_parser(
        "import-browser",
        help="copy embedded-browser data from an old profile into the live app",
    )
    p.add_argument("label")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_desktop_import_browser)

    p = d_sub.add_parser("list", help="list saved profiles")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_desktop_list)

    p = d_sub.add_parser("current", help="show the live profile")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_desktop_current)

    p = d_sub.add_parser("remove", help="delete a profile")
    p.add_argument("label")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_desktop_remove)

    p = d_sub.add_parser("clear", help="clear the live login to add another account")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_desktop_clear)

    p_sessions = sub.add_parser("sessions", help="local Code session sync")
    s_sub = p_sessions.add_subparsers(dest="sessions_command")

    p = s_sub.add_parser("status", help="show session counts per account")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sessions_status)

    p = s_sub.add_parser("sync", help="share Code sessions across Claude accounts")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-quit", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.set_defaults(func=cmd_sessions_sync)

    p_sessions.set_defaults(func=cmd_sessions_status)

    p_doctor = sub.add_parser("doctor", help="check local state")
    p_doctor.set_defaults(func=cmd_doctor)

    p_menubar = sub.add_parser("menubar", help="open the menu bar app")
    p_menubar.set_defaults(func=cmd_menubar)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["status"])
    try:
        return int(args.func(args) or 0)
    except ToolError as exc:
        print("claude-switch: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130
