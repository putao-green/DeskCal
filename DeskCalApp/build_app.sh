#!/bin/bash
set -e
cd "$(dirname "$0")"
APP="DeskCal.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
# 把界面打进 App，开箱即用，无需后端
cp ../index.html "$APP/Contents/Resources/index.html"
swiftc -O -parse-as-library App.swift -o "$APP/Contents/MacOS/App"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>App</string>
  <key>CFBundleIdentifier</key><string>com.workbuddy.deskcal</string>
  <key>CFBundleName</key><string>DeskCal</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
# 关于 NSAppTransportSecurity：
# 默认形态是纯本地，界面从 App 包内以 file:// 加载，数据走 localStorage，
# 不产生任何网络请求，所以这里不放开的传输安全策略。
# 只有当你把 LOAD_URL 改成 http:// 开头的服务器地址做跨机器同步时，
# 才需要在这段 plist 里补上下面两行；能用 https 就别用 http。
#   <key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>

# 清掉 Finder 与同步盘留下的扩展属性。否则 codesign 会报
# "resource fork, Finder information, or similar detritus not allowed" 并以非零退出，
# set -e 会直接中断，产物是个没签名的残件。工程放在桌面或 iCloud 同步目录下必然触发。
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"
codesign -v "$APP"
echo "build ok -> $APP"
echo "初次打开若被 Gatekeeper 拦下，执行：xattr -d com.apple.quarantine $APP"
