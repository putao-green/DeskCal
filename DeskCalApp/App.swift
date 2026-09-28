import Cocoa
import WebKit

// DeskCal 桌面待办日历 —— 原生外壳（可独立运行版）
// 默认加载打进 App 的 index.html，开箱即用，无需任何后端。
// 想接自己的同步服务：把 LOAD_URL 改成 "http://你的服务器/deskcal/?widget=1" 即可。
// 桌面层：CGWindowLevelForKey(.desktopIconWindow)+1 （壁纸之上、普通窗口之下）
let BUILD_TAG = "deskcal-20260914"
let LOAD_URL: String = {
    if let u = Bundle.main.url(forResource: "index", withExtension: "html") {
        return u.absoluteString + "?widget=1"
    }
    return "http://127.0.0.1:8787/?widget=1"
}()

func trace(_ m: String) {
    let line = "\(Date()) [DeskCal] \(m)\n"
    if let h = FileHandle(forWritingAtPath: "/tmp/deskcal_app_trace.log") {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile()
    } else {
        try? line.data(using: .utf8)!.write(to: URL(fileURLWithPath: "/tmp/deskcal_app_trace.log"))
    }
}

@main
struct AppMain {
    static func main() {
        trace("launch start")
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}

final class Panel: NSPanel {
    var dragLocked = false
    private var dragStart: NSPoint?
    private var dragStartOrigin: NSPoint = .zero
    private var isDragging = false
    private let dragThreshold: CGFloat = 4

    override var canBecomeKey: Bool { true }

    override func sendEvent(_ event: NSEvent) {
        guard event.window === self else { super.sendEvent(event); return }
        switch event.type {
        case .leftMouseDown:
            dragStart = event.locationInWindow
            dragStartOrigin = self.frame.origin
            isDragging = false
            super.sendEvent(event)
        case .leftMouseDragged:
            guard !dragLocked, let start = dragStart else { super.sendEvent(event); return }
            let cur = event.locationInWindow
            let dx = cur.x - start.x, dy = cur.y - start.y
            if !isDragging {
                if hypot(dx, dy) < dragThreshold { super.sendEvent(event); return }
                isDragging = true
            }
            self.setFrameOrigin(NSPoint(x: dragStartOrigin.x + dx, y: dragStartOrigin.y + dy))
        case .leftMouseUp:
            super.sendEvent(event)
            dragStart = nil; isDragging = false
        default:
            super.sendEvent(event)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var panel: Panel!
    var webView: WKWebView!
    var statusItem: NSStatusItem!
    let size = NSSize(width: 460, height: 520)

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        trace("didFinishLaunching")
        let origin = NSPoint(x: NSScreen.main!.visibleFrame.maxX - size.width - 40,
                             y: NSScreen.main!.visibleFrame.minY + 40)

        panel = Panel(contentRect: NSRect(origin: origin, size: size),
                      styleMask: [.borderless, .nonactivatingPanel, .resizable],
                      backing: .buffered, defer: false)
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.minSize = NSSize(width: 300, height: 340)
        panel.maxSize = NSSize(width: 1200, height: 1100)
        panel.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.becomesKeyOnlyIfNeeded = false
        panel.isMovableByWindowBackground = false

        let container = NSView(frame: NSRect(origin: .zero, size: size))
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor.clear.cgColor
        container.autoresizingMask = [.width, .height]

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.preferences = WKPreferences()
        config.userContentController.add(self, name: "deskcal")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        webView.navigationDelegate = self
        webView.frame = container.bounds
        webView.autoresizingMask = [.width, .height]
        container.addSubview(webView)
        panel.contentView = container

        buildStatusItem()
        loadPage()
        panel.orderFront(nil)
        trace("done init")
    }

    func loadPage() {
        var comp = URLComponents(string: LOAD_URL)!
        let ts = URLQueryItem(name: "_ts", value: String(Int(Date().timeIntervalSince1970)))
        comp.queryItems = (comp.queryItems ?? []) + [ts]
        let req = URLRequest(url: comp.url!, cachePolicy: .reloadIgnoringLocalCacheData)
        webView.load(req)
        trace("load \(comp.url!.absoluteString)")
    }

    func webView(_ webView: WKWebView, didFinish nav: WKNavigation!) {
        webView.evaluateJavaScript("try{var e=document.getElementById('build-tag');if(e)e.textContent='\(BUILD_TAG)';}catch(_){}")
        trace("nav OK -> \(webView.url?.absoluteString ?? "?")")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError error: Error) {
        trace("nav FAIL \(error.localizedDescription)")
        webView.loadHTMLString(errorHTML, baseURL: nil)
    }
    func webView(_ webView: WKWebView, didFail nav: WKNavigation!, withError error: Error) {
        trace("nav FAIL2 \(error.localizedDescription)")
        webView.loadHTMLString(errorHTML, baseURL: nil)
    }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        if m.body as? String == "reload" { loadPage() }
    }

    func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let btn = statusItem.button { btn.title = "📅" }
        let menu = NSMenu()
        menu.addItem(withTitle: "刷新组件", action: #selector(reload), keyEquivalent: "r")
        menu.addItem(withTitle: "重置位置", action: #selector(resetPos), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出", action: #selector(quit), keyEquivalent: "q")
        statusItem.menu = menu
    }

    @objc func reload() { loadPage() }
    @objc func resetPos() {
        guard let s = NSScreen.main else { return }
        panel.setFrameOrigin(NSPoint(x: s.visibleFrame.maxX - size.width - 40,
                                     y: s.visibleFrame.minY + 40))
    }
    @objc func quit() { NSApplication.shared.terminate(nil) }

    var errorHTML: String {
        return """
        <!doctype html><html><head><meta charset=\"utf-8\"><style>
        body{margin:0;height:100vh;background:#15171c;color:#cfd3da;font:14px/1.6 -apple-system,sans-serif;
        display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;padding:24px}
        .b{background:#2b6cff;color:#fff;border:none;padding:10px 20px;border-radius:10px;font-size:14px;cursor:pointer}
        </style></head><body>
        <div>组件载入失败</div>
        <div style=\"opacity:.7;font-size:12px\">请重新打开 App，或检查 index.html 是否在 App 包内</div>
        <button class=\"b\" onclick=\"window.webkit.messageHandlers.deskcal.postMessage('reload')\">重试</button>
        </body></html>
        """
    }
}
