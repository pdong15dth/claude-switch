import Cocoa

struct AccountInfo: Codable {
    let label: String
    let email: String?
    let subscriptionType: String?
    let active: Bool?
}

struct TargetInfo: Codable {
    let currentLabel: String?
    let accounts: [AccountInfo]
    let running: Bool?
}

struct StatusInfo: Codable {
    let claudeCode: TargetInfo
    let desktop: TargetInfo
}

final class SwitchAction: NSObject {
    let target: String
    let label: String

    init(target: String, label: String) {
        self.target = target
        self.label = label
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private var status: StatusInfo?
    private var busy = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let button = statusItem.button {
            button.image = claudeMenuIcon()
            button.toolTip = "Claude Switch"
        }
        menu.delegate = self
        statusItem.menu = menu
        reload()
    }

    private func claudeMenuIcon() -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            let center = NSPoint(x: rect.midX, y: rect.midY)
            let rayCount = 12
            let outer = min(rect.width, rect.height) * 0.46
            let inner = outer * 0.16
            let lengths: [CGFloat] = [
                1.0, 0.90, 0.97, 0.86, 0.95, 0.90,
                1.0, 0.88, 0.96, 0.90, 0.98, 0.87,
            ]
            let path = NSBezierPath()
            path.lineWidth = 1.6
            path.lineCapStyle = .round
            for index in 0..<rayCount {
                let angle = CGFloat(index) / CGFloat(rayCount) * .pi * 2 + .pi / 12
                let length = outer * lengths[index]
                path.move(
                    to: NSPoint(
                        x: center.x + cos(angle) * inner,
                        y: center.y + sin(angle) * inner
                    )
                )
                path.line(
                    to: NSPoint(
                        x: center.x + cos(angle) * length,
                        y: center.y + sin(angle) * length
                    )
                )
            }
            NSColor.black.setStroke()
            path.stroke()
            return true
        }
        image.isTemplate = true
        return image
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        rebuildMenu()
        reload()
    }

    private func cliPath() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            "\(home)/.local/bin/claude-switch",
            "/usr/local/bin/claude-switch",
            "/opt/homebrew/bin/claude-switch",
        ]
        for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        return candidates[0]
    }

    private func runCLI(_ args: [String], done: ((Bool, String, String) -> Void)? = nil) {
        let path = cliPath()
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: path)
            process.arguments = args
            var env = ProcessInfo.processInfo.environment
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
            process.environment = env
            let out = Pipe()
            let err = Pipe()
            process.standardOutput = out
            process.standardError = err
            do {
                try process.run()
                process.waitUntilExit()
                let outText = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                let errText = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                let ok = process.terminationStatus == 0
                DispatchQueue.main.async { done?(ok, outText, errText) }
            } catch {
                DispatchQueue.main.async { done?(false, "", error.localizedDescription) }
            }
        }
    }

    private func reload() {
        runCLI(["status", "--json"]) { [weak self] ok, out, _ in
            guard let self = self else { return }
            if ok, let data = out.data(using: .utf8) {
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                self.status = try? decoder.decode(StatusInfo.self, from: data)
            }
            self.rebuildMenu()
        }
    }

    private func rebuildMenu() {
        menu.removeAllItems()

        let header = NSMenuItem(title: "Claude Switch", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(.separator())

        addTargetMenu(
            title: "Claude Code",
            targetKey: "cc",
            target: status?.claudeCode
        )
        addTargetMenu(
            title: "Claude Desktop",
            targetKey: "desktop",
            target: status?.desktop
        )

        menu.addItem(.separator())

        let sync = NSMenuItem(
            title: "Sync Code sessions…",
            action: #selector(syncSessionsClicked),
            keyEquivalent: ""
        )
        sync.target = self
        menu.addItem(sync)

        menu.addItem(.separator())

        let refresh = NSMenuItem(title: "Refresh", action: #selector(refreshClicked), keyEquivalent: "r")
        refresh.target = self
        menu.addItem(refresh)

        let open = NSMenuItem(title: "Open Claude Desktop", action: #selector(openClaudeClicked), keyEquivalent: "")
        open.target = self
        menu.addItem(open)

        menu.addItem(.separator())

        let quit = NSMenuItem(title: "Quit", action: #selector(quitClicked), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
    }

    private func addTargetMenu(title: String, targetKey: String, target: TargetInfo?) {
        let current = target?.currentLabel ?? "not saved"
        var suffix = current
        if targetKey == "desktop", target?.running == true {
            suffix += " (running)"
        }
        let item = NSMenuItem(title: "\(title) — \(suffix)", action: nil, keyEquivalent: "")
        let sub = NSMenu()

        if let accounts = target?.accounts, !accounts.isEmpty {
            for account in accounts {
                var text = account.label
                if let email = account.email, !email.isEmpty {
                    text += "  (\(email))"
                }
                if let plan = account.subscriptionType, !plan.isEmpty {
                    text += " · \(plan)"
                }
                let entry = NSMenuItem(title: text, action: #selector(switchAccount(_:)), keyEquivalent: "")
                entry.target = self
                entry.representedObject = SwitchAction(target: targetKey, label: account.label)
                if account.label == current || account.active == true {
                    entry.state = .on
                }
                sub.addItem(entry)
            }
        } else {
            let empty = NSMenuItem(title: "No saved logins", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            sub.addItem(empty)
        }

        sub.addItem(.separator())

        let save = NSMenuItem(title: "Save current login…", action: #selector(saveCurrent(_:)), keyEquivalent: "")
        save.target = self
        save.representedObject = targetKey
        sub.addItem(save)

        let add = NSMenuItem(title: "Add account…", action: #selector(addAccount(_:)), keyEquivalent: "")
        add.target = self
        add.representedObject = targetKey
        sub.addItem(add)

        if targetKey == "desktop" {
            let clear = NSMenuItem(
                title: "Clear login to add another account…",
                action: #selector(clearDesktopClicked),
                keyEquivalent: ""
            )
            clear.target = self
            sub.addItem(clear)
        }

        item.submenu = sub
        menu.addItem(item)
    }

    @objc private func switchAccount(_ sender: NSMenuItem) {
        guard !busy, let action = sender.representedObject as? SwitchAction else { return }
        if action.target == "desktop" {
            let alert = NSAlert()
            alert.messageText = "Switch Claude Desktop to “\(action.label)”?"
            alert.informativeText = "Claude Desktop will quit, swap its login profile, and reopen. Unsaved in-app state will be lost."
            alert.addButton(withTitle: "Switch")
            alert.addButton(withTitle: "Cancel")
            NSApp.activate(ignoringOtherApps: true)
            if alert.runModal() != .alertFirstButtonReturn {
                return
            }
        }
        busy = true
        let args = action.target == "cc"
            ? ["cc", "use", action.label]
            : ["desktop", "use", action.label, "--yes"]
        runCLI(args) { [weak self] ok, _, err in
            guard let self = self else { return }
            self.busy = false
            if !ok {
                self.showError(err)
            }
            self.reload()
        }
    }

    @objc private func addAccount(_ sender: NSMenuItem) {
        guard !busy, let targetKey = sender.representedObject as? String else { return }
        let appName = targetKey == "cc" ? "Claude Code" : "Claude Desktop"
        guard let label = promptLabel(
            title: "Add a \(appName) account",
            message: "Label for the new account (letters, digits, . _ @ + -).\n\nClaude Code opens Terminal for the browser login. Claude Desktop quits, saves the current session, then reopens so you can sign in.",
            placeholder: "work"
        ) else { return }

        if targetKey == "cc" {
            let command = "\(shellQuote(cliPath())) cc login \(shellQuote(label))"
            openTerminal(command: command)
            return
        }

        let alert = NSAlert()
        alert.messageText = "Add Claude Desktop account “\(label)”?"
        alert.informativeText = "Claude Desktop will quit, save the current session, reopen for you to sign in, then snapshot the new account."
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        busy = true
        runCLI(["desktop", "add", label, "--yes", "--timeout", "900"]) { [weak self] ok, out, err in
            guard let self = self else { return }
            self.busy = false
            if ok {
                self.showInfo(out)
            } else {
                self.showError(err)
            }
            self.reload()
        }
    }

    private func promptLabel(title: String, message: String, placeholder: String) -> String? {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24))
        field.placeholderString = placeholder
        alert.accessoryView = field
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let label = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        return label.isEmpty ? nil : label
    }

    private func shellQuote(_ value: String) -> String {
        return "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private func openTerminal(command: String) {
        let escaped = command
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"Terminal\" to do script \"\(escaped)\"\ntell application \"Terminal\" to activate"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        do {
            try process.run()
        } catch {
            showError(error.localizedDescription)
        }
    }

    @objc private func saveCurrent(_ sender: NSMenuItem) {
        guard !busy, let targetKey = sender.representedObject as? String else { return }
        let appName = targetKey == "cc" ? "Claude Code" : "Claude Desktop"
        guard let label = promptLabel(
            title: "Save the current \(appName) login",
            message: "Choose a label for this account. Claude Desktop will quit and reopen while its session is snapshotted.",
            placeholder: "work"
        ) else { return }
        busy = true
        let args = targetKey == "cc"
            ? ["cc", "add", label, "--force"]
            : ["desktop", "save", label, "--force", "--yes"]
        runCLI(args) { [weak self] ok, _, err in
            guard let self = self else { return }
            self.busy = false
            if !ok {
                self.showError(err)
            }
            self.reload()
        }
    }

    @objc private func clearDesktopClicked() {
        guard !busy else { return }
        let alert = NSAlert()
        alert.messageText = "Clear the local Claude Desktop login?"
        alert.informativeText = "The current session is backed up, then Claude reopens so you can sign in with another account. Afterwards use “Save current login…”."
        alert.addButton(withTitle: "Clear and reopen")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        busy = true
        runCLI(["desktop", "clear", "--yes"]) { [weak self] ok, _, err in
            guard let self = self else { return }
            self.busy = false
            if !ok {
                self.showError(err)
            }
            self.reload()
        }
    }

    @objc private func syncSessionsClicked() {
        guard !busy else { return }
        busy = true
        runCLI(["sessions", "sync", "--no-quit"]) { [weak self] ok, out, err in
            guard let self = self else { return }
            self.busy = false
            if ok {
                self.showInfo(out + "\n\nRestart Claude Desktop to see synced sessions.")
            } else {
                self.showError(err)
            }
            self.reload()
        }
    }

    @objc private func refreshClicked() {
        reload()
    }

    @objc private func openClaudeClicked() {
        NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/Claude.app"))
    }

    @objc private func quitClicked() {
        NSApp.terminate(nil)
    }

    private func showInfo(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Claude Switch"
        var text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            text = "Done."
        }
        if text.count > 1200 {
            text = String(text.prefix(1200)) + "…"
        }
        alert.informativeText = text
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "claude-switch failed"
        var text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            text = "Unknown error. See the terminal for details."
        }
        if text.count > 1200 {
            text = String(text.prefix(1200)) + "…"
        }
        alert.informativeText = text
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
