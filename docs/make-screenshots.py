#!/usr/bin/env python3
"""生成 README 用的界面截图。

做法：把 index.html 拷一份到临时目录，追一段脚本自动点击目标按钮，
再用无头浏览器截图。不改动仓库里的 index.html。

浏览器按下面的顺序探测，也可以用环境变量指定：
    export CHROME="/path/to/chrome"

输出为 1600px 宽的 JPEG。这些截图有大面积渐变，同样尺寸下 JPEG 比 PNG
小一个数量级，仓库里四张图合计约 800KB。
"""
import os
import shutil
import subprocess
import sys
import tempfile

CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
OUT = os.path.join(ROOT, "docs")
TARGET_WIDTH = 1600
JPEG_QUALITY = "88"

# 名称 -> 自动点击的表达式，None 表示保持默认视图
VARIANTS = {
    "screenshot-month": None,
    "screenshot-week": "document.querySelector('[data-v=\"week\"]').click()",
    "screenshot-settings": "document.getElementById('gear').click()",
    "screenshot-todos": "document.getElementById('bak').click()",
}


def find_browser():
    env = os.environ.get("CHROME")
    if env:
        return env
    for path in CANDIDATES:
        if os.path.exists(path):
            return path
    sys.exit("找不到无头浏览器。装一个 Chrome，或用 CHROME 环境变量指定路径。")


def build_variant(js):
    if not js:
        return SRC
    with open(SRC, encoding="utf-8") as f:
        html = f.read()
    inject = (
        "<script>window.addEventListener('load',function(){"
        "setTimeout(function(){try{%s}catch(e){console.error(e)}},120);"
        "});</script>" % js
    )
    idx = html.rfind("</body>")
    html = html + inject if idx == -1 else html[:idx] + inject + html[idx:]
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def capture(browser, src, target):
    subprocess.run(
        [
            browser, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--hide-scrollbars", "--force-device-scale-factor=2",
            "--virtual-time-budget=6000", "--window-size=1400,1180",
            "--screenshot=" + target, "file://" + src,
        ],
        check=True,
        capture_output=True,
    )


def to_jpeg(png):
    """缩到 TARGET_WIDTH 并转成 JPEG，返回最终路径。"""
    jpg = os.path.splitext(png)[0] + ".jpg"
    if shutil.which("sips"):
        subprocess.run(
            ["sips", "-Z", str(TARGET_WIDTH), "-s", "format", "jpeg",
             "-s", "formatOptions", JPEG_QUALITY, png, "--out", jpg],
            check=True, capture_output=True,
        )
        os.unlink(png)
        return jpg
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print("  提示：装 Pillow 或 sips 才能压缩，本次保留 PNG")
        return png
    with Image.open(png) as im:
        ratio = TARGET_WIDTH / im.width
        if ratio < 1:
            im = im.resize((TARGET_WIDTH, round(im.height * ratio)), Image.LANCZOS)
        im.convert("RGB").save(jpg, "JPEG", quality=int(JPEG_QUALITY), optimize=True)
    os.unlink(png)
    return jpg


def main():
    browser = find_browser()
    os.makedirs(OUT, exist_ok=True)
    for name, js in VARIANTS.items():
        tmp = build_variant(js)
        png = os.path.join(OUT, name + ".png")
        try:
            capture(browser, tmp, png)
            final = to_jpeg(png)
            print("ok", os.path.relpath(final, ROOT), os.path.getsize(final) // 1024, "KB")
        finally:
            if tmp != SRC:
                os.unlink(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
