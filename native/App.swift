import AppKit
import Foundation
import LocalAuthentication
import UniformTypeIdentifiers

func humanSize(_ bytes: Int64) -> String {
    let formatter = ByteCountFormatter()
    formatter.countStyle = .file
    return formatter.string(fromByteCount: bytes)
}

func compactDAWFormat(product: String, version: String) -> String {
    let lower = product.lowercased()
    let name: String
    if lower.contains("nuendo") {
        name = "Nuendo"
    } else if lower.contains("cubase") {
        name = "Cubase"
    } else {
        return product == "?" ? "Unknown" : product
    }
    let major = version.split(separator: ".").first.map(String.init) ?? version
    return major.isEmpty || major == "?" ? name : "\(name) \(major)"
}

// MARK: - Shell chrome

/// Colour roles for the application shell. The design tokens are mapped onto
/// macOS semantic colours so one implementation renders both the light and the
/// dark palette and still follows the user's accent and contrast settings.
enum ShellPalette {
    static var text: NSColor { .labelColor }
    static var textSecondary: NSColor { .secondaryLabelColor }
    static var textTertiary: NSColor { .tertiaryLabelColor }
    static var accent: NSColor { .controlAccentColor }
    static var onAccent: NSColor { .alternateSelectedControlTextColor }
    static var border: NSColor { .separatorColor }
}

/// One-point hairline. A layer colour is a CGColor and does not follow the
/// palette on its own, so it is re-resolved whenever the appearance changes.
final class ShellSeparator: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
    }

    required init?(coder: NSCoder) { fatalError("ShellSeparator is created in code only") }

    override var wantsUpdateLayer: Bool { true }

    override func updateLayer() {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            layer?.backgroundColor = ShellPalette.border.cgColor
        }
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        needsDisplay = true
    }
}

/// One sidebar workspace row: symbol, label and an optional count badge inside
/// a rounded selection pill that fills with the accent colour while current.
final class SidebarNavButton: NSButton {
    private let symbolView = NSImageView()
    private let captionField = NSTextField(labelWithString: "")
    private let badgeField = NSTextField(labelWithString: "")
    private let badgePill = NSView()

    var isCurrent = false {
        didSet { if isCurrent != oldValue { applyState() } }
    }

    var badge: String? {
        didSet {
            badgeField.stringValue = badge ?? ""
            badgePill.isHidden = badge == nil
            applyState()
        }
    }

    init(caption: String, symbol: String, target: AnyObject, action: Selector) {
        super.init(frame: NSRect(x: 0, y: 0, width: 200, height: 30))
        self.target = target
        self.action = action
        title = ""
        isBordered = false
        setButtonType(.momentaryChange)
        wantsLayer = true
        layer?.cornerRadius = 7
        translatesAutoresizingMaskIntoConstraints = false
        setAccessibilityRole(.radioButton)
        setAccessibilityLabel(caption)

        symbolView.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?
            .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 13, weight: .regular))
        symbolView.imageScaling = .scaleProportionallyDown
        symbolView.translatesAutoresizingMaskIntoConstraints = false

        captionField.stringValue = caption
        captionField.translatesAutoresizingMaskIntoConstraints = false

        badgeField.font = .systemFont(ofSize: 10.5, weight: .semibold)
        badgeField.alignment = .center
        badgeField.translatesAutoresizingMaskIntoConstraints = false
        badgePill.wantsLayer = true
        badgePill.layer?.cornerRadius = 8
        badgePill.isHidden = true
        badgePill.translatesAutoresizingMaskIntoConstraints = false
        badgePill.addSubview(badgeField)

        addSubview(symbolView)
        addSubview(captionField)
        addSubview(badgePill)

        NSLayoutConstraint.activate([
            heightAnchor.constraint(equalToConstant: 30),
            symbolView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 10),
            symbolView.centerYAnchor.constraint(equalTo: centerYAnchor),
            symbolView.widthAnchor.constraint(equalToConstant: 16),
            captionField.leadingAnchor.constraint(equalTo: symbolView.trailingAnchor, constant: 9),
            captionField.centerYAnchor.constraint(equalTo: centerYAnchor),
            badgePill.leadingAnchor.constraint(greaterThanOrEqualTo: captionField.trailingAnchor, constant: 8),
            badgePill.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -10),
            badgePill.centerYAnchor.constraint(equalTo: centerYAnchor),
            badgeField.leadingAnchor.constraint(equalTo: badgePill.leadingAnchor, constant: 6),
            badgeField.trailingAnchor.constraint(equalTo: badgePill.trailingAnchor, constant: -6),
            badgeField.topAnchor.constraint(equalTo: badgePill.topAnchor, constant: 1),
            badgeField.bottomAnchor.constraint(equalTo: badgePill.bottomAnchor, constant: -1),
        ])
        applyState()
    }

    required init?(coder: NSCoder) { fatalError("SidebarNavButton is created in code only") }

    private func applyState() {
        captionField.font = .systemFont(ofSize: 13, weight: isCurrent ? .semibold : .regular)
        captionField.textColor = isCurrent ? ShellPalette.onAccent : ShellPalette.text
        symbolView.contentTintColor = isCurrent ? ShellPalette.onAccent : ShellPalette.textSecondary
        badgeField.textColor = isCurrent ? ShellPalette.accent : ShellPalette.onAccent
        setAccessibilityValue(isCurrent ? 1 : 0)
        updateLayerColours()
    }

    /// Layer colours are CGColors, so they do not resolve themselves when the
    /// window switches between the light and dark palette.
    private func updateLayerColours() {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            layer?.backgroundColor = isCurrent ? ShellPalette.accent.cgColor : NSColor.clear.cgColor
            badgePill.layer?.backgroundColor = isCurrent
                ? ShellPalette.onAccent.cgColor
                : ShellPalette.accent.cgColor
        }
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        updateLayerColours()
    }

    /// The label and symbol are decoration; the whole pill is the control.
    override func hitTest(_ point: NSPoint) -> NSView? {
        guard let parent = superview else { return nil }
        return bounds.contains(convert(point, from: parent)) ? self : nil
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSTableViewDataSource, NSTableViewDelegate {
    var window: NSWindow!
    var workspaceContainer = NSView()
    var workspaceViews: [String: NSView] = [:]
    var navButtons: [String: SidebarNavButton] = [:]
    var currentWorkspace = "scan"
    var themeToggleButton: NSButton?
    let rootField = NSTextField()
    let quarantineField = NSComboBox()
    let exclusionsField = NSTextField(
        string: "Backups, Backup, Edits, Mixdown, Mixdowns, Exports, Export, Bounces, Freeze, .Trash*"
    )
    let backupPolicy = NSPopUpButton()
    let summaryLabel = NSTextField(labelWithString: "No scan yet")
    let cleanupSelectionLabel = NSTextField(
        labelWithString: "Scan a folder, then select Ready projects."
    )
    let recoveryStatusLabel = NSTextField(
        labelWithString: "Choose a quarantine location to manage recovery sessions."
    )
    let phaseLabel = NSTextField(labelWithString: "Ready")
    let progressCountLabel = NSTextField(labelWithString: "")
    let statusLabel = NSTextField(labelWithString: "Choose a project archive folder to run a local safety scan.")
    let progress = NSProgressIndicator()
    let scanButton = NSButton(title: "Scan (Read Only)", target: nil, action: nil)
    let archiveQueueButton = NSButton(title: "Build Archive Queue", target: nil, action: nil)
    let validateNormalizedButton = NSButton(title: "Validate Nuendo Cleanup…", target: nil, action: nil)
    let applyNormalizedButton = NSButton(title: "Quarantine Validated Copy…", target: nil, action: nil)
    let clearNormalizedButton = NSButton(title: "Clear Validated Batch", target: nil, action: nil)
    let applyButton = NSButton(title: "Apply to Controlled Copy…", target: nil, action: nil)
    let selectAllButton = NSButton(title: "Select All Ready", target: nil, action: nil)
    let deselectAllButton = NSButton(title: "Deselect All", target: nil, action: nil)
    let restoreButton = NSButton(title: "Restore Session…", target: nil, action: nil)
    let purgeButton = NSButton(title: "Delete (Rewrite Required)", target: nil, action: nil)
    let backupReviewButton = NSButton(title: "Review Backups…", target: nil, action: nil)
    let backupApplyButton = NSButton(title: "Apply Backup Policy…", target: nil, action: nil)
    let projectsTable = NSTableView()
    let mediaTable = NSTableView()
    let previousProjectsButton = NSButton(title: "Previous Projects", target: nil, action: nil)
    let nextProjectsButton = NSButton(title: "Next Projects", target: nil, action: nil)
    let previousMediaButton = NSButton(title: "Previous Media", target: nil, action: nil)
    let nextMediaButton = NSButton(title: "Next Media", target: nil, action: nil)
    let projectPageLabel = NSTextField(labelWithString: "No project rows")
    let mediaPageLabel = NSTextField(labelWithString: "No media rows")
    let advancedOptionsButton = NSButton(
        checkboxWithTitle: "Show advanced scan options", target: nil, action: nil
    )
    let scanOptionsStack = NSStackView()
    let legacyToolsButton = NSButton(title: "Legacy shared archive tools", target: nil, action: nil)
    let legacyToolsStack = NSStackView()
    let backupToolsButton = NSButton(title: "Backup cleanup", target: nil, action: nil)
    let backupToolsStack = NSStackView()
    let deleteOptionsButton = NSButton(title: "Permanent deletion", target: nil, action: nil)
    let deleteOptionsStack = NSStackView()
    var projects: [[String: Any]] = []
    var media: [[String: Any]] = []
    var backups: [[String: Any]] = []
    var backupProtectMedia = false
    var currentScanKind = "full_safety_scan"
    var inventorySummary: [String: Any] = [:]
    var running: Process?
    var terminationPending = false
    var aboutPanel: NSPanel?
    var currentReport: URL?
    var currentReportRoot: String?
    var currentSession: URL?
    var currentNormalizationReport: URL?
    var normalizationReports: [URL] = []
    var rewriteReady = false
    var scanCompleted = false
    var selectedProjectPaths = Set<String>()
    var isScanning = false
    var isBuildingArchiveQueue = false
    var isNormalizedTransaction = false
    var scanCancelled = false
    let projectPageSize = 200
    let mediaPageSize = 500
    var projectPage = 0
    var mediaPage = 0
    var knownProjectPaths = Set<String>()
    var uiRefreshScheduled = false
    var pendingScanProgress: ScanProgressLine?
    var progressRefreshScheduled = false
    var lastProgressRender = Date.distantPast

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        applyStoredTheme()
        buildMainMenu()
        buildWindow()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let task = running, task.isRunning else { return .terminateNow }
        terminationPending = true
        task.terminate()
        return .terminateLater
    }

    func buildMainMenu() {
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        let about = appMenu.addItem(
            withTitle: "About DAW Project Cleaner", action: #selector(showSupport), keyEquivalent: ""
        )
        about.target = self
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Hide DAW Project Cleaner", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = appMenu.addItem(
            withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h"
        )
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        let quit = appMenu.addItem(
            withTitle: "Quit DAW Project Cleaner", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"
        )
        for item in appMenu.items where item !== about { item.target = NSApp }
        quit.target = NSApp
        appItem.submenu = appMenu
        NSApp.mainMenu = mainMenu
    }

    func label(_ value: String) -> NSTextField {
        let field = NSTextField(labelWithString: value)
        field.font = NSFont.systemFont(ofSize: 12)
        return field
    }

    func multilineLabel(_ value: String, color: NSColor = .secondaryLabelColor) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: value)
        field.font = NSFont.systemFont(ofSize: 12)
        field.textColor = color
        field.maximumNumberOfLines = 0
        field.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return field
    }

    func sectionTitle(_ value: String) -> NSTextField {
        let field = NSTextField(labelWithString: value)
        field.font = NSFont.systemFont(ofSize: 15, weight: .semibold)
        return field
    }

    func separator() -> NSView {
        let view = NSView()
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.separatorColor.cgColor
        view.heightAnchor.constraint(equalToConstant: 1).isActive = true
        return view
    }

    func page(with stack: NSStackView) -> NSView {
        let page = NSView()
        stack.translatesAutoresizingMaskIntoConstraints = false
        page.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: page.leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: page.trailingAnchor, constant: -14),
            stack.topAnchor.constraint(equalTo: page.topAnchor, constant: 14),
            stack.bottomAnchor.constraint(equalTo: page.bottomAnchor, constant: -12),
        ])
        return page
    }

    func button(_ title: String, _ action: Selector) -> NSButton {
        let item = NSButton(title: title, target: self, action: action)
        item.bezelStyle = .rounded
        return item
    }

    func configureDisclosure(_ item: NSButton, action: Selector) {
        item.setButtonType(.pushOnPushOff)
        item.bezelStyle = .inline
        item.isBordered = false
        item.alignment = .left
        item.imagePosition = .imageLeading
        item.imageHugsTitle = true
        item.target = self
        item.action = action
        item.state = .off
        item.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        setDisclosure(item, expanded: false)
    }

    func setDisclosure(_ item: NSButton, expanded: Bool) {
        item.state = expanded ? .on : .off
        item.image = NSImage(
            systemSymbolName: expanded ? "chevron.down" : "chevron.right",
            accessibilityDescription: expanded ? "Expanded" : "Collapsed"
        )
        item.contentTintColor = .secondaryLabelColor
    }

    func addColumn(_ table: NSTableView, _ id: String, _ title: String, _ width: CGFloat) {
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
        column.title = title
        column.width = width
        column.minWidth = 60
        table.addTableColumn(column)
    }

    func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "DAW Project Cleaner"
        window.center()
        window.minSize = NSSize(width: 900, height: 580)
        window.maxSize = NSSize(width: 100_000, height: 100_000)
        window.collectionBehavior.insert(.fullScreenPrimary)
        window.setFrameAutosaveName("DAWProjectCleanerMainWindow")

        for field in [summaryLabel, phaseLabel, progressCountLabel, statusLabel, projectPageLabel, mediaPageLabel] {
            field.lineBreakMode = .byTruncatingTail
            field.maximumNumberOfLines = 1
            field.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        }

        rootField.placeholderString = "/Volumes/Server/Projects"
        quarantineField.placeholderString = "/Volumes/Server/DAW Project Cleaner Quarantine"
        let quarantineHistory = UserDefaults.standard.stringArray(
            forKey: "SharedQuarantinePaths"
        ) ?? []
        quarantineField.addItems(withObjectValues: quarantineHistory)
        quarantineField.stringValue = UserDefaults.standard.string(
            forKey: "SharedQuarantinePath"
        ) ?? quarantineHistory.first ?? ""
        quarantineField.isEditable = true
        quarantineField.completes = true
        backupPolicy.addItems(withTitles: [
            "Archive cleanup — quarantine all classified backups (Recommended)",
            "Working project — keep newest 5 and protect media",
            "Working project — keep all and protect media",
            "Working project — keep newest 10 and protect media",
            "Working project — keep newest 3 and protect media",
            "Working project — keep newest 1 and protect media",
        ])
        let savedBackupPolicy = UserDefaults.standard.integer(
            forKey: "BackupPolicyIndex"
        )
        backupPolicy.selectItem(at: min(max(savedBackupPolicy, 0), 5))
        let choose = button("Choose Folder…", #selector(chooseRoot))
        let chooseQuarantine = button("Choose Location…", #selector(chooseQuarantineRoot))
        scanButton.target = self
        scanButton.action = #selector(startScan)
        archiveQueueButton.target = self
        archiveQueueButton.action = #selector(startArchiveQueue)
        validateNormalizedButton.target = self
        validateNormalizedButton.action = #selector(startNormalizationValidation)
        applyNormalizedButton.target = self
        applyNormalizedButton.action = #selector(startNormalizedApply)
        applyNormalizedButton.isEnabled = false
        clearNormalizedButton.target = self
        clearNormalizedButton.action = #selector(clearNormalizationBatch)
        clearNormalizedButton.isEnabled = false
        applyButton.target = self
        applyButton.action = #selector(startApply)
        applyButton.isEnabled = false
        selectAllButton.target = self
        selectAllButton.action = #selector(selectAllReady)
        selectAllButton.isEnabled = false
        deselectAllButton.target = self
        deselectAllButton.action = #selector(deselectAll)
        deselectAllButton.isEnabled = false
        restoreButton.target = self
        restoreButton.action = #selector(startRestore)
        purgeButton.target = self
        purgeButton.action = #selector(startPurge)
        purgeButton.isEnabled = false
        backupReviewButton.target = self
        backupReviewButton.action = #selector(reviewBackups)
        backupReviewButton.isEnabled = false
        backupApplyButton.target = self
        backupApplyButton.action = #selector(startBackupApply)
        backupApplyButton.isEnabled = false

        advancedOptionsButton.title = "Scan options"
        configureDisclosure(advancedOptionsButton, action: #selector(toggleAdvancedOptions))
        advancedOptionsButton.state = UserDefaults.standard.bool(
            forKey: "ShowAdvancedScanOptions"
        ) ? .on : .off
        configureDisclosure(legacyToolsButton, action: #selector(toggleLegacyTools))
        configureDisclosure(backupToolsButton, action: #selector(toggleBackupTools))
        configureDisclosure(deleteOptionsButton, action: #selector(toggleDeleteOptions))

        let rootRow = NSStackView(views: [rootField, choose, scanButton])
        rootRow.orientation = .horizontal
        rootRow.spacing = 8
        rootField.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let quarantineRow = NSStackView(views: [quarantineField, chooseQuarantine])
        quarantineRow.orientation = .horizontal
        quarantineRow.spacing = 8
        quarantineField.setContentHuggingPriority(.defaultLow, for: .horizontal)

        selectAllButton.title = "Select All Ready"
        deselectAllButton.title = "Clear Selection"
        applyButton.title = "Clean Selected Projects…"
        restoreButton.title = "Restore a Cleanup…"
        purgeButton.title = "Permanently Delete Quarantine…"
        scanButton.bezelColor = .controlAccentColor
        applyButton.bezelColor = .controlAccentColor
        restoreButton.bezelColor = .controlAccentColor
        archiveQueueButton.title = "Analyze Shared Archive…"
        validateNormalizedButton.title = "Validate Cleaned Project…"
        applyNormalizedButton.title = "Quarantine Validated Project…"
        clearNormalizedButton.title = "Clear Validation"
        backupReviewButton.title = "Review Backup Plan…"
        backupApplyButton.title = "Quarantine Approved Backups…"
        let selectionRow = NSStackView(views: [selectAllButton, deselectAllButton, NSView()])
        selectionRow.orientation = .horizontal
        selectionRow.spacing = 8
        let normalizationRow = NSStackView(views: [archiveQueueButton, validateNormalizedButton, applyNormalizedButton, clearNormalizedButton, NSView()])
        normalizationRow.orientation = .horizontal
        normalizationRow.spacing = 8
        let backupRow = NSStackView(views: [backupReviewButton, backupApplyButton, NSView()])
        backupRow.orientation = .horizontal
        backupRow.spacing = 8
        let recoveryRow = NSStackView(views: [restoreButton, NSView()])
        recoveryRow.orientation = .horizontal
        recoveryRow.spacing = 8
        summaryLabel.font = NSFont.boldSystemFont(ofSize: 14)
        phaseLabel.font = NSFont.boldSystemFont(ofSize: 13)
        progressCountLabel.alignment = .right
        progressCountLabel.textColor = .secondaryLabelColor
        projectPageLabel.textColor = .secondaryLabelColor
        mediaPageLabel.textColor = .secondaryLabelColor

        previousProjectsButton.target = self
        previousProjectsButton.action = #selector(previousProjectsPage)
        nextProjectsButton.target = self
        nextProjectsButton.action = #selector(nextProjectsPage)
        previousMediaButton.target = self
        previousMediaButton.action = #selector(previousMediaPage)
        nextMediaButton.target = self
        nextMediaButton.action = #selector(nextMediaPage)
        for item in [previousProjectsButton, nextProjectsButton, previousMediaButton, nextMediaButton] {
            item.bezelStyle = .rounded
        }

        projectsTable.delegate = self
        projectsTable.dataSource = self
        projectsTable.headerView = NSTableHeaderView()
        addColumn(projectsTable, "select", "Use", 44)
        addColumn(projectsTable, "project", "Project", 310)
        addColumn(projectsTable, "status", "Status", 70)
        addColumn(projectsTable, "profile", "Format", 100)
        addColumn(projectsTable, "rewrite", "Cleanup", 115)
        addColumn(projectsTable, "candidates", "Files", 60)
        addColumn(projectsTable, "space", "Space", 90)
        projectsTable.usesAlternatingRowBackgroundColors = true
        projectsTable.rowHeight = 25

        mediaTable.delegate = self
        mediaTable.dataSource = self
        mediaTable.headerView = NSTableHeaderView()
        addColumn(mediaTable, "name", "Media", 180)
        addColumn(mediaTable, "class", "Classification", 115)
        addColumn(mediaTable, "action", "Action", 70)
        addColumn(mediaTable, "size", "Size", 80)
        addColumn(mediaTable, "reason", "Evidence / reason", 330)
        mediaTable.usesAlternatingRowBackgroundColors = true
        mediaTable.rowHeight = 25

        let projectScroll = NSScrollView()
        projectScroll.documentView = projectsTable
        projectScroll.hasVerticalScroller = true
        projectScroll.hasHorizontalScroller = true
        projectScroll.borderType = .bezelBorder
        projectScroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        projectScroll.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        projectScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 90).isActive = true
        let mediaScroll = NSScrollView()
        mediaScroll.documentView = mediaTable
        mediaScroll.hasVerticalScroller = true
        mediaScroll.hasHorizontalScroller = true
        mediaScroll.borderType = .bezelBorder
        mediaScroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        mediaScroll.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        mediaScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 90).isActive = true
        let projectHeader = NSStackView(views: [sectionTitle("Projects"), NSView(), previousProjectsButton, projectPageLabel, nextProjectsButton])
        projectHeader.orientation = .horizontal
        projectHeader.spacing = 8
        let mediaHeader = NSStackView(views: [sectionTitle("Files in selected project"), NSView(), previousMediaButton, mediaPageLabel, nextMediaButton])
        mediaHeader.orientation = .horizontal
        mediaHeader.spacing = 8
        let projectPane = NSStackView(views: [projectHeader, projectScroll])
        projectPane.orientation = .vertical
        projectPane.spacing = 6
        let mediaPane = NSStackView(views: [mediaHeader, mediaScroll])
        mediaPane.orientation = .vertical
        mediaPane.spacing = 6
        let split = NSSplitView()
        split.isVertical = false
        split.dividerStyle = .thin
        split.addArrangedSubview(projectPane)
        split.addArrangedSubview(mediaPane)
        split.setPosition(250, ofDividerAt: 0)

        progress.isIndeterminate = false
        progress.minValue = 0
        progress.maxValue = 1

        let phaseRow = NSStackView(views: [phaseLabel, NSView(), progressCountLabel])
        phaseRow.orientation = .horizontal
        phaseRow.spacing = 8
        scanOptionsStack.orientation = .vertical
        scanOptionsStack.alignment = .leading
        scanOptionsStack.spacing = 5
        for view in [label("Project backup policy"), backupPolicy,
                     label("Excluded folder names (comma-separated)"), exclusionsField] {
            scanOptionsStack.addArrangedSubview(view)
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: scanOptionsStack.widthAnchor).isActive = true
        }
        scanOptionsStack.isHidden = advancedOptionsButton.state != .on

        let legacyDescription = multilineLabel(
            "For older folders where several projects share one Audio folder. Analyze dependencies, clean each project in Nuendo, then validate the cleaned result."
        )
        legacyToolsStack.orientation = .vertical
        legacyToolsStack.alignment = .leading
        legacyToolsStack.spacing = 7
        for view in [legacyDescription, normalizationRow] {
            legacyToolsStack.addArrangedSubview(view)
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: legacyToolsStack.widthAnchor).isActive = true
        }
        legacyToolsStack.isHidden = true

        let backupDescription = multilineLabel(
            "Review classified project backups before moving approved old versions to recoverable quarantine. Backup files are never rewritten."
        )
        backupToolsStack.orientation = .vertical
        backupToolsStack.alignment = .leading
        backupToolsStack.spacing = 7
        for view in [backupDescription, backupRow] {
            backupToolsStack.addArrangedSubview(view)
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: backupToolsStack.widthAnchor).isActive = true
        }
        backupToolsStack.isHidden = true

        let deleteDescription = multilineLabel(
            "Use only after the recovery window has passed. Owner authentication and exact session validation are required."
        )
        let deleteRow = NSStackView(views: [purgeButton, NSView()])
        deleteRow.orientation = .horizontal
        deleteRow.spacing = 8
        deleteOptionsStack.orientation = .vertical
        deleteOptionsStack.alignment = .leading
        deleteOptionsStack.spacing = 7
        for view in [deleteDescription, deleteRow] {
            deleteOptionsStack.addArrangedSubview(view)
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: deleteOptionsStack.widthAnchor).isActive = true
        }
        deleteOptionsStack.isHidden = true

        let scanStack = NSStackView(views: [
            sectionTitle("1. Choose what to scan"),
            multilineLabel("Select one archive folder. The app never scans the whole Mac when this field is empty."),
            rootRow,
            advancedOptionsButton, scanOptionsStack,
            separator(),
            sectionTitle("2. Review the safety result"),
            summaryLabel, selectionRow,
            phaseRow, progress, statusLabel,
            split,
        ])
        scanStack.orientation = .vertical
        scanStack.alignment = .leading
        scanStack.spacing = 7

        let cleanupStack = NSStackView(views: [
            sectionTitle("Cleanup"),
            multilineLabel("Validated projects selected in Scan & Review appear here. Cleanup always moves files to quarantine first."),
            cleanupSelectionLabel,
            applyButton,
            separator(),
            sectionTitle("More cleanup options"),
            legacyToolsButton, legacyToolsStack,
            backupToolsButton, backupToolsStack,
            NSView(),
        ])
        cleanupStack.orientation = .vertical
        cleanupStack.alignment = .leading
        cleanupStack.spacing = 10

        let recoveryStack = NSStackView(views: [
            sectionTitle("Recovery & quarantine"),
            multilineLabel("Use a location on the same server volume as the projects. This Mac remembers recent locations, and Restore verifies every file before moving anything back."),
            label("Quarantine location"), quarantineRow,
            recoveryStatusLabel,
            recoveryRow,
            separator(),
            deleteOptionsButton, deleteOptionsStack,
            NSView(),
        ])
        recoveryStack.orientation = .vertical
        recoveryStack.alignment = .leading
        recoveryStack.spacing = 10

        let scanPage = page(with: scanStack)
        let cleanupPage = page(with: cleanupStack)
        let recoveryPage = page(with: recoveryStack)
        workspaceViews = ["scan": scanPage, "cleanup": cleanupPage, "recovery": recoveryPage]

        split.setContentHuggingPriority(.defaultLow, for: .vertical)
        split.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        for view in [rootRow, advancedOptionsButton, scanOptionsStack,
                     summaryLabel, selectionRow, phaseRow, split, progress, statusLabel] {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: scanStack.widthAnchor).isActive = true
        }
        for view in [cleanupSelectionLabel, legacyToolsStack, backupToolsStack] {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: cleanupStack.widthAnchor).isActive = true
        }
        for view in [quarantineRow, recoveryStatusLabel, recoveryRow, deleteOptionsStack] {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: recoveryStack.widthAnchor).isActive = true
        }
        split.heightAnchor.constraint(greaterThanOrEqualToConstant: 220).isActive = true

        // Workspaces are stacked in one container and swapped by the sidebar,
        // so every page keeps its state while another one is on screen.
        workspaceContainer.translatesAutoresizingMaskIntoConstraints = false
        for pageView in workspaceViews.values {
            pageView.translatesAutoresizingMaskIntoConstraints = false
            workspaceContainer.addSubview(pageView)
            NSLayoutConstraint.activate([
                pageView.leadingAnchor.constraint(equalTo: workspaceContainer.leadingAnchor),
                pageView.trailingAnchor.constraint(equalTo: workspaceContainer.trailingAnchor),
                pageView.topAnchor.constraint(equalTo: workspaceContainer.topAnchor),
                pageView.bottomAnchor.constraint(equalTo: workspaceContainer.bottomAnchor),
            ])
        }

        let sidebar = buildSidebar()
        let sidebarEdge = ShellSeparator()
        sidebarEdge.translatesAutoresizingMaskIntoConstraints = false

        let content = window.contentView!
        content.addSubview(sidebar)
        content.addSubview(sidebarEdge)
        content.addSubview(workspaceContainer)
        NSLayoutConstraint.activate([
            sidebar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            sidebar.topAnchor.constraint(equalTo: content.topAnchor),
            sidebar.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            sidebar.widthAnchor.constraint(equalToConstant: 220),
            sidebarEdge.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            sidebarEdge.topAnchor.constraint(equalTo: content.topAnchor),
            sidebarEdge.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            sidebarEdge.widthAnchor.constraint(equalToConstant: 1),
            workspaceContainer.leadingAnchor.constraint(equalTo: sidebarEdge.trailingAnchor),
            workspaceContainer.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            workspaceContainer.topAnchor.constraint(equalTo: content.topAnchor),
            workspaceContainer.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])
        installTitlebarAccessory()
        goToWorkspace(currentWorkspace)
        purgeButton.isEnabled = !purgeableSessionOptions(
            statuses: ["complete", "purging"]
        ).isEmpty
        updateRecoveryStatus()
        updateScanModeControls()
        updatePageControls()
    }

    // MARK: - Shell

    func sidebarFooterLine(_ value: String) -> NSTextField {
        let field = NSTextField(labelWithString: value)
        field.font = .systemFont(ofSize: 10.5)
        field.textColor = ShellPalette.textTertiary
        return field
    }

    func buildSidebar() -> NSView {
        let sidebar = NSVisualEffectView()
        sidebar.material = .sidebar
        sidebar.blendingMode = .behindWindow
        sidebar.state = .followsWindowActiveState
        sidebar.translatesAutoresizingMaskIntoConstraints = false

        let appIcon = NSImageView(image: NSApp.applicationIconImage)
        appIcon.imageScaling = .scaleProportionallyUpOrDown
        appIcon.translatesAutoresizingMaskIntoConstraints = false
        appIcon.widthAnchor.constraint(equalToConstant: 34).isActive = true
        appIcon.heightAnchor.constraint(equalToConstant: 34).isActive = true

        let brandTitle = NSTextField(labelWithString: "DAW Project Cleaner")
        brandTitle.font = .systemFont(ofSize: 12.5, weight: .semibold)
        brandTitle.textColor = ShellPalette.text
        let brandSubtitle = NSTextField(labelWithString: "Reclaim space, safely")
        brandSubtitle.font = .systemFont(ofSize: 11)
        brandSubtitle.textColor = ShellPalette.textTertiary
        let brandText = NSStackView(views: [brandTitle, brandSubtitle])
        brandText.orientation = .vertical
        brandText.alignment = .leading
        brandText.spacing = 1

        let brandRow = NSStackView(views: [appIcon, brandText])
        brandRow.orientation = .horizontal
        brandRow.alignment = .centerY
        brandRow.spacing = 10
        brandRow.edgeInsets = NSEdgeInsets(top: 4, left: 8, bottom: 18, right: 8)

        let navStack = NSStackView()
        navStack.orientation = .vertical
        navStack.alignment = .leading
        navStack.spacing = 2
        let workspaces: [(String, String, String)] = [
            ("scan", "Scan & Review", "magnifyingglass"),
            ("cleanup", "Cleanup", "sparkles"),
            ("recovery", "Recovery", "arrow.uturn.backward"),
        ]
        for (key, caption, symbol) in workspaces {
            let item = SidebarNavButton(
                caption: caption,
                symbol: symbol,
                target: self,
                action: #selector(selectWorkspace(_:))
            )
            item.identifier = NSUserInterfaceItemIdentifier(key)
            navButtons[key] = item
            navStack.addArrangedSubview(item)
            item.widthAnchor.constraint(equalTo: navStack.widthAnchor).isActive = true
        }

        let footer = NSStackView(views: [
            sidebarFooterLine("Local processing only"),
            sidebarFooterLine("No telemetry"),
        ])
        footer.orientation = .vertical
        footer.alignment = .leading
        footer.spacing = 1
        footer.edgeInsets = NSEdgeInsets(top: 10, left: 10, bottom: 4, right: 10)

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .vertical)

        let column = NSStackView(views: [brandRow, navStack, spacer, footer])
        column.orientation = .vertical
        column.alignment = .leading
        column.spacing = 0
        column.translatesAutoresizingMaskIntoConstraints = false
        sidebar.addSubview(column)
        NSLayoutConstraint.activate([
            column.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 10),
            column.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -10),
            column.topAnchor.constraint(equalTo: sidebar.topAnchor, constant: 16),
            column.bottomAnchor.constraint(equalTo: sidebar.bottomAnchor, constant: -16),
        ])
        for view in [brandRow, navStack, footer] {
            view.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
        }
        return sidebar
    }

    @objc func selectWorkspace(_ sender: NSButton) {
        guard let key = sender.identifier?.rawValue else { return }
        goToWorkspace(key)
    }

    /// Every workspace stays built and keeps its state; only visibility moves.
    func goToWorkspace(_ key: String) {
        guard workspaceViews[key] != nil else { return }
        currentWorkspace = key
        for (identifier, view) in workspaceViews { view.isHidden = identifier != key }
        for (identifier, item) in navButtons { item.isCurrent = identifier == key }
    }

    func installTitlebarAccessory() {
        let theme = chromeButton(
            symbol: isDarkTheme ? "moon" : "sun.max",
            action: #selector(toggleTheme),
            tooltip: "Toggle appearance",
            label: "Toggle light and dark mode"
        )
        themeToggleButton = theme
        let about = chromeButton(
            symbol: "info.circle",
            action: #selector(showSupport),
            tooltip: "About",
            label: "About DAW Project Cleaner"
        )
        let row = NSStackView(views: [theme, about])
        row.orientation = .horizontal
        row.spacing = 14
        row.edgeInsets = NSEdgeInsets(top: 0, left: 0, bottom: 0, right: 12)
        row.frame = NSRect(x: 0, y: 0, width: 92, height: 28)
        let accessory = NSTitlebarAccessoryViewController()
        accessory.layoutAttribute = .trailing
        accessory.view = row
        window.addTitlebarAccessoryViewController(accessory)
    }

    func chromeButton(symbol: String, action: Selector, tooltip: String, label: String) -> NSButton {
        let item = NSButton(frame: NSRect(x: 0, y: 0, width: 26, height: 26))
        item.target = self
        item.action = action
        item.title = ""
        item.isBordered = false
        item.bezelStyle = .regularSquare
        item.imagePosition = .imageOnly
        item.image = themeSymbol(symbol, label: label)
        item.contentTintColor = ShellPalette.textSecondary
        item.toolTip = tooltip
        item.setAccessibilityLabel(label)
        item.translatesAutoresizingMaskIntoConstraints = false
        item.widthAnchor.constraint(equalToConstant: 26).isActive = true
        item.heightAnchor.constraint(equalToConstant: 26).isActive = true
        return item
    }

    func themeSymbol(_ name: String, label: String) -> NSImage? {
        NSImage(systemSymbolName: name, accessibilityDescription: label)?
            .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 14, weight: .regular))
    }

    var isDarkTheme: Bool {
        NSApp.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
    }

    /// The design ships a two-state light/dark switch. Until the user picks a
    /// side the app follows the system setting, so a Mac already in dark mode
    /// does not open into a forced light window.
    func applyStoredTheme() {
        guard let stored = UserDefaults.standard.string(forKey: "ShellAppearance") else { return }
        NSApp.appearance = NSAppearance(named: stored == "dark" ? .darkAqua : .aqua)
    }

    @objc func toggleTheme() {
        let next: NSAppearance.Name = isDarkTheme ? .aqua : .darkAqua
        NSApp.appearance = NSAppearance(named: next)
        UserDefaults.standard.set(next == .darkAqua ? "dark" : "light", forKey: "ShellAppearance")
        refreshThemeButton()
    }

    func refreshThemeButton() {
        themeToggleButton?.image = themeSymbol(
            isDarkTheme ? "moon" : "sun.max",
            label: "Toggle light and dark mode"
        )
    }

    @objc func toggleAdvancedOptions() {
        let shown = advancedOptionsButton.state == .on
        setDisclosure(advancedOptionsButton, expanded: shown)
        scanOptionsStack.isHidden = !shown
        UserDefaults.standard.set(shown, forKey: "ShowAdvancedScanOptions")
    }

    @objc func toggleLegacyTools() {
        let shown = legacyToolsButton.state == .on
        setDisclosure(legacyToolsButton, expanded: shown)
        legacyToolsStack.isHidden = !shown
    }

    @objc func toggleBackupTools() {
        let shown = backupToolsButton.state == .on
        setDisclosure(backupToolsButton, expanded: shown)
        backupToolsStack.isHidden = !shown
    }

    @objc func toggleDeleteOptions() {
        let shown = deleteOptionsButton.state == .on
        setDisclosure(deleteOptionsButton, expanded: shown)
        deleteOptionsStack.isHidden = !shown
    }

    func updateRecoveryStatus() {
        let path = quarantineField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        recoveryStatusLabel.stringValue = path.isEmpty
            ? "No quarantine location selected. Cleanup actions that need shared quarantine stay unavailable."
            : "Current location: \(path)"
    }

    func displayedProjects() -> [[String: Any]] {
        let start = min(projectPage * projectPageSize, projects.count)
        let end = min(start + projectPageSize, projects.count)
        return start < end ? Array(projects[start..<end]) : []
    }

    func displayedMedia() -> [[String: Any]] {
        let start = min(mediaPage * mediaPageSize, media.count)
        let end = min(start + mediaPageSize, media.count)
        return start < end ? Array(media[start..<end]) : []
    }

    func updatePageControls() {
        let projectPages = max(1, Int(ceil(Double(projects.count) / Double(projectPageSize))))
        projectPage = min(projectPage, projectPages - 1)
        let projectStart = projects.isEmpty ? 0 : projectPage * projectPageSize + 1
        let projectEnd = min((projectPage + 1) * projectPageSize, projects.count)
        projectPageLabel.stringValue = projects.isEmpty
            ? "No project rows"
            : "Projects \(projectStart)–\(projectEnd) of \(projects.count) · locally cached"
        previousProjectsButton.isEnabled = projectPage > 0
        nextProjectsButton.isEnabled = projectPage + 1 < projectPages

        let mediaPages = max(1, Int(ceil(Double(media.count) / Double(mediaPageSize))))
        mediaPage = min(mediaPage, mediaPages - 1)
        let mediaStart = media.isEmpty ? 0 : mediaPage * mediaPageSize + 1
        let mediaEnd = min((mediaPage + 1) * mediaPageSize, media.count)
        mediaPageLabel.stringValue = media.isEmpty
            ? "No media rows"
            : "Media \(mediaStart)–\(mediaEnd) of \(media.count) · locally cached"
        previousMediaButton.isEnabled = mediaPage > 0
        nextMediaButton.isEnabled = mediaPage + 1 < mediaPages
    }

    @objc func previousProjectsPage() {
        guard projectPage > 0 else { return }
        projectPage -= 1
        media = []
        mediaPage = 0
        projectsTable.deselectAll(nil)
        projectsTable.reloadData()
        mediaTable.reloadData()
        updatePageControls()
    }

    @objc func nextProjectsPage() {
        guard (projectPage + 1) * projectPageSize < projects.count else { return }
        projectPage += 1
        media = []
        mediaPage = 0
        projectsTable.deselectAll(nil)
        projectsTable.reloadData()
        mediaTable.reloadData()
        updatePageControls()
    }

    @objc func previousMediaPage() {
        guard mediaPage > 0 else { return }
        mediaPage -= 1
        mediaTable.reloadData()
        updatePageControls()
    }

    @objc func nextMediaPage() {
        guard (mediaPage + 1) * mediaPageSize < media.count else { return }
        mediaPage += 1
        mediaTable.reloadData()
        updatePageControls()
    }

    func scheduleTableRefresh() {
        guard !uiRefreshScheduled else { return }
        uiRefreshScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self = self else { return }
            self.uiRefreshScheduled = false
            self.projectsTable.reloadData()
            self.updatePageControls()
            self.refreshSummary(partial: true)
        }
    }

    func updateScanModeControls() {
        exclusionsField.isEnabled = true
        backupPolicy.isEnabled = true
        exclusionsField.toolTip = "Folder names omitted from the scan"
        backupPolicy.toolTip = nil
        if !isScanning {
            scanButton.title = "Scan Folder"
        }
        if projects.isEmpty && currentReportRoot == nil {
            statusLabel.stringValue = "The scan checks project references, shared media and backups before cleanup."
        }
    }

    @objc func chooseRoot() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose"
        if panel.runModal() == .OK, let url = panel.url { rootField.stringValue = url.path }
    }

    @objc func chooseQuarantineRoot() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.prompt = "Choose Quarantine"
        if panel.runModal() == .OK, let url = panel.url {
            quarantineField.stringValue = url.path
            rememberQuarantinePath(url.path)
            purgeButton.isEnabled = running == nil && !purgeableSessionOptions(
                statuses: ["complete", "purging"]
            ).isEmpty
        }
    }

    func rememberQuarantinePath(_ path: String) {
        let clean = URL(fileURLWithPath: path).standardizedFileURL.path
        var history = UserDefaults.standard.stringArray(
            forKey: "SharedQuarantinePaths"
        ) ?? []
        history.removeAll { $0 == clean }
        history.insert(clean, at: 0)
        history = Array(history.prefix(12))
        UserDefaults.standard.set(clean, forKey: "SharedQuarantinePath")
        UserDefaults.standard.set(history, forKey: "SharedQuarantinePaths")
        quarantineField.removeAllItems()
        quarantineField.addItems(withObjectValues: history)
        quarantineField.stringValue = clean
        updateRecoveryStatus()
    }

    func rememberedQuarantinePaths() -> [String] {
        let current = quarantineField.stringValue.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let history = UserDefaults.standard.stringArray(
            forKey: "SharedQuarantinePaths"
        ) ?? []
        return Array(Set(([current] + history).filter { !$0.isEmpty })).sorted()
    }

    func rememberLocalQuarantineRoot(_ projectRoot: String) {
        let control = URL(fileURLWithPath: projectRoot).standardizedFileURL
            .appendingPathComponent(
                ".daw-project-cleaner-quarantine", isDirectory: true
            ).path
        var history = UserDefaults.standard.stringArray(
            forKey: "LocalQuarantinePaths"
        ) ?? []
        history.removeAll { $0 == control }
        history.insert(control, at: 0)
        UserDefaults.standard.set(
            Array(history.prefix(12)), forKey: "LocalQuarantinePaths"
        )
    }

    func setBusy(_ busy: Bool) {
        scanButton.isEnabled = !busy
        if !busy { updateScanModeControls() }
        restoreButton.isEnabled = !busy
        applyButton.isEnabled = !busy && rewriteReady
        selectAllButton.isEnabled = !busy && scanCompleted && !readyProjectPaths().isEmpty
        deselectAllButton.isEnabled = !busy && scanCompleted && !selectedProjectPaths.isEmpty
        purgeButton.isEnabled = !busy && !purgeableSessionOptions(
            statuses: ["complete", "purging"]
        ).isEmpty
        backupReviewButton.isEnabled = !busy && !backups.isEmpty
        backupApplyButton.isEnabled = !busy && scanCompleted && backups.contains {
            ($0["action"] as? String) == "quarantine"
        }
        archiveQueueButton.isEnabled = !busy || isBuildingArchiveQueue
        if !isBuildingArchiveQueue { archiveQueueButton.title = "Analyze Shared Archive…" }
        validateNormalizedButton.isEnabled = !busy
        applyNormalizedButton.isEnabled = !busy && !normalizationReports.isEmpty
        clearNormalizedButton.isEnabled = !busy && !normalizationReports.isEmpty
        updatePageControls()
    }

    func backendURL() -> URL? {
        Bundle.main.resourceURL?.appendingPathComponent("backend/daw-project-cleaner-backend")
    }

    func reportURL(quick: Bool = false) throws -> URL {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { throw NSError(domain: "Report", code: 1) }
        let folder = base.appendingPathComponent("DAW Project Cleaner/reports", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder.appendingPathComponent(
            quick ? "latest-quick-scan.json" : "latest-scan.json"
        )
    }

    func quickStateURL() throws -> URL {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { throw NSError(domain: "Report", code: 1) }
        let folder = base.appendingPathComponent(
            "DAW Project Cleaner/reports", isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: folder, withIntermediateDirectories: true
        )
        return folder.appendingPathComponent("latest-quick-scan-state.json")
    }

    func archiveQueueReportURLs() throws -> (audit: URL, queue: URL) {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { throw NSError(domain: "Report", code: 1) }
        let folder = base.appendingPathComponent(
            "DAW Project Cleaner/reports", isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: folder, withIntermediateDirectories: true
        )
        return (
            folder.appendingPathComponent("latest-archive-audit.json"),
            folder.appendingPathComponent("latest-archive-queue.json")
        )
    }

    func normalizationReportURL() throws -> URL {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { throw NSError(domain: "Report", code: 1) }
        let folder = base.appendingPathComponent(
            "DAW Project Cleaner/reports", isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: folder, withIntermediateDirectories: true
        )
        return folder.appendingPathComponent("latest-normalization-validation.json")
    }

    func chooseProjectFile(prompt: String) -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = ["npr", "cpr"].compactMap {
            UTType(filenameExtension: $0)
        }
        panel.prompt = prompt
        return panel.runModal() == .OK ? panel.url : nil
    }

    @objc func startNormalizationValidation() {
        guard running == nil else { return }
        guard let control = chooseProjectFile(prompt: "Choose CONTROL Project") else {
            return
        }
        guard let cleaned = chooseProjectFile(prompt: "Choose CLEANED Project") else {
            return
        }
        let controlParent = control.deletingLastPathComponent().standardizedFileURL
        let cleanedParent = cleaned.deletingLastPathComponent().standardizedFileURL
        guard controlParent.path == cleanedParent.path else {
            showError("CONTROL and CLEANED must be inside the same disposable project folder.")
            return
        }
        guard control.standardizedFileURL.path != cleaned.standardizedFileURL.path else {
            showError("Choose two different project files: the pre-cleanup CONTROL and the Nuendo-cleaned survivor.")
            return
        }
        let confirmation = "Before continuing, the CLEANED project must have been closed and reopened in the matching Nuendo version after Remove Unused Media → Remove from Pool. Confirm that it played normally, showed no missing-media dialog, and the removed items were absent from the Pool.\n\nNo files will be moved during validation."
        guard warning(
            "Did the CLEANED project reopen and play correctly?", confirmation,
            proceed: "Yes — validate the pair"
        ) else { return }
        let report: URL
        do { report = try normalizationReportURL() }
        catch {
            showError("Could not prepare the private report folder: \(error.localizedDescription)")
            return
        }
        setBusy(true)
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        phaseLabel.stringValue = "Validating Nuendo cleanup"
        progressCountLabel.stringValue = "Hashing projects and candidate media"
        statusLabel.stringValue = "Comparing active references, Pool state and disk media…"
        runBackend(arguments: [
            "validate-normalization", control.path, cleaned.path,
            "--media-root", controlParent.path,
            "--report", report.path,
            "--daw-open-confirmed",
        ]) { [weak self] code, output in
            guard let self = self else { return }
            self.progress.stopAnimation(nil)
            self.progress.isIndeterminate = false
            if code == 0, self.loadNormalizationSummary(report) {
                self.currentNormalizationReport = report
                self.addNormalizationReport(report)
                self.phaseLabel.stringValue = "Nuendo cleanup validated"
                self.progressCountLabel.stringValue = "\(self.normalizationReports.count) validated · Apply remains recoverable"
            } else {
                self.showError(output.isEmpty ? "Normalization validation failed safely." : output)
            }
            self.setBusy(false)
        }
    }

    func normalizationRoot(_ url: URL) -> String? {
        guard let data = try? Data(contentsOf: url),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return object["media_root"] as? String
    }

    func addNormalizationReport(_ url: URL) {
        guard let root = normalizationRoot(url) else { return }
        normalizationReports.removeAll { normalizationRoot($0) == root }
        normalizationReports.append(url)
        applyNormalizedButton.title = normalizationReports.count == 1
            ? "Quarantine Validated Project…"
            : "Quarantine Validated Batch (\(normalizationReports.count))…"
        clearNormalizedButton.isEnabled = true
    }

    @objc func clearNormalizationBatch() {
        guard running == nil else { return }
        normalizationReports.removeAll()
        currentNormalizationReport = nil
        applyNormalizedButton.title = "Quarantine Validated Project…"
        applyNormalizedButton.isEnabled = false
        clearNormalizedButton.isEnabled = false
        statusLabel.stringValue = "Validated batch cleared. No files were changed."
    }

    @discardableResult
    func loadNormalizationSummary(_ url: URL) -> Bool {
        do {
            let data = try Data(contentsOf: url)
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let summary = object["summary"] as? [String: Any],
                  (summary["final_gate_passed"] as? Bool) == true,
                  (summary["structural_valid"] as? Bool) == true,
                  let cleaned = object["cleaned"] as? [String: Any] else {
                throw NSError(domain: "Normalization", code: 1)
            }
            let active = (summary["active_references"] as? NSNumber)?.intValue ?? 0
            let candidates = (summary["candidate_files"] as? NSNumber)?.intValue ?? 0
            let bytes = (summary["candidate_bytes"] as? NSNumber)?.int64Value ?? 0
            let artifacts = (summary["project_artifacts_to_quarantine"] as? NSNumber)?.intValue ?? 0
            let survivor = URL(fileURLWithPath: cleaned["path"] as? String ?? "").lastPathComponent
            statusLabel.stringValue = "Validated: \(active) active references · \(candidates) unused media (\(humanSize(bytes))) · \(artifacts) old projects/backups · survivor: \(survivor)."
            showInfo(
                "Nuendo cleanup validated",
                "The surviving project retains \(active) active references and no Pool-only references.\n\nRecoverable quarantine plan:\n• \(candidates) unused media files — \(humanSize(bytes))\n• \(artifacts) old project/backup files\n\nNo files were moved. Review the result, then quarantine the validated project."
            )
            return true
        } catch {
            showError("Could not read the normalization report: \(error.localizedDescription)")
            return false
        }
    }

    @objc func startNormalizedApply() {
        guard running == nil, !normalizationReports.isEmpty else {
            showError("Validate a CONTROL/CLEANED pair first.")
            return
        }
        var roots: [String] = []
        var candidates = 0
        var artifacts = 0
        var bytes: Int64 = 0
        var survivors: [String] = []
        for report in normalizationReports {
            guard let data = try? Data(contentsOf: report),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let summary = object["summary"] as? [String: Any],
                  let rootPath = object["media_root"] as? String,
                  let cleaned = object["cleaned"] as? [String: Any],
                  (summary["final_gate_passed"] as? Bool) == true else {
                showError("A normalization report is unavailable or no longer passes its final gate.")
                return
            }
            roots.append(rootPath)
            candidates += (summary["candidate_files"] as? NSNumber)?.intValue ?? 0
            artifacts += (summary["project_artifacts_to_quarantine"] as? NSNumber)?.intValue ?? 0
            bytes += (summary["candidate_bytes"] as? NSNumber)?.int64Value ?? 0
            survivors.append(cleaned["path"] as? String ?? "Unknown")
        }
        let isBatch = normalizationReports.count > 1
        let explanation = "This action is only for disposable copies. The app will preflight every project before the first move, leave each CLEANED project and its active media in place, and move \(candidates) unused media files (\(humanSize(bytes))) plus \(artifacts) old project/backup files into recoverable quarantine. A later failure restores earlier completed projects.\n\nSurviving projects:\n\(survivors.joined(separator: "\n"))\n\nNothing will be permanently deleted."
        guard warning(
            isBatch ? "Quarantine the validated disposable batch?" : "Quarantine the validated disposable copy?", explanation,
            proceed: "These are copies — continue"
        ) else { return }
        let phrase = isBatch ? "QUARANTINE NORMALIZED BATCH" : "QUARANTINE NORMALIZED COPY"
        guard typedConfirmation(
            phrase,
            text: "Type the phrase exactly. After quarantine, reopen the surviving CLEANED project in Nuendo. Restore remains available."
        ) else { return }
        setBusy(true)
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        phaseLabel.stringValue = "Preparing normalized quarantine"
        progressCountLabel.stringValue = "Preflighting \(normalizationReports.count) validated project(s)"
        statusLabel.stringValue = "No file will be permanently deleted…"
        let reports = normalizationReports
        let arguments: [String]
        if isBatch {
            arguments = ["apply-normalized-batch"]
                + reports.flatMap { ["--report", $0.path] }
                + ["--confirm", phrase]
            isNormalizedTransaction = true
        } else {
            arguments = ["prepare-controlled-copy", roots[0], "--confirm", "THIS IS A DISPOSABLE COPY"]
        }
        runBackend(arguments: arguments) { [weak self] markerCode, markerOutput in
            guard let self = self else { return }
            if markerCode != 0 {
                self.progress.stopAnimation(nil)
                self.progress.isIndeterminate = false
                self.setBusy(false)
                self.showError(markerOutput.isEmpty ? "Could not validate the controlled-copy folder." : markerOutput)
                return
            }
            if isBatch {
                self.finishNormalizedApply(code: markerCode, output: markerOutput, roots: roots)
                return
            }
            self.isNormalizedTransaction = true
            self.phaseLabel.stringValue = "Quarantining validated copy"
            self.progressCountLabel.stringValue = "Persisting every recoverable move"
            self.statusLabel.stringValue = "Rechecking hashes and moving only the validated files…"
            self.runBackend(arguments: [
                "apply-normalized-pilot", reports[0].path,
                "--confirm", "QUARANTINE NORMALIZED COPY",
            ]) { [weak self] code, output in
                guard let self = self else { return }
                self.finishNormalizedApply(code: code, output: output, roots: roots)
            }
        }
    }

    func finishNormalizedApply(code: Int32, output: String, roots: [String]) {
        isNormalizedTransaction = false
        progress.stopAnimation(nil)
        progress.isIndeterminate = false
        setBusy(false)
        if code == 0 {
            currentSession = sessionURL(from: output)
            roots.forEach { rememberLocalQuarantineRoot($0) }
            normalizationReports.removeAll()
            currentNormalizationReport = nil
            applyNormalizedButton.title = "Quarantine Validated Project…"
            applyNormalizedButton.isEnabled = false
            clearNormalizedButton.isEnabled = false
            restoreButton.isEnabled = true
            phaseLabel.stringValue = "Recoverable quarantine complete"
            progressCountLabel.stringValue = "Test every CLEANED project · Restore available"
            statusLabel.stringValue = "Validated files moved to recoverable quarantine. Reopen every CLEANED project without resaving."
            showInfo(
                "Validated cleanup quarantined",
                "No file was deleted. Reopen every surviving CLEANED project in the matching Nuendo version and confirm playback with no missing-media prompt. Use Restore to return moved files.\n\n\(output)"
            )
        } else {
            showError(output.isEmpty ? "Quarantine failed safely; completed projects were rolled back." : output)
        }
    }

    @objc func startArchiveQueue() {
        if isBuildingArchiveQueue {
            archiveQueueButton.title = "Stopping…"
            archiveQueueButton.isEnabled = false
            statusLabel.stringValue = "Stopping Archive Queue safely…"
            running?.terminate()
            return
        }
        guard running == nil else { return }
        let selectedPath = rootField.stringValue.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard !selectedPath.isEmpty else {
            showError("Choose a project archive folder first.")
            return
        }
        let root = URL(fileURLWithPath: selectedPath).standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(
            atPath: root.path, isDirectory: &isDirectory
        ), isDirectory.boolValue else {
            showError("Choose an existing folder first.")
            return
        }
        let reports: (audit: URL, queue: URL)
        do { reports = try archiveQueueReportURLs() }
        catch {
            showError("Could not prepare the private report folder: \(error.localizedDescription)")
            return
        }
        isBuildingArchiveQueue = true
        setBusy(true)
        archiveQueueButton.title = "Stop Archive Queue"
        archiveQueueButton.isEnabled = true
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        phaseLabel.stringValue = "Building Nuendo 15 Archive Queue"
        progressCountLabel.stringValue = "Read-only · no archive changes"
        statusLabel.stringValue = "Discovering project families and shared media…"
        runBackend(arguments: [
            "archive-queue", root.path,
            "--audit-report", reports.audit.path,
            "--report", reports.queue.path,
            "--target", "Nuendo 15",
        ]) { [weak self] code, output in
            guard let self = self else { return }
            self.isBuildingArchiveQueue = false
            self.progress.stopAnimation(nil)
            self.progress.isIndeterminate = false
            self.archiveQueueButton.title = "Analyze Shared Archive…"
            if code == 0 {
                self.progress.minValue = 0
                self.progress.maxValue = 1
                self.progress.doubleValue = 1
                self.phaseLabel.stringValue = "Archive Queue ready"
                self.progressCountLabel.stringValue = "100% · report saved locally"
                self.showArchiveQueueSummary(reports.queue)
            } else if code == 15 || code == 9 {
                self.phaseLabel.stringValue = "Archive Queue stopped"
                self.progressCountLabel.stringValue = "No archive changes"
                self.statusLabel.stringValue = "Archive Queue stopped. Incomplete planning data was not accepted."
            } else {
                self.showError(output.isEmpty ? "Archive Queue failed." : output)
            }
            self.setBusy(false)
        }
    }

    func showArchiveQueueSummary(_ url: URL) {
        do {
            let data = try Data(contentsOf: url)
            guard let object = try JSONSerialization.jsonObject(
                with: data
            ) as? [String: Any],
                  let summary = object["summary"] as? [String: Any] else {
                throw NSError(domain: "ArchiveQueue", code: 1)
            }
            let families = (summary["families"] as? NSNumber)?.intValue ?? 0
            let projects = (summary["projects"] as? NSNumber)?.intValue ?? 0
            let ready = (summary["ready_for_operator"] as? NSNumber)?.intValue ?? 0
            let blocked = (summary["blocked"] as? NSNumber)?.intValue ?? 0
            statusLabel.stringValue = "Archive Queue: \(projects) projects in \(families) families · \(ready) ready for Nuendo 15 · \(blocked) blocked · cleanup locked."
            let alert = NSAlert()
            alert.messageText = "Archive Queue ready"
            alert.informativeText = "Found \(projects) projects in \(families) dependency families.\n\nReady for Nuendo 15 normalization: \(ready)\nBlocked by missing, ambiguous or unreadable references: \(blocked)\n\nNo server files were changed. Cleanup remains locked until every surviving normalized project is validated and reopened in Nuendo 15 without missing media.\n\nReport: \(url.path)"
            alert.addButton(withTitle: "OK")
            alert.runModal()
        } catch {
            showError("Could not read Archive Queue report: \(error.localizedDescription)")
        }
    }

    func runBackend(
        arguments: [String],
        eventHandler: (([String: Any]) -> Void)? = nil,
        completion: @escaping (Int32, String) -> Void
    ) {
        guard let executable = backendURL(), FileManager.default.isExecutableFile(atPath: executable.path) else {
            showError("The scanner backend is missing from the app bundle.")
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        running = process
        var captured = Data()
        var pending = Data()
        let ioLock = NSLock()
        let newline = Data([0x0A])
        func consume(_ data: Data) {
            guard !data.isEmpty else { return }
            ioLock.lock()
            pending.append(data)
            var lines: [String] = []
            while let range = pending.range(of: newline) {
                let lineData = pending.subdata(in: pending.startIndex..<range.lowerBound)
                pending.removeSubrange(pending.startIndex...range.lowerBound)
                if let line = String(data: lineData, encoding: .utf8) {
                    lines.append(line)
                }
            }
            ioLock.unlock()
            var ordinaryLines: [String] = []
            for line in lines {
                if line.hasPrefix("PROJECT_EVENT "),
                   let jsonData = String(line.dropFirst("PROJECT_EVENT ".count)).data(using: .utf8),
                   let event = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] {
                    DispatchQueue.main.async { eventHandler?(event) }
                } else if let scanProgress = self.parseScanProgress(line) {
                    DispatchQueue.main.async { [weak self] in
                        self?.queueScanProgress(scanProgress)
                    }
                } else if !line.isEmpty {
                    ordinaryLines.append(line)
                    DispatchQueue.main.async { [weak self] in
                        self?.statusLabel.stringValue = line
                    }
                }
            }
            if !ordinaryLines.isEmpty,
               let ordinary = (ordinaryLines.joined(separator: "\n") + "\n").data(using: .utf8) {
                ioLock.lock()
                captured.append(ordinary)
                ioLock.unlock()
            }
        }
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            _ = self
            consume(data)
        }
        process.terminationHandler = { [weak self] task in
            pipe.fileHandleForReading.readabilityHandler = nil
            consume(pipe.fileHandleForReading.readDataToEndOfFile())
            ioLock.lock()
            let text = String(data: captured, encoding: .utf8) ?? ""
            ioLock.unlock()
            DispatchQueue.main.async {
                if let self = self, self.terminationPending {
                    self.running = nil
                    self.terminationPending = false
                    NSApp.reply(toApplicationShouldTerminate: true)
                    return
                }
                self?.running = nil
                completion(task.terminationStatus, text)
            }
        }
        do { try process.run() }
        catch {
            running = nil
            completion(-1, error.localizedDescription)
        }
    }

    struct ScanProgressLine {
        var done = 0
        var total = 0
        var path = ""
        var percent: String?
        var bytes: String?
        var rate: String?
        var remaining: String?
        var discovering = false
        var measured: String?
    }

    /// Counting files says little when they range from a few hundred kilobytes
    /// to tens of megabytes, so the backend reports bytes, rate and remaining
    /// time. Discovery is announced separately because walking a large tree
    /// happens before anything can be counted at all.
    func parseScanProgress(_ line: String) -> ScanProgressLine? {
        if line.hasPrefix("DISCOVER ") {
            var value = ScanProgressLine()
            value.discovering = true
            value.path = String(line.dropFirst("DISCOVER ".count))
            return value
        }
        if line.hasPrefix("MEASURED ") {
            var value = ScanProgressLine()
            value.measured = String(line.dropFirst("MEASURED ".count))
            return value
        }
        guard line.hasPrefix("["), let close = line.firstIndex(of: "]") else {
            return nil
        }
        let numbers = line[line.index(after: line.startIndex)..<close]
            .split(separator: "/")
        guard numbers.count == 2,
              let done = Int(numbers[0]), let total = Int(numbers[1]) else {
            return nil
        }
        var value = ScanProgressLine()
        value.done = done
        value.total = total
        let fields = line[line.index(after: close)...]
            .components(separatedBy: " · ")
            .map { $0.trimmingCharacters(in: .whitespaces) }
        value.path = fields.last ?? ""
        for field in fields {
            if field.hasSuffix("%") { value.percent = field }
            else if field.hasSuffix("/s") { value.rate = field }
            else if field.hasPrefix("remaining ") {
                value.remaining = String(field.dropFirst("remaining ".count))
            } else if field.contains("/") && !field.hasPrefix("/") {
                value.bytes = field
            }
        }
        return value
    }

    func showScanProgress(
        done: Int, total: Int, path: String,
        percentText: String? = nil, bytesText: String? = nil,
        rateText: String? = nil, remainingText: String? = nil,
        discoveryDetail: String? = nil, measuredDetail: String? = nil
    ) {
        if isNormalizedTransaction {
            progress.stopAnimation(nil)
            progress.isIndeterminate = false
            progress.minValue = 0
            progress.maxValue = Double(max(total, 1))
            progress.doubleValue = Double(done)
            let percent = Int((Double(done) / Double(max(total, 1))) * 100)
            let name = URL(fileURLWithPath: path).lastPathComponent
            phaseLabel.stringValue = "Quarantining validated copy"
            progressCountLabel.stringValue = "\(done) of \(total) · \(percent)%"
            statusLabel.stringValue = "Current file: \(name) · Every move remains restorable."
            return
        }
        guard isScanning else { return }
        if let discovery = discoveryDetail {
            progress.startAnimation(nil)
            progress.isIndeterminate = true
            phaseLabel.stringValue = "Finding projects"
            progressCountLabel.stringValue = discovery.components(separatedBy: " · ").first ?? ""
            statusLabel.stringValue = "Nothing can be counted until the folder has been walked. \(discovery)"
            return
        }
        if let measured = measuredDetail {
            progress.startAnimation(nil)
            progress.isIndeterminate = true
            phaseLabel.stringValue = "Ready to read"
            progressCountLabel.stringValue = measured
            statusLabel.stringValue = "Every file is read in full, so this is the work ahead."
            return
        }
        if done == 0 {
            progress.startAnimation(nil)
            progress.isIndeterminate = true
            statusLabel.stringValue = total == 0
                ? "No Cubase, Nuendo or project backup files were found."
                : "Found \(total) project and backup files. Preparing the scan…"
            return
        }
        let name = URL(fileURLWithPath: path).lastPathComponent
        progress.stopAnimation(nil)
        progress.isIndeterminate = false
        progress.minValue = 0
        progress.maxValue = 100
        let fraction = Double(percentText?.dropLast().trimmingCharacters(in: .whitespaces) ?? "")
        progress.doubleValue = fraction ?? (100.0 * Double(done) / Double(max(total, 1)))
        phaseLabel.stringValue = "Reading projects and backups"
        var parts = ["\(done) of \(total) files"]
        if let percentText { parts.append(percentText) }
        if let bytesText { parts.append(bytesText) }
        progressCountLabel.stringValue = parts.joined(separator: " · ")
        var status = "Current file: \(name)"
        if let rateText, let remainingText {
            status = "\(rateText) · about \(remainingText) remaining · \(name)"
        }
        statusLabel.stringValue = status
    }

    func queueScanProgress(_ value: ScanProgressLine) {
        pendingScanProgress = value
        let elapsed = Date().timeIntervalSince(lastProgressRender)
        if elapsed >= 0.15 {
            renderPendingScanProgress()
            return
        }
        guard !progressRefreshScheduled else { return }
        progressRefreshScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + max(0.02, 0.15 - elapsed)) {
            [weak self] in
            self?.progressRefreshScheduled = false
            self?.renderPendingScanProgress()
        }
    }

    func renderPendingScanProgress() {
        guard let value = pendingScanProgress else { return }
        pendingScanProgress = nil
        lastProgressRender = Date()
        showScanProgress(
            done: value.done, total: value.total, path: value.path,
            percentText: value.percent, bytesText: value.bytes,
            rateText: value.rate, remainingText: value.remaining,
            discoveryDetail: value.discovering ? value.path : nil,
            measuredDetail: value.measured
        )
    }

    @objc func startScan() {
        if isScanning {
            scanCancelled = true
            scanButton.title = "Stopping…"
            scanButton.isEnabled = false
            statusLabel.stringValue = "Stopping the scan safely…"
            running?.terminate()
            return
        }
        guard running == nil else { return }
        let selectedPath = rootField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !selectedPath.isEmpty else {
            showError("Choose a project archive folder before scanning.")
            return
        }
        let root = URL(fileURLWithPath: selectedPath).standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            showError("Choose an existing folder first.")
            return
        }
        let report: URL
        do {
            report = try reportURL()
        }
        catch { showError("Could not prepare the private report folder: \(error.localizedDescription)"); return }
        var args = [
            "scan", root.path, "--report", report.path, "--events-jsonl",
        ]
        let backupValues = ["0", "5", "all", "10", "3", "1"]
        args += ["--keep-backups", backupValues[backupPolicy.indexOfSelectedItem]]
        if backupPolicy.indexOfSelectedItem != 0 {
            args.append("--backup-protect-media")
        }
        UserDefaults.standard.set(
            backupPolicy.indexOfSelectedItem, forKey: "BackupPolicyIndex"
        )
        let quarantineDuringScan = quarantineField.stringValue.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let normalizedQuarantine = URL(
            fileURLWithPath: quarantineDuringScan
        ).standardizedFileURL.path
        if !quarantineDuringScan.isEmpty,
           normalizedQuarantine.hasPrefix(root.path + "/") {
            args += [
                "--exclude",
                URL(fileURLWithPath: normalizedQuarantine).lastPathComponent,
            ]
        }
        for item in exclusionsField.stringValue.split(separator: ",")
            .map({ $0.trimmingCharacters(in: .whitespaces) }).filter({ !$0.isEmpty }) {
            args += ["--exclude", item]
        }
        projects = []
        media = []
        backups = []
        projectPage = 0
        mediaPage = 0
        knownProjectPaths.removeAll()
        backupProtectMedia = false
        currentScanKind = "full_safety_scan"
        inventorySummary = [:]
        projectsTable.reloadData()
        mediaTable.reloadData()
        updatePageControls()
        currentReport = nil
        currentReportRoot = nil
        rewriteReady = false
        scanCompleted = false
        selectedProjectPaths.removeAll()
        applyButton.isEnabled = false
        selectAllButton.isEnabled = false
        deselectAllButton.isEnabled = false
        isScanning = true
        scanCancelled = false
        setBusy(true)
        scanButton.title = "Stop Scanning"
        scanButton.isEnabled = true
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        phaseLabel.stringValue = "Discovering projects and backups"
        progressCountLabel.stringValue = "Counting files before detailed reading…"
        statusLabel.stringValue = "Finding Cubase, Nuendo and project backup files…"
        runBackend(arguments: args, eventHandler: { [weak self] project in
            guard let self = self, self.isScanning else { return }
            let path = project["path"] as? String ?? ""
            if !self.knownProjectPaths.contains(path) {
                self.knownProjectPaths.insert(path)
                self.projects.append(project)
                self.scheduleTableRefresh()
            }
        }) { [weak self] code, output in
            guard let self = self else { return }
            let wasCancelled = self.scanCancelled
            self.isScanning = false
            self.scanCancelled = false
            self.progress.stopAnimation(nil)
            self.progress.isIndeterminate = false
            if wasCancelled {
                self.refreshSummary(partial: true)
                self.phaseLabel.stringValue = "Scan stopped"
                self.progressCountLabel.stringValue = "Partial rows are review-only"
                self.statusLabel.stringValue = "Scan stopped. Choose a folder and start again when ready."
            } else if code == 0 {
                self.loadReport(report)
                self.currentReport = report
                self.scanCompleted = true
                self.updateApplyState()
                let hasCandidates = self.projects.contains { self.projectHasCandidates($0) }
                let backupSelection = self.backups.filter {
                    ($0["action"] as? String) == "quarantine"
                }
                let backupBytes = backupSelection.reduce(Int64(0)) { total, backup in
                    total + ((backup["size_bytes"] as? NSNumber)?.int64Value ?? 0)
                }
                if self.readyProjectPaths().isEmpty && !backupSelection.isEmpty {
                    self.statusLabel.stringValue = "Scan complete: \(backupSelection.count) older backups (\(humanSize(backupBytes))) are ready for backup cleanup. Project cleanup has 0 Ready projects."
                } else if hasCandidates && self.readyProjectPaths().isEmpty {
                    self.statusLabel.stringValue = "Scan complete: review files were found, but none are validated for safe Apply. Select a report-only project for details."
                } else {
                    self.statusLabel.stringValue = "Read-only scan complete. Report: \(report.path)"
                }
                self.phaseLabel.stringValue = "Scan complete"
                self.progressCountLabel.stringValue = "100% · detailed report saved"
            } else { self.showError(output.isEmpty ? "Scan failed." : output) }
            self.setBusy(false)
        }
    }

    func loadReport(_ url: URL) {
        do {
            let data = try Data(contentsOf: url)
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let loaded = object["projects"] as? [[String: Any]] else {
                throw NSError(domain: "Report", code: 2)
            }
            projects = loaded
            knownProjectPaths = Set(loaded.compactMap { $0["path"] as? String })
            backups = object["backups"] as? [[String: Any]] ?? []
            backupProtectMedia = object["backup_protect_media"] as? Bool ?? false
            currentScanKind = object["scan_kind"] as? String ?? "full_safety_scan"
            inventorySummary = object["summary"] as? [String: Any] ?? [:]
            currentReportRoot = object["root"] as? String
            selectedProjectPaths.removeAll()
            projectPage = 0
            mediaPage = 0
            projectsTable.reloadData()
            media = []
            mediaTable.reloadData()
            updatePageControls()
            refreshSummary(partial: false)
            backupReviewButton.isEnabled = !backups.isEmpty && running == nil
            backupReviewButton.title = "Review Backup Plan (\(backups.count))…"
            backupApplyButton.isEnabled = backups.contains {
                ($0["action"] as? String) == "quarantine"
            } && running == nil
            let selectedBackups = backups.filter {
                ($0["action"] as? String) == "quarantine"
            }
            backupApplyButton.title = "Quarantine Approved Backups (\(selectedBackups.count))…"
            backupApplyButton.toolTip = selectedBackups.isEmpty
                ? "The current policy keeps all discovered backups"
                : "Move the policy-selected older backups intact into quarantine"
        } catch { showError("Could not read scan report: \(error.localizedDescription)") }
    }

    func projectHasCandidates(_ project: [String: Any]) -> Bool {
        let items = project["media"] as? [[String: Any]] ?? []
        return items.contains { ($0["candidate"] as? Bool) == true }
    }

    func readyProjectPaths() -> Set<String> {
        Set(projects.compactMap { project in
            guard (project["rewrite_supported"] as? Bool) == true,
                  projectHasCandidates(project) else { return nil }
            return project["path"] as? String
        })
    }

    func candidateMediaPaths(for project: [String: Any]) -> Set<String> {
        let items = project["media"] as? [[String: Any]] ?? []
        return Set(items.compactMap { item in
            guard (item["candidate"] as? Bool) == true else { return nil }
            return item["disk_path"] as? String
        })
    }

    func dependencyGroup(for startPath: String) -> Set<String> {
        let ready = projects.filter {
            ($0["rewrite_supported"] as? Bool) == true && projectHasCandidates($0)
        }
        let mediaByProject = Dictionary(uniqueKeysWithValues: ready.compactMap { project -> (String, Set<String>)? in
            guard let path = project["path"] as? String else { return nil }
            return (path, candidateMediaPaths(for: project))
        })
        var group: Set<String> = [startPath]
        var changed = true
        while changed {
            changed = false
            let groupMedia = group.reduce(into: Set<String>()) { result, path in
                result.formUnion(mediaByProject[path] ?? [])
            }
            for (path, mediaPaths) in mediaByProject
                where !group.contains(path) && !groupMedia.isDisjoint(with: mediaPaths) {
                group.insert(path)
                changed = true
            }
        }
        return group
    }

    func refreshSummary(partial: Bool) {
        if currentScanKind == "remote_quick_inventory" {
            let projectCount = (inventorySummary["projects"] as? NSNumber)?.intValue ?? projects.count
            let backupCount = (inventorySummary["backups"] as? NSNumber)?.intValue ?? backups.count
            let mediaCount = (inventorySummary["media_files"] as? NSNumber)?.intValue ?? 0
            let mediaBytes = (inventorySummary["media_bytes"] as? NSNumber)?.int64Value ?? 0
            let pending = (inventorySummary["directories_pending"] as? NSNumber)?.intValue ?? 0
            summaryLabel.stringValue = "Quick Inventory: \(projectCount) projects · \(backupCount) backups · \(mediaCount) media files · \(humanSize(mediaBytes)) media · \(pending) folders pending · Apply locked"
            cleanupSelectionLabel.stringValue = "This older inventory is review-only. Run a new scan before cleanup."
            return
        }
        var uniqueCandidates: [String: Int64] = [:]
        for project in projects {
            let items = project["media"] as? [[String: Any]] ?? []
            for item in items where (item["candidate"] as? Bool) == true {
                guard let path = item["disk_path"] as? String else { continue }
                uniqueCandidates[path] = (item["size_bytes"] as? NSNumber)?.int64Value ?? 0
            }
        }
        let errors = projects.filter {
            ($0["status"] as? String) == "error"
        }.count + backups.filter {
            ($0["status"] as? String) == "error"
        }.count
        let ready = readyProjectPaths().count
        let potentialBytes = uniqueCandidates.values.reduce(0, +)
        let selectedBytes = projects.reduce(into: [String: Int64]()) { result, project in
            guard let path = project["path"] as? String,
                  selectedProjectPaths.contains(path) else { return }
            let items = project["media"] as? [[String: Any]] ?? []
            for item in items where (item["candidate"] as? Bool) == true {
                guard let mediaPath = item["disk_path"] as? String else { continue }
                result[mediaPath] = (item["size_bytes"] as? NSNumber)?.int64Value ?? 0
            }
        }.values.reduce(0, +)
        let backupQuarantine = backups.filter {
            ($0["action"] as? String) == "quarantine"
        }
        let backupBytes = backupQuarantine.reduce(Int64(0)) { total, backup in
            total + ((backup["size_bytes"] as? NSNumber)?.int64Value ?? 0)
        }
        let prefix = partial ? "Scanning" : "Complete"
        summaryLabel.stringValue = "\(prefix): \(projects.count) projects · \(backups.count) backups (\(backupQuarantine.count) to quarantine, \(humanSize(backupBytes))) · \(uniqueCandidates.count) review files · \(humanSize(potentialBytes)) potential · \(ready) Ready · \(errors) errors · \(selectedProjectPaths.count) selected (\(humanSize(selectedBytes)))"
        if partial {
            cleanupSelectionLabel.stringValue = "The scan is still running. Cleanup stays locked until validation finishes."
        } else if ready == 0 && errors > 0 {
            cleanupSelectionLabel.stringValue = "No projects passed the validated cleanup gate. \(errors) project\(errors == 1 ? "" : "s") could not be read; media in those folders is excluded."
        } else if ready == 0 {
            cleanupSelectionLabel.stringValue = "No projects passed the validated cleanup gate. Review Report only rows in Scan & Review."
        } else if selectedProjectPaths.isEmpty {
            cleanupSelectionLabel.stringValue = "\(ready) project\(ready == 1 ? " is" : "s are") Ready. Select the projects to clean in Scan & Review."
        } else {
            let note = errors > 0
                ? " \(errors) unreadable project\(errors == 1 ? "" : "s") elsewhere in the scan; media in those folders is excluded."
                : ""
            cleanupSelectionLabel.stringValue = "Ready to quarantine unused media from \(selectedProjectPaths.count) selected project\(selectedProjectPaths.count == 1 ? "" : "s") — \(humanSize(selectedBytes)).\(note)"
        }
    }

    func updateApplyState() {
        let ready = readyProjectPaths()
        // An unreadable project used to lock Apply for the entire scan. On the
        // studio archive one 0-byte failed save among 1,725 projects made
        // cleanup unavailable everywhere. The backend already excludes media in
        // an unreadable project's folder and validates each selected project,
        // so the selection being a subset of Ready is the gate that matters.
        rewriteReady = scanCompleted && !selectedProjectPaths.isEmpty &&
            selectedProjectPaths.isSubset(of: ready)
        applyButton.isEnabled = rewriteReady && running == nil
        selectAllButton.title = "Select Ready (\(ready.count))"
        selectAllButton.isEnabled = scanCompleted && running == nil && !ready.isEmpty
        selectAllButton.toolTip = ready.isEmpty
            ? "Candidates were found, but no exact project layout is validated for Apply yet"
            : "Select every project validated for Apply"
        deselectAllButton.isEnabled = scanCompleted && running == nil && !selectedProjectPaths.isEmpty
        refreshSummary(partial: !scanCompleted)
        projectsTable.reloadData()
    }

    @objc func selectAllReady() {
        let ready = readyProjectPaths()
        guard !ready.isEmpty else {
            statusLabel.stringValue = "Nothing selected: the candidates are report-only until their exact project layout is validated."
            NSSound.beep()
            return
        }
        selectedProjectPaths = ready
        updateApplyState()
    }

    @objc func deselectAll() {
        selectedProjectPaths.removeAll()
        updateApplyState()
    }

    @objc func toggleProject(_ sender: NSButton) {
        let shown = displayedProjects()
        guard scanCompleted, sender.tag >= 0, sender.tag < shown.count,
              let path = shown[sender.tag]["path"] as? String else { return }
        let group = dependencyGroup(for: path)
        if sender.state == .on {
            selectedProjectPaths.formUnion(group)
        } else {
            selectedProjectPaths.subtract(group)
        }
        updateApplyState()
    }

    func warning(_ title: String, _ text: String, proceed: String) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = text
        alert.addButton(withTitle: proceed)
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func typedConfirmation(_ phrase: String, text: String) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Type \(phrase) to continue"
        alert.informativeText = text
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 330, height: 24))
        field.placeholderString = phrase
        alert.accessoryView = field
        alert.addButton(withTitle: "Confirm")
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn && field.stringValue == phrase
    }

    func chooseSession(prompt: String) -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = prompt
        return panel.runModal() == .OK ? panel.url : nil
    }

    func latestRestorableSession() -> URL? {
        knownSessionOptions(statuses: ["complete"]).first?.url
    }

    func knownSessionOptions(statuses: Set<String>) -> [(url: URL, label: String, date: Date)] {
        let local = UserDefaults.standard.stringArray(
            forKey: "LocalQuarantinePaths"
        ) ?? []
        let controls = Array(Set(rememberedQuarantinePaths() + local)).sorted()
        let entries = controls.flatMap { path -> [URL] in
            let sessions = URL(fileURLWithPath: path)
                .appendingPathComponent("sessions", isDirectory: true)
            return (try? FileManager.default.contentsOfDirectory(
                at: sessions,
                includingPropertiesForKeys: [.contentModificationDateKey],
                options: [.skipsHiddenFiles]
            )) ?? []
        }
        return entries.compactMap { entry -> (url: URL, label: String, date: Date)? in
            let stateURL = entry.appendingPathComponent("state.json")
            guard let data = try? Data(contentsOf: stateURL),
                  let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let status = state["status"] as? String,
                  statuses.contains(status) else { return nil }
            let values = try? entry.resourceValues(
                forKeys: [.contentModificationDateKey]
            )
            let date = values?.contentModificationDate ?? Date.distantPast
            let moves = state["moves"] as? [[String: Any]] ?? []
            let bytes = moves.reduce(Int64(0)) { total, move in
                total + ((move["size_bytes"] as? NSNumber)?.int64Value ?? 0)
            }
            let root = state["root"] as? String ?? "Unknown archive"
            let archive = URL(fileURLWithPath: root).lastPathComponent
            let changes = state["project_changes"] as? [[String: Any]] ?? []
            let archives = state["archive_projects"] as? [[String: Any]] ?? []
            let normalized = state["surviving_project"] as? [String: Any]
            let cutoff = Date().addingTimeInterval(-Double(3 * 365 * 24 * 60 * 60))
            let normalizedRecent: Bool = {
                guard let normalized = normalized else { return false }
                guard let stamp = (normalized["modified_at"] as? NSNumber)?.doubleValue
                else { return true }
                return Date(timeIntervalSince1970: stamp) > cutoff
            }()
            let recentProject = changes.contains { change in
                guard let stamp = (change["original_mtime"] as? NSNumber)?.doubleValue
                else { return true }
                return Date(timeIntervalSince1970: stamp) > cutoff
            } || archives.contains { archive in
                guard let stamp = (archive["modified_at"] as? NSNumber)?.doubleValue
                else { return true }
                return Date(timeIntervalSince1970: stamp) > cutoff
            } || normalizedRecent
            let mode = state["mode"] as? String ?? ""
            let policy = mode == "daw-normalized-pilot"
                ? "Restore only pilot"
                : (recentProject ? "30-day recovery" : "Delete now available")
            let formatter = DateFormatter()
            formatter.dateStyle = .medium
            formatter.timeStyle = .short
            let label = "\(archive) · \(formatter.string(from: date)) · \(moves.count) files · \(humanSize(bytes)) · \(policy)"
            return (entry, label, date)
        }.sorted { $0.date > $1.date }
    }

    func purgeableSessionOptions(
        statuses: Set<String>
    ) -> [(url: URL, label: String, date: Date)] {
        knownSessionOptions(statuses: statuses).filter { option in
            let stateURL = option.url.appendingPathComponent("state.json")
            guard let data = try? Data(contentsOf: stateURL),
                  let state = try? JSONSerialization.jsonObject(
                    with: data
                  ) as? [String: Any] else { return false }
            return (state["mode"] as? String) != "daw-normalized-pilot"
        }
    }

    func chooseKnownSession(
        title: String, statuses: Set<String>, purgeableOnly: Bool = false
    ) -> URL? {
        let options = purgeableOnly
            ? purgeableSessionOptions(statuses: statuses)
            : knownSessionOptions(statuses: statuses)
        guard !options.isEmpty else { return nil }
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = "Choose the exact cleanup session. Offline quarantine locations remain remembered but are not shown until their server volume is connected."
        let picker = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 560, height: 28))
        picker.addItems(withTitles: options.map(\.label))
        alert.accessoryView = picker
        alert.addButton(withTitle: "Choose Session")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        return options[picker.indexOfSelectedItem].url
    }

    func sessionHasStatus(_ url: URL, _ status: String) -> Bool {
        let stateURL = url.appendingPathComponent("state.json")
        guard let data = try? Data(contentsOf: stateURL),
              let state = try? JSONSerialization.jsonObject(
                with: data
              ) as? [String: Any] else { return false }
        return (state["status"] as? String) == status
    }

    func sessionURL(from output: String) -> URL? {
        for line in output.split(separator: "\n").reversed() {
            for prefix in [
                "NORMALIZED BATCH SESSION: ", "NORMALIZED PILOT SESSION: ", "PILOT SESSION: ",
                "BACKUP SESSION: ",
            ] {
                if line.hasPrefix(prefix) {
                    return URL(fileURLWithPath: String(line.dropFirst(prefix.count)))
                }
            }
        }
        return nil
    }

    @objc func startBackupApply() {
        guard let report = currentReport, scanCompleted else {
            showError("Run a fresh scan before applying the backup policy.")
            return
        }
        let selected = backups.filter {
            ($0["action"] as? String) == "quarantine"
        }
        guard !selected.isEmpty else {
            showInfo("No older backups selected", "The current backup policy keeps every classified backup.")
            return
        }
        let rootPath = rootField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let quarantinePath = quarantineField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rootPath.isEmpty, !quarantinePath.isEmpty else {
            showError("Choose both the projects folder and shared quarantine location.")
            return
        }
        guard let scannedRoot = currentReportRoot,
              URL(fileURLWithPath: scannedRoot).standardizedFileURL.path ==
                URL(fileURLWithPath: rootPath).standardizedFileURL.path else {
            showError("The projects folder changed after the scan. Run a fresh scan.")
            return
        }
        rememberQuarantinePath(quarantinePath)
        let bytes = selected.reduce(Int64(0)) { total, backup in
            total + ((backup["size_bytes"] as? NSNumber)?.int64Value ?? 0)
        }
        // A backup beside a project we could not read may be that project's
        // only readable copy, so the scanner withholds every backup in such a
        // folder. Say so here: the operator should see the evidence that was
        // used to exclude them, not just the count that is moving.
        let unreadable = projects.filter { ($0["status"] as? String) == "error" }.count
        let withheld = backups.filter {
            ($0["action"] as? String) == "keep"
                && (($0["reason"] as? String) ?? "").contains("could not be read")
        }.count
        var evidence = ""
        if unreadable > 0 {
            evidence = "\n\n\(unreadable) project\(unreadable == 1 ? "" : "s") in this scan could not be read. \(withheld) backup\(withheld == 1 ? "" : "s") in those folders \(withheld == 1 ? "is" : "are") excluded from this move."
        }
        let explanation = "Move \(selected.count) older project backups (\(humanSize(bytes))) intact into recoverable quarantine? Backup files are not rewritten. Ambiguous and unreadable backups remain untouched.\(evidence)\n\nQuarantine location:\n\(quarantinePath)"
        guard warning(
            "Apply the selected backup policy?", explanation,
            proceed: "Move Backups to Quarantine"
        ) else { return }
        guard typedConfirmation(
            "APPLY BACKUP POLICY",
            text: "Type the phrase exactly. Restore can return every moved backup to its original location."
        ) else { return }
        setBusy(true)
        statusLabel.stringValue = "Revalidating and moving older project backups to quarantine…"
        runBackend(arguments: [
            "apply-backup-policy", report.path,
            "--quarantine-root", quarantinePath,
            "--confirm", "APPLY BACKUP POLICY",
        ]) { [weak self] code, output in
            guard let self = self else { return }
            self.setBusy(false)
            if code == 0 {
                self.currentSession = self.sessionURL(from: output)
                self.currentReport = nil
                self.currentReportRoot = nil
                self.scanCompleted = false
                self.selectedProjectPaths.removeAll()
                self.backupApplyButton.isEnabled = false
                self.applyButton.isEnabled = false
                self.statusLabel.stringValue = "Backup policy applied. Run a fresh scan or use Restore to return the backups."
                self.showInfo(
                    "Older backups moved to quarantine",
                    "No project or backup content was rewritten. Run a fresh scan before any project cleanup.\n\n\(output)"
                )
            } else {
                self.showError(output.isEmpty ? "Backup cleanup failed safely." : output)
            }
        }
    }

    @objc func startApply() {
        guard let report = currentReport, rewriteReady else {
            showError("Run a fresh scan. Apply is available only when every candidate project has a validated exact rewrite profile.")
            return
        }
        let rootPath = rootField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rootPath.isEmpty else { showError("Choose a controlled-copy folder first."); return }
        let quarantinePath = quarantineField.stringValue.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard !quarantinePath.isEmpty else {
            showError("Choose the shared quarantine location first.")
            return
        }
        rememberQuarantinePath(quarantinePath)
        let selectedRoot = URL(fileURLWithPath: rootPath).standardizedFileURL.path
        guard let scannedRoot = currentReportRoot,
              URL(fileURLWithPath: scannedRoot).standardizedFileURL.path == selectedRoot else {
            showError("The selected folder changed after the scan. Run a fresh read-only scan before Apply.")
            return
        }
        let selected = selectedProjectPaths.sorted()
        guard !selected.isEmpty else { showError("Select at least one Ready project."); return }
        let explanation = "This pilot is only for a disposable copy, never the only server archive. The app will revalidate every project, create verified project backups, atomically rewrite validated Pool references, and move the matching media into this remembered quarantine location:\n\n\(quarantinePath)\n\nUnknown formats, shared active media, changed files and incomplete mappings stop the operation."
        guard warning("Apply validated cleanup to this controlled copy?", explanation, proceed: "This is a copy — continue") else { return }
        guard typedConfirmation("CONTROLLED COPY APPLY", text: "Type the phrase exactly. After Apply, open and test the projects without resaving. Use Restore to return both project files and media to their exact original state.") else { return }
        setBusy(true)
        statusLabel.stringValue = "Marking the disposable copy and revalidating the fresh scan…"
        runBackend(arguments: [
            "prepare-controlled-copy", rootPath,
            "--confirm", "THIS IS A DISPOSABLE COPY",
        ]) { [weak self] markerCode, markerOutput in
            guard let self = self else { return }
            if markerCode != 0 {
                self.setBusy(false)
                self.showError(markerOutput.isEmpty ? "Could not validate the controlled-copy folder." : markerOutput)
                return
            }
            self.statusLabel.stringValue = "Backing up projects, rewriting validated references and moving media to quarantine…"
            var applyArguments = [
                "apply-pilot", report.path,
                "--confirm", "CONTROLLED COPY APPLY",
                "--quarantine-root", quarantinePath,
            ]
            for projectPath in selected {
                applyArguments += ["--project", projectPath]
            }
            self.runBackend(arguments: applyArguments) { [weak self] code, output in
                guard let self = self else { return }
                self.setBusy(false)
                if code == 0 {
                    self.currentSession = self.sessionURL(from: output)
                    self.currentReport = nil
                    self.currentReportRoot = nil
                    self.rewriteReady = false
                    self.scanCompleted = false
                    self.selectedProjectPaths.removeAll()
                    self.applyButton.isEnabled = false
                    self.selectAllButton.isEnabled = false
                    self.deselectAllButton.isEnabled = false
                    self.restoreButton.isEnabled = true
                    self.statusLabel.stringValue = "Controlled-copy Apply complete. Test projects without resaving, then Restore."
                    self.showInfo("Validated cleanup applied", "Project references and matching media were updated together. The removed media is recoverable in quarantine. Open and test the projects without saving them, then choose Restore Last Cleanup.\n\n\(output)")
                } else {
                    self.showError(output.isEmpty ? "Apply failed safely; any partial work was rolled back." : output)
                }
            }
        }
    }

    @objc func startRestore() {
        let known = knownSessionOptions(statuses: ["complete"])
        let session: URL?
        if let current = currentSession, sessionHasStatus(current, "complete") {
            session = current
        } else {
            session = known.isEmpty
                ? chooseSession(prompt: "Restore")
                : chooseKnownSession(
                    title: "Choose a cleanup to restore", statuses: ["complete"]
                )
        }
        guard let session = session else { return }
        guard warning("Restore this cleanup?", "The exact original project files and quarantined media will be atomically returned to their original paths. Restore stops if a project was resaved, an original path is occupied, or any hash validation fails.", proceed: "Restore") else { return }
        setBusy(true)
        runBackend(arguments: ["restore", session.path]) { [weak self] code, output in
            guard let self = self else { return }
            self.setBusy(false)
            if code == 0 {
                self.currentSession = nil
                self.currentReport = nil
                self.currentReportRoot = nil
                self.rewriteReady = false
                self.scanCompleted = false
                self.selectedProjectPaths.removeAll()
                self.applyButton.isEnabled = false
                self.selectAllButton.isEnabled = false
                self.deselectAllButton.isEnabled = false
                self.statusLabel.stringValue = "Restore complete. Run a fresh read-only scan before another Apply."
                self.showInfo("Restore complete", output)
            }
            else { self.showError(output.isEmpty ? "Restore failed safely." : output) }
        }
    }

    @objc func startPurge() {
        guard running == nil else { return }
        let known = purgeableSessionOptions(statuses: ["complete", "purging"])
        let session = known.isEmpty
            ? chooseSession(prompt: "Choose Cleanup Session")
            : chooseKnownSession(
                title: "Choose quarantined files to delete",
                statuses: ["complete", "purging"], purgeableOnly: true
            )
        guard let session = session else { return }
        let message = "This permanently deletes the audio and/or old project backups held by the selected quarantine session. Projects originally modified within the last three years keep a mandatory 30-day recovery window; older projects may be deleted immediately. Verified cleanup records remain, but deleted files cannot be restored."
        guard warning("Permanently delete quarantined audio?", message, proceed: "Authenticate…") else { return }
        authenticateOwner(reason: "Authorize permanent deletion of quarantined studio audio") { [weak self] authenticated in
            guard let self = self, authenticated else { return }
            guard self.typedConfirmation(
                "DELETE QUARANTINE PERMANENTLY",
                text: "This cannot be undone. Type the phrase exactly to permanently delete the quarantined files."
            ) else { return }
            self.setBusy(true)
            self.statusLabel.stringValue = "Revalidating the project, backup and quarantined media before permanent deletion…"
            self.runBackend(arguments: [
                "purge", session.path,
                "--confirm", "DELETE QUARANTINE PERMANENTLY",
            ]) { [weak self] code, output in
                guard let self = self else { return }
                self.setBusy(false)
                if code == 0 {
                    self.currentSession = nil
                    self.statusLabel.stringValue = "The selected quarantined files were permanently deleted; audit records were retained."
                    self.showInfo("Permanent deletion complete", output)
                } else {
                    self.showError(output.isEmpty ? "Permanent deletion was refused safely." : output)
                }
            }
        }
    }

    func authenticateOwner(reason: String, completion: @escaping (Bool) -> Void) {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            showError(error?.localizedDescription ?? "macOS authentication is unavailable.")
            completion(false)
            return
        }
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) {
            success, authenticationError in
            DispatchQueue.main.async { [weak self] in
                if !success, let authenticationError = authenticationError {
                    self?.showError(authenticationError.localizedDescription)
                }
                completion(success)
            }
        }
    }

    @objc func reviewBackups() {
        guard !backups.isEmpty else {
            showInfo("No project backups found", "The completed scan did not find any readable .bak files or project files inside backup folders.")
            return
        }
        let ordered = backups.sorted {
            ($0["path"] as? String ?? "").localizedCaseInsensitiveCompare(
                $1["path"] as? String ?? ""
            ) == .orderedAscending
        }
        let lines = ordered.map { backup -> String in
            let action = (backup["action"] as? String ?? "review").uppercased()
            let path = backup["path"] as? String ?? "Unknown backup"
            let size = humanSize((backup["size_bytes"] as? NSNumber)?.int64Value ?? 0)
            let reason = backup["reason"] as? String ?? ""
            return "\(action) · \(size)\n\(path)\n\(reason)"
        }
        let textView = NSTextView(frame: NSRect(x: 0, y: 0, width: 720, height: 390))
        textView.string = lines.joined(separator: "\n\n")
        textView.isEditable = false
        textView.isSelectable = true
        textView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        let scroll = NSScrollView(frame: textView.frame)
        scroll.documentView = textView
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        let alert = NSAlert()
        alert.messageText = "Project backup review"
        alert.informativeText = backupProtectMedia
            ? "Working Project mode reads retained backups and protects their referenced media. Backups marked QUARANTINE move intact into the recoverable cleanup session; they are never rewritten. Ambiguous or unreadable backups are always kept."
            : "Archive Cleanup mode does not parse backup contents or use them to protect media. Unambiguously classified backups are marked QUARANTINE and move intact into the recoverable cleanup session. Ambiguous backups are always kept."
        alert.accessoryView = scroll
        alert.addButton(withTitle: "Done")
        alert.runModal()
    }

    @objc func showSupport() {
        if let panel = aboutPanel {
            panel.makeKeyAndOrderFront(nil)
            return
        }
        let visible = window.screen?.visibleFrame ?? NSScreen.main?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 800, height: 600)
        let panelWidth = min(CGFloat(620), max(CGFloat(380), visible.width - 80))
        let panelHeight = min(CGFloat(520), max(CGFloat(340), visible.height - 100))
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: panelWidth, height: panelHeight),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        panel.title = "About DAW Project Cleaner"
        panel.minSize = NSSize(width: min(380, panelWidth), height: min(340, panelHeight))
        panel.maxSize = NSSize(
            width: min(720, visible.width - 40),
            height: min(640, visible.height - 40)
        )
        panel.isReleasedWhenClosed = false

        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.translatesAutoresizingMaskIntoConstraints = false
        icon.widthAnchor.constraint(equalToConstant: 58).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 58).isActive = true
        let name = NSTextField(labelWithString: "DAW Project Cleaner 0.11.0")
        name.font = NSFont.systemFont(ofSize: 20, weight: .bold)
        let purpose = multilineLabel(
            "Safely reduce oversized Cubase and Nuendo archives without leaving broken media references.",
            color: .labelColor
        )
        let titleStack = NSStackView(views: [name, purpose])
        titleStack.orientation = .vertical
        titleStack.alignment = .leading
        titleStack.spacing = 3
        var headerViews: [NSView] = [icon, titleStack, NSView()]
        if let path = Bundle.main.path(forResource: "support-qr", ofType: "png"),
           let image = NSImage(contentsOfFile: path) {
            let qr = NSImageView(image: image)
            qr.imageScaling = .scaleProportionallyUpOrDown
            qr.translatesAutoresizingMaskIntoConstraints = false
            qr.widthAnchor.constraint(equalToConstant: 72).isActive = true
            qr.heightAnchor.constraint(equalToConstant: 72).isActive = true
            qr.toolTip = "buymeacoffee.com/franckreisner"
            headerViews.append(qr)
        }
        let header = NSStackView(views: headerViews)
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 12

        let body = """
        What it does
        DAW Project Cleaner reads project folders, identifies media that can be removed with strong project evidence, and keeps project references and disk files consistent.

        How it protects your work
        Uncertain, shared, missing, changed or unsupported files are left untouched. Cleanup moves validated files to recoverable quarantine before permanent deletion is allowed. Restore verifies the recorded paths and file hashes.

        Where it works
        Choose any project folder available on your Mac, including a local drive or a mounted server volume. Processing stays on this computer.

        Privacy
        No telemetry and no project data is uploaded.

        Independent software
        Created in good faith by Franck Reisner / Studio89. Not affiliated with or endorsed by Steinberg. Cubase and Nuendo are trademarks of their respective owner.

        Support
        If this utility helps you, support development at buymeacoffee.com/franckreisner.
        """
        let textView = NSTextView()
        textView.string = body
        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = false
        textView.font = NSFont.systemFont(ofSize: 13)
        textView.textContainerInset = NSSize(width: 4, height: 8)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true
        let scroll = NSScrollView()
        scroll.documentView = textView
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.borderType = .bezelBorder
        scroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        scroll.setContentCompressionResistancePriority(.defaultLow, for: .vertical)

        let support = button("Support Development", #selector(openSupportURL))
        let close = button("Close", #selector(closeAbout))
        close.keyEquivalent = "\r"
        let actions = NSStackView(views: [support, NSView(), close])
        actions.orientation = .horizontal
        actions.spacing = 8
        let stack = NSStackView(views: [header, scroll, actions])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = panel.contentView!
        content.addSubview(stack)
        for view in [header, scroll, actions] {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 18),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -18),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 16),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -14),
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 160),
        ])
        aboutPanel = panel
        window.beginSheet(panel)
    }

    @objc func closeAbout() {
        guard let panel = aboutPanel else { return }
        if window.attachedSheet === panel { window.endSheet(panel) }
        panel.orderOut(nil)
        aboutPanel = nil
    }

    @objc func openSupportURL() {
        if let url = URL(string: "https://buymeacoffee.com/franckreisner") {
            NSWorkspace.shared.open(url)
        }
    }

    func numberOfRows(in tableView: NSTableView) -> Int {
        tableView === projectsTable ? displayedProjects().count : displayedMedia().count
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard let column = tableColumn else { return nil }
        let id = column.identifier.rawValue
        if tableView === projectsTable && id == "select" {
            let project = displayedProjects()[row]
            let path = project["path"] as? String ?? ""
            let checkbox = NSButton(
                checkboxWithTitle: "", target: self, action: #selector(toggleProject(_:))
            )
            checkbox.tag = row
            checkbox.state = selectedProjectPaths.contains(path) ? .on : .off
            checkbox.isEnabled = scanCompleted &&
                (project["rewrite_supported"] as? Bool) == true &&
                projectHasCandidates(project)
            checkbox.toolTip = checkbox.isEnabled
                ? "Select this project and every Ready project sharing its candidate media"
                : "Only Ready projects can be selected after the complete scan"
            return checkbox
        }
        let cell = NSTextField(labelWithString: "")
        cell.lineBreakMode = .byTruncatingMiddle
        if tableView === projectsTable {
            let project = displayedProjects()[row]
            let items = project["media"] as? [[String: Any]] ?? []
            let candidates = items.filter { ($0["candidate"] as? Bool) == true }
            switch id {
            case "project": cell.stringValue = URL(fileURLWithPath: project["path"] as? String ?? "").lastPathComponent
            case "status": cell.stringValue = project["status"] as? String ?? ""
            case "profile":
                let product = project["product"] as? String ?? "?"
                let version = project["version"] as? String ?? "?"
                cell.stringValue = compactDAWFormat(product: product, version: version)
                cell.toolTip = product == "?" ? nil : "\(product) \(version)"
            case "rewrite":
                let reason = project["rewrite_reason"] as? String ?? ""
                cell.stringValue = (project["rewrite_supported"] as? Bool) == true
                    ? "Ready"
                    : (reason.contains("blocked by retained backups")
                        ? "Backup protected" : "Report only")
                cell.toolTip = project["rewrite_reason"] as? String ?? ""
            case "candidates": cell.stringValue = String(candidates.count)
            case "space": cell.stringValue = humanSize(
                (project["potential_reclaimable_bytes"] as? NSNumber)?.int64Value ?? 0
            )
            default: break
            }
        } else {
            let item = displayedMedia()[row]
            switch id {
            case "name": cell.stringValue = item["name"] as? String ?? ""
            case "class": cell.stringValue = item["classification"] as? String ?? ""
            case "action": cell.stringValue = (item["candidate"] as? Bool) == true ? "Quarantine" : "Keep"
            case "size": cell.stringValue = humanSize((item["size_bytes"] as? NSNumber)?.int64Value ?? 0)
            case "reason": cell.stringValue = item["reason"] as? String ?? ""
            default: break
            }
        }
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        guard notification.object as AnyObject? === projectsTable else { return }
        let row = projectsTable.selectedRow
        let shown = displayedProjects()
        media = row >= 0 && row < shown.count
            ? (shown[row]["media"] as? [[String: Any]] ?? []) : []
        mediaPage = 0
        mediaTable.reloadData()
        updatePageControls()
        if row >= 0 && row < shown.count {
            let project = shown[row]
            let name = URL(fileURLWithPath: project["path"] as? String ?? "").lastPathComponent
            let state = (project["rewrite_supported"] as? Bool) == true ? "Ready" : "Report only"
            let reason = project["rewrite_reason"] as? String ?? ""
            statusLabel.stringValue = "\(name) — \(state): \(reason)"
        }
    }

    func showError(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "DAW Project Cleaner"
        alert.informativeText = message
        alert.runModal()
    }

    func showInfo(_ title: String, _ message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
