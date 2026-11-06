# Claude Switch

[English](README.md) | **Tiếng Việt**

Chuyển qua lại giữa nhiều account subscription của **Claude Code** và **Claude Desktop** mà vẫn giữ nguyên settings, plugin, MCP, session history.

Không có dependency runtime ngoài Python 3 (có sẵn trên macOS) và `security` của macOS.

## Cài đặt

```bash
git clone https://github.com/pdong15dth/claude-switch.git ~/Documents/GitHub/claude-switch
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

## Nhờ AI cài đặt

Nếu không muốn làm theo các bước thủ công, dán prompt dưới đây vào Claude Code, Command Code, hoặc bất kỳ agent nào có quyền chạy lệnh terminal. Agent sẽ cài đặt, tạo account và kiểm tra; bạn chỉ cần đăng nhập trên browser và bấm cấp quyền khi macOS hỏi.

```text
Hãy cài đặt claude-switch trên máy Mac này từ đầu đến cuối. Chỉ dừng lại khi macOS hoặc browser cần tôi thao tác (đăng nhập, cấp quyền Keychain). Mọi việc còn lại bạn tự làm.

Quy tắc:
- Dùng `claude-switch` nếu có trong PATH, ngược lại dùng <repo>/bin/claude-switch.
- Không in, copy hay commit OAuth token. Không sửa tay ~/.claude, ~/.claude.json hay app-data của Claude Desktop; chỉ dùng claude-switch.
- Hỏi tôi trước khi xoá bất kỳ profile đã lưu.

Các bước:
1. Kiểm tra macOS, python3, git. Nếu chưa có repo, clone https://github.com/pdong15dth/claude-switch.git vào ~/Documents/GitHub/claude-switch; nếu đã có, chạy `git pull --ff-only`.
2. Chạy ./scripts/install.sh, sau đó `claude-switch doctor`. Nếu ~/.local/bin chưa có trong PATH, thêm `export PATH="$HOME/.local/bin:$PATH"` vào ~/.zshrc đúng một lần.
3. Hiển thị kết quả `claude-switch status`.
4. Hỏi tôi các label account muốn dùng cho Claude Code và Claude Desktop (ví dụ work, personal).
5. Claude Code: với label đầu tiên, nếu tôi đang đăng nhập sẵn thì chạy `claude-switch cc add <label>`; với mỗi label tiếp theo chạy `claude-switch cc login <label>` và bảo tôi hoàn tất đăng nhập trên browser. Kiểm tra bằng `claude-switch cc list` và `claude-switch cc current`.
6. Claude Desktop: lưu account đang đăng nhập bằng `claude-switch desktop save <label>`; với mỗi label tiếp theo chạy `claude-switch desktop add <label> --yes`, bảo tôi đăng nhập khi app mở lại, và chờ lệnh chạy xong. Kiểm tra bằng `claude-switch desktop list` và `claude-switch desktop current`.
7. Nếu có nhiều hơn một account, xem trước sync session bằng `claude-switch sessions sync --dry-run`, rồi chạy `claude-switch sessions sync --yes` nếu kết quả xem trước ổn.
8. Hỏi tôi có muốn menu bar app tự chạy khi đăng nhập không; chỉ chạy ./scripts/autostart.sh install nếu tôi đồng ý.
9. Kết thúc bằng `claude-switch status` và tóm tắt ngắn: các account đã lưu, account hiện tại của từng app, và cách chuyển.

Trước mọi lệnh `cc use`, đảm bảo không có session Claude Code CLI nào đang chạy (hoặc bảo tôi đóng), để session đang chạy không ghi đè token khi refresh.
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

## Usage / quota

Menu bar hiển thị mức dùng 5 giờ của account Claude Code hiện tại bằng một thanh nhỏ cạnh icon. Mở menu sẽ thấy mọi cửa sổ giới hạn đang hoạt động — 5 giờ, weekly, và Opus/Sonnet weekly nếu account có báo — kèm progress bar và đếm ngược thời gian reset.

```bash
claude-switch usage           # dạng đọc được
claude-switch usage --json    # cho script và menu bar app
```

Dữ liệu đọc từ endpoint usage của claude.ai bằng token trong Keychain; không lưu hay ghi log. Nếu token hết hạn, thanh quota sẽ ẩn và menu nhắc mở Claude Code một lần để refresh. App tự cập nhật mỗi 5 phút, cache 60 giây giữa các lần mở menu; chọn **Refresh** trong menu để cập nhật ngay.

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

## Giấy phép

[MIT](LICENSE)
