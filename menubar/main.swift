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

struct UsageWindow: Codable {
    let key: String
    let label: String
    let usedPercent: Double
    let resetsAt: Int?
}

struct UsageInfo: Codable {
    let ok: Bool
    let error: String?
    let message: String?
    let label: String?
    let email: String?
    let subscriptionType: String?
    let windows: [UsageWindow]?
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
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private var status: StatusInfo?
    private var usageInfo: UsageInfo?
    private var usageFetchedAt: Date?
    private var usageLoading = false
    private var busy = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let button = statusItem.button {
            button.image = statusImage(percent: nil)
            button.toolTip = "Claude Switch"
        }
        menu.delegate = self
        menu.autoenablesItems = false
        statusItem.menu = menu
        reload()
        reloadUsage(force: true)
        Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            self?.reload()
            self?.reloadUsage(force: true)
        }
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

    private func statusImage(percent: Double?) -> NSImage {
        let icon = claudeMenuIcon()
        let barWidth: CGFloat = 26
        let barHeight: CGFloat = 6
        let gap: CGFloat = 5
        let size = NSSize(width: 18 + (percent == nil ? 0 : gap + barWidth), height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            icon.draw(in: NSRect(x: 0, y: 0, width: 18, height: 18))
            guard let percent = percent else { return true }
            let track = NSRect(
                x: 18 + gap,
                y: (rect.height - barHeight) / 2,
                width: barWidth,
                height: barHeight
            )
            let background = NSBezierPath(
                roundedRect: track,
                xRadius: barHeight / 2,
                yRadius: barHeight / 2
            )
            NSColor.black.withAlphaComponent(0.3).setFill()
            background.fill()

            let fraction = max(0, min(percent / 100, 1))
            if fraction > 0 {
                let fill = NSRect(
                    x: track.minX,
                    y: track.minY,
                    width: max(barHeight, track.width * CGFloat(fraction)),
                    height: barHeight
                )
                NSColor.black.setFill()
                NSBezierPath(
                    roundedRect: fill,
                    xRadius: barHeight / 2,
                    yRadius: barHeight / 2
                ).fill()
            }
            return true
        }
        image.isTemplate = true
        return image
    }

    private func updateStatusItem() {
        guard let button = statusItem.button else { return }
        let primary = usageInfo?.windows?.first(where: { $0.key == "five_hour" })
            ?? usageInfo?.windows?.first
        button.image = statusImage(percent: primary?.usedPercent)

        var lines = ["Claude Switch"]
        if let info = usageInfo, info.ok {
            if let label = info.label {
                lines[0] += " — \(label)"
            }
            for window in info.windows ?? [] {
                var line = "\(window.label): \(formatPercent(window.usedPercent))"
                if let reset = resetText(window.resetsAt) {
                    line += " · \(reset)"
                }
                lines.append(line)
            }
        } else if let message = usageInfo?.message {
            lines.append(message)
        }
        button.toolTip = lines.joined(separator: "\n")
    }

    private func reloadUsage(force: Bool) {
        if usageLoading {
            return
        }
        if !force, let fetched = usageFetchedAt, Date().timeIntervalSince(fetched) < 60 {
            return
        }
        usageLoading = true
        runCLI(["usage", "--json"]) { [weak self] _, out, _ in
            guard let self = self else { return }
            self.usageLoading = false
            self.usageFetchedAt = Date()
            if let data = out.data(using: .utf8) {
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                if let info = try? decoder.decode(UsageInfo.self, from: data) {
                    self.usageInfo = info
                }
            }
            self.updateStatusItem()
            self.rebuildMenu()
        }
    }

    private func formatPercent(_ value: Double) -> String {
        if abs(value.rounded() - value) < 0.05 {
            return String(format: "%.0f%%", value)
        }
        return String(format: "%.1f%%", value)
    }

    private func resetText(_ epoch: Int?) -> String? {
        guard let epoch = epoch else { return nil }
        let date = Date(timeIntervalSince1970: TimeInterval(epoch))
        let remaining = date.timeIntervalSinceNow
        if remaining <= 0 {
            return "resetting"
        }
        if remaining < 48 * 3600 {
            let totalMinutes = Int(remaining / 60)
            let hours = totalMinutes / 60
            let minutes = totalMinutes % 60
            if hours > 0 {
                return "resets in \(hours)h \(minutes)m"
            }
            return "resets in \(minutes)m"
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "EEE HH:mm"
        return "resets \(formatter.string(from: date))"
    }

    private func usageValueText(_ window: UsageWindow) -> String {
        var parts = [formatPercent(window.usedPercent)]
        if let reset = resetText(window.resetsAt) {
            parts.append(reset)
        }
        return parts.joined(separator: " · ")
    }

    private func addUsageSection() {
        menu.addItem(.separator())

        var title = "Usage"
        if let info = usageInfo, info.ok, let label = info.label {
            title += " — \(label)"
            if let plan = info.subscriptionType, !plan.isEmpty {
                title += " (\(plan))"
            }
        }
        let header = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)

        if let info = usageInfo, info.ok, let windows = info.windows, !windows.isEmpty {
            for window in windows {
                addUsageRow(window)
            }
            return
        }

        let message: String
        if usageInfo == nil {
            message = "Loading…"
        } else {
            message = usageInfo?.message ?? "Usage unavailable"
        }
        let item = NSMenuItem(title: message, action: nil, keyEquivalent: "")
        item.isEnabled = false
        menu.addItem(item)
    }

    private func addUsageRow(_ window: UsageWindow) {
        let width: CGFloat = 300
        let view = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 44))

        let label = NSTextField(labelWithString: window.label)
        label.font = NSFont.systemFont(ofSize: 12)
        label.textColor = .labelColor
        label.frame = NSRect(x: 14, y: 24, width: 140, height: 16)
        view.addSubview(label)

        let value = NSTextField(labelWithString: usageValueText(window))
        value.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        value.textColor = .secondaryLabelColor
        value.alignment = .right
        value.frame = NSRect(x: width - 14 - 160, y: 24, width: 160, height: 16)
        view.addSubview(value)

        let bar = NSProgressIndicator(frame: NSRect(x: 14, y: 6, width: width - 28, height: 12))
        bar.style = .bar
        bar.isIndeterminate = false
        bar.minValue = 0
        bar.maxValue = 100
        bar.doubleValue = min(max(window.usedPercent, 0), 100)
        bar.controlSize = .small
        view.addSubview(bar)

        let item = NSMenuItem()
        item.view = view
        item.isEnabled = true
        menu.addItem(item)
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        rebuildMenu()
        reload()
        reloadUsage(force: false)
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
        addUsageSection()

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
            self.reloadUsage(force: true)
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
        reloadUsage(force: true)
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
