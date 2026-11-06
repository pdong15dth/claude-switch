# Claude Switch

Chuyển qua lại giữa nhiều account subscription của **Claude Code** và **Claude Desktop** mà vẫn giữ nguyên settings, plugin, MCP, session history.

Không có dependency runtime ngoài Python 3 (có sẵn trên macOS) và `security` của macOS.

## Cài đặt

```bash
cd ~/Documents/GitHub/claude-switch
./scripts/install.sh
```

Lệnh này:
- symlink CLI vào `~/.local/bin/claude-switch`
- build menu bar app `menubar/ClaudeSwitchBar.app`

Nếu `~/.local/bin` chưa có trong `PATH`, thêm vào `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Chạy menu bar:

```bash
claude-switch menubar
```

Tự chạy khi đăng nhập macOS (tuỳ chọn):

```bash
./scripts/autostart.sh install
./scripts/autostart.sh status
./scripts/autostart.sh uninstall
```

## Claude Code

Claude Code lưu login subscription ở **Keychain** (`Claude Code-credentials`) và metadata account trong `~/.claude.json`. Mọi settings/plugin/MCP/skill/session nằm ở `~/.claude` và không bị đụng tới.

```bash
# thêm account mới: tool tự lưu login hiện tại, mở browser login, rồi lưu account mới
claude-switch cc login work

# hoặc chỉ lưu login đang đăng nhập sẵn
claude-switch cc add work

# chuyển qua lại
claude-switch cc use work
claude-switch cc use personal

claude-switch cc list
claude-switch cc current
claude-switch cc remove personal
```

Lưu ý:
- Phải đóng các session Claude Code CLI trước khi `use` (hoặc `--force`). Session đang chạy có thể ghi đè token khi refresh.
- Token hết hạn thì Claude Code tự refresh bằng refresh token; nếu refresh token cũng hết hạn, chạy `claude /login` cho account đó rồi `claude-switch cc add <label> --force`.
- Khi switch, tool tự checkpoint login đang dùng trước, nên token vừa refresh không bị mất.

## Claude Desktop

Claude Desktop là Electron app; login nằm trong Cookies/Local Storage/IndexedDB chứ không tách riêng như Claude Code. Tool chỉ swap **các entry auth**, không swap toàn bộ app-data:

**Được swap theo account (Claude session)**
`Cookies*`, `Local Storage`, `Session Storage`, `IndexedDB`, `WebStorage`, `SharedStorage`, `Trust Tokens*`, `InterestGroups`, `DIPS*`, `Network Persistent State`.

**Dùng chung giữa các account (không swap)**
`Partitions/` — đây là dữ liệu browser/webview bên trong Claude Desktop (`Launch Preview`, `cowork-shared`, preview). Cookie/login của Google, Slack, Backlog/nulab, Figma… nằm ở đây và **được giữ nguyên** khi đổi Claude account.

**Được giữ nguyên (settings)**
`config.json` (theme, locale, … chỉ patch `lastKnownAccountUuid`), `claude_desktop_config.json` (MCP servers), `Preferences`, extensions, `claude-code-sessions`, cowork state, `git-worktrees.json`, window state, cache.

```bash
# đang đăng nhập account 1, Claude Desktop đang mở
claude-switch desktop add personal
# tool tự: lưu session account 1 -> clear login -> mở app để bạn login account 2
# -> chờ login xong -> quit -> lưu profile "personal" -> mở lại app

# chuyển qua lại
claude-switch desktop use work         # quit -> checkpoint session hiện tại -> swap -> mở lại
claude-switch desktop list
claude-switch desktop current
claude-switch desktop remove personal

# hoặc chỉ snapshot session đang đăng nhập sẵn
claude-switch desktop save work

# một lần: khôi phục browser data từ profile tạo bởi bản cũ (có Partitions)
claude-switch desktop import-browser HCM
```

Mỗi lần `desktop use`, tool **checkpoint ngược session Claude đang chạy vào profile của account đó trước khi swap**. Nhờ vậy cookie/refresh session của claude.ai phát sinh sau lần save cuối vẫn được giữ.

**Đừng logout bằng tay trong app.** Logout sẽ invalidate session phía server và snapshot thành vô dụng. Dùng `desktop add` hoặc `desktop clear` — chỉ dời auth state ra khỏi app-data, session cũ vẫn còn trong backup.

Lưu ý: state UI nào Claude Desktop lưu trong `localStorage`/`IndexedDB` top-level sẽ đi theo account. Settings dạng file như MCP servers, extensions, theme thì được giữ nguyên.

### Browser/webview bên trong Claude Desktop

- Login claude.ai của cửa sổ chính nằm ở top-level (`Cookies`, `Local Storage`, `IndexedDB`, …) và được swap theo profile.
- Browser/webview bên trong (`Partitions/launch-preview-*`, `cowork-shared`, …) **dùng chung**: đổi Claude account không làm mất login Google, Slack, Backlog/nulab, Figma, Zalo… Dữ liệu này chỉ bị thay đổi khi bạn chủ động chạy `desktop import-browser`.
- Cache (`Cache`, `Code Cache`, `GPUCache`, `blob_storage`, Service Worker cache, …) **không** được copy. Không mất login, nhưng dữ liệu offline tạm có thể mất.
- Nếu "browser" bạn nói là **Claude in Chrome / Chrome extension** chạy trong Chrome thật, tool không đụng tới profile Chrome — login ở đó do Chrome quản lý.

## Sync sessions (local)

Claude Code CLI dùng chung `~/.claude/projects`, nên session/transcript đã có sẵn ở mọi account. Riêng **Code tab của Claude Desktop** lưu metadata theo `claude-code-sessions/<accountUuid>/<orgUuid>/`, nên đổi account là danh sách session biến mất. Tool sync metadata này across các account, thuần local, không qua mạng.

```bash
claude-switch sessions status           # số session từng account
claude-switch sessions sync --dry-run   # xem trước
claude-switch sessions sync             # quit Claude Desktop -> sync -> mở lại
claude-switch sessions sync --no-quit   # sync best-effort khi app đang chạy
```

Quy tắc sync:
- Mỗi `local_<id>.json` được lấy bản mới nhất (theo `lastActivityAt`/mtime) và copy sang mọi account/org dir còn thiếu hoặc cũ hơn.
- Transcript thật vẫn nằm ở `~/.claude/projects/<project>/<cliSessionId>.jsonl` — đã dùng chung, không copy.
- Tôn trọng tombstone `deleted_<id>`: session đã xoá ở account nào thì không tự thêm lại vào account đó.
- Không xoá session nào; file bị ghi đè được backup vào `~/.claude-switch/sessions/backups/`.
- Sync áp dụng cho tất cả account/org dir (kể cả org phụ của cùng account). Không rewrite các field account-specific như `envScopeId` hay MCP tool IDs.

Sau khi sync, restart Claude Desktop để Code tab đọc lại danh sách session.

## Menu bar

Icon `⇄` trên menu bar hiển thị account hiện tại của từng app, cho phép:
- đổi account Claude Code / Claude Desktop
- **thêm account mới** (Claude Code mở Terminal để login; Claude Desktop tự quit/reopen và chờ bạn login)
- lưu login hiện tại
- clear login Claude Desktop để thêm account
- mở Claude Desktop

Menu đọc trạng thái mỗi lần mở. Thao tác switch Claude Desktop sẽ hỏi xác nhận vì app phải quit và mở lại.

## Bảo mật

- Token Claude Code lưu trong **macOS Keychain** (service `claude-switch-cc`), không ghi ra file plaintext.
- State/desktop profiles nằm ở `~/.claude-switch` với quyền `0700`; file `0600`.
- Cookie Claude Desktop là blob mã hoá bằng keychain của máy — profile chỉ dùng được trên chính máy này.
- Tool không in token ra output hay log.

## Giới hạn đã biết

- Lần đầu đọc Keychain, macOS có thể hỏi quyền truy cập; chọn **Always Allow**.
- `desktop save/use` cần quit Claude Desktop; state chưa lưu trong app sẽ mất.
- Switch Claude Code không làm session đang mở đổi account ngay — cần restart session.
- Đây là công cụ đổi giữa các subscription bạn sở hữu trên máy của bạn; không có cơ chế bypass quota hay chia sẻ account.

## So sánh với tool open-source khác

Đã tham khảo:
- [claude-code-tools/claude-code-account-switcher](https://github.com/claude-code-tools/claude-code-account-switcher) — dùng `claude setup-token` + `CLAUDE_CONFIG_DIR` riêng cho từng account. Settings được symlink nhưng mỗi account có command riêng và setup token không hỗ trợ Remote Control.
- [vyshnavsdeepak/ccswitch](https://github.com/vyshnavsdeepak/ccswitch) — snapshot credential vào Keychain rồi swap. Cùng hướng với tool này.
- [FranCalveyra/claude-desktop-swap](https://github.com/FranCalveyra/claude-desktop-swap) — swap gần như toàn bộ app-data của Claude Desktop.
- [NeezerGu/claude-profile-switcher](https://github.com/NeezerGu/claude-profile-switcher) — profile switcher cho Claude Desktop.

Tool này khác ở chỗ: Claude Code chỉ swap Keychain + `oauthAccount` (giữ nguyên 100% `~/.claude`), còn Claude Desktop chỉ swap entry auth thay vì cả cây app-data.

Không liên kết với Anthropic. "Claude" là sản phẩm của Anthropic.

## Phát triển

```bash
python3 -m unittest discover -s tests -v
./scripts/build-menubar.sh
```
