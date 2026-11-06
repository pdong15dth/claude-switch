# Claude Switch

**English** | [Tiếng Việt](README.vi.md)

Switch between multiple subscription accounts for **Claude Code** and **Claude Desktop** while keeping your settings, plugins, MCP servers, and session history intact.

No runtime dependencies beyond Python 3 (bundled with macOS) and macOS `security`.

## Install

```bash
cd ~/Documents/GitHub/claude-switch
./scripts/install.sh
```

This will:
- symlink the CLI to `~/.local/bin/claude-switch`
- build the menu bar app at `menubar/ClaudeSwitchBar.app`

If `~/.local/bin` is not in your `PATH`, add it to `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Run the menu bar app:

```bash
claude-switch menubar
```

Start automatically at macOS login (optional):

```bash
./scripts/autostart.sh install
./scripts/autostart.sh status
./scripts/autostart.sh uninstall
```

## Claude Code

Claude Code stores its subscription login in the **Keychain** (`Claude Code-credentials`) and account metadata in `~/.claude.json`. All settings/plugins/MCP/skills/sessions live in `~/.claude` and are never touched.

```bash
# add a new account: saves the current login, opens browser login, then saves the new account
claude-switch cc login work

# or just save the login you are already signed in with
claude-switch cc add work

# switch back and forth
claude-switch cc use work
claude-switch cc use personal

claude-switch cc list
claude-switch cc current
claude-switch cc remove personal
```

Notes:
- Close all Claude Code CLI sessions before running `use` (or pass `--force`). A running session can overwrite the token when it refreshes.
- When a token expires, Claude Code refreshes it automatically using the refresh token. If the refresh token has also expired, run `claude /login` for that account and then `claude-switch cc add <label> --force`.
- On every switch, the tool checkpoints the login currently in use first, so a freshly refreshed token is not lost.

## Claude Desktop

Claude Desktop is an Electron app; its login lives in Cookies/Local Storage/IndexedDB rather than being isolated like Claude Code. The tool only swaps the **auth entries**, not the entire app-data tree:

**Swapped per account (Claude session)**
`Cookies*`, `Local Storage`, `Session Storage`, `IndexedDB`, `WebStorage`, `SharedStorage`, `Trust Tokens*`, `InterestGroups`, `DIPS*`, `Network Persistent State`.

**Shared between accounts (not swapped)**
`Partitions/` — this is the browser/webview data inside Claude Desktop (`Launch Preview`, `cowork-shared`, preview). Cookies/logins for Google, Slack, Backlog/nulab, Figma, etc. live here and are **kept intact** when you switch Claude accounts.

**Kept as-is (settings)**
`config.json` (theme, locale, … only `lastKnownAccountUuid` is patched), `claude_desktop_config.json` (MCP servers), `Preferences`, extensions, `claude-code-sessions`, cowork state, `git-worktrees.json`, window state, cache.

```bash
# signed in as account 1, Claude Desktop is open
claude-switch desktop add personal
# the tool will: save account 1's session -> clear login -> open the app for you to log in as account 2
# -> wait for login to finish -> quit -> save profile "personal" -> reopen the app

# switch back and forth
claude-switch desktop use work         # quit -> checkpoint current session -> swap -> reopen
claude-switch desktop list
claude-switch desktop current
claude-switch desktop remove personal

# or just snapshot the session you are already signed in with
claude-switch desktop save work

# one-time: restore browser data from a profile created by an older version (with Partitions)
claude-switch desktop import-browser HCM
```

On every `desktop use`, the tool **checkpoints the currently running Claude session back into that account's profile before swapping**. This preserves claude.ai cookies/refresh sessions created since the last save.

**Do not log out manually inside the app.** Logging out invalidates the session server-side and makes the snapshot useless. Use `desktop add` or `desktop clear` instead — they only move auth state out of app-data, and the old session remains in the backup.

Note: any UI state Claude Desktop stores in top-level `localStorage`/`IndexedDB` follows the account. File-based settings such as MCP servers, extensions, and theme are kept intact.

### Browser/webview inside Claude Desktop

- The claude.ai login for the main window lives at the top level (`Cookies`, `Local Storage`, `IndexedDB`, …) and is swapped per profile.
- Embedded browser/webviews (`Partitions/launch-preview-*`, `cowork-shared`, …) are **shared**: switching Claude accounts does not lose your Google, Slack, Backlog/nulab, Figma, or Zalo logins. That data only changes when you explicitly run `desktop import-browser`.
- Caches (`Cache`, `Code Cache`, `GPUCache`, `blob_storage`, Service Worker cache, …) are **not** copied. Logins are unaffected, but temporary offline data may be lost.
- If by "browser" you mean **Claude in Chrome / the Chrome extension** running in real Chrome, the tool does not touch your Chrome profile — logins there are managed by Chrome.

## Sync sessions (local)

The Claude Code CLI shares `~/.claude/projects`, so sessions/transcripts are already available to every account. However, the **Code tab in Claude Desktop** stores metadata under `claude-code-sessions/<accountUuid>/<orgUuid>/`, so switching accounts makes the session list disappear. The tool syncs this metadata across accounts, entirely locally, with no network access.

```bash
claude-switch sessions status           # session count per account
claude-switch sessions sync --dry-run   # preview
claude-switch sessions sync             # quit Claude Desktop -> sync -> reopen
claude-switch sessions sync --no-quit   # best-effort sync while the app is running
```

Sync rules:
- For each `local_<id>.json`, the newest version (by `lastActivityAt`/mtime) is copied to every account/org dir where it is missing or older.
- The actual transcript stays at `~/.claude/projects/<project>/<cliSessionId>.jsonl` — it is already shared and is not copied.
- `deleted_<id>` tombstones are respected: a session deleted in one account is not re-added there automatically.
- No session is ever deleted; overwritten files are backed up to `~/.claude-switch/sessions/backups/`.
- Sync applies to all account/org dirs (including secondary orgs of the same account). Account-specific fields such as `envScopeId` or MCP tool IDs are not rewritten.

After syncing, restart Claude Desktop so the Code tab re-reads the session list.

## Menu bar

The `⇄` menu bar icon shows the current account for each app and lets you:
- switch Claude Code / Claude Desktop accounts
- **add a new account** (Claude Code opens Terminal to log in; Claude Desktop quits/reopens and waits for you to log in)
- save the current login
- clear the Claude Desktop login so you can add an account
- open Claude Desktop

The menu reads state each time it opens. Claude Desktop switch actions ask for confirmation because the app must quit and reopen.

## Security

- Claude Code tokens are stored in the **macOS Keychain** (service `claude-switch-cc`), never written to a plaintext file.
- State/desktop profiles live in `~/.claude-switch` with `0700` permissions; files are `0600`.
- Claude Desktop cookies are blobs encrypted with the machine's Keychain — profiles only work on this machine.
- The tool never prints tokens to output or logs.

## Known limitations

- On first Keychain access, macOS may ask for permission; choose **Always Allow**.
- `desktop save/use` requires quitting Claude Desktop; unsaved state in the app will be lost.
- Switching Claude Code does not change the account of an already-running session — restart the session.
- This is a tool for switching between subscriptions you own on your own machine; it has no mechanism to bypass quotas or share accounts.

## Comparison with other open-source tools

References:
- [claude-code-tools/claude-code-account-switcher](https://github.com/claude-code-tools/claude-code-account-switcher) — uses `claude setup-token` + a separate `CLAUDE_CONFIG_DIR` per account. Settings are symlinked, but each account has its own command and setup tokens do not support Remote Control.
- [vyshnavsdeepak/ccswitch](https://github.com/vyshnavsdeepak/ccswitch) — snapshots credentials into the Keychain and swaps them. Same approach as this tool.
- [FranCalveyra/claude-desktop-swap](https://github.com/FranCalveyra/claude-desktop-swap) — swaps nearly the entire Claude Desktop app-data tree.
- [NeezerGu/claude-profile-switcher](https://github.com/NeezerGu/claude-profile-switcher) — profile switcher for Claude Desktop.

This tool differs in that Claude Code only swaps the Keychain + `oauthAccount` (leaving 100% of `~/.claude` untouched), while Claude Desktop only swaps auth entries instead of the whole app-data tree.

Not affiliated with Anthropic. "Claude" is a product of Anthropic.

## Development

```bash
python3 -m unittest discover -s tests -v
./scripts/build-menubar.sh
```
