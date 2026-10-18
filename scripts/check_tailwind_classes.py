"""扫描 index.html 里所有 Tailwind 工具类，逐个核对是否真的存在于预编译 CSS。

为什么需要：vendor/tailwind/tailwind.min.css 是**预编译产物**（不是运行时 JIT），
页面里用到但没被编译进去的 class 会**静默失效** —— 不报错、不警告、样式就是不生效。
实测踩过两次：`ml-1.5`（命中率紧贴数字）、`mr-0.5`（图标与文字无间距）。

项目文档提到过有个 check_tailwind_classes.py 专门查这个，但它**没随源码发布**，
所以这里补一个最小可用的替代。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(r"G:\ZCode\workbuddy2api-xiaofan6ya")
HTML = REPO / "admin/static/index.html"
CSS = REPO / "admin/static/vendor/tailwind/tailwind.min.css"

#: 只检查「看起来像 Tailwind 工具类」的名字，避免把项目自定义类（fs-11-5 / tbl / acc-table）算进来
TAILWIND_PREFIXES = (
    "p-", "px-", "py-", "pt-", "pb-", "pl-", "pr-",
    "m-", "mx-", "my-", "mt-", "mb-", "ml-", "mr-",
    "w-", "h-", "min-w-", "min-h-", "max-w-", "max-h-",
    "text-", "font-", "leading-", "tracking-",
    "bg-", "border", "rounded", "shadow",
    "flex", "grid", "gap-", "items-", "justify-", "content-", "self-",
    "col-", "row-", "order-", "space-",
    "absolute", "relative", "fixed", "sticky", "static",
    "top-", "right-", "bottom-", "left-", "inset-", "z-",
    "overflow-", "whitespace-", "break-", "truncate",
    "opacity-", "transition", "duration-", "ease-", "delay-",
    "cursor-", "select-", "pointer-events-",
    "tnum",  # 项目自定义，但常被当成工具类；存在与否也要查
)

#: 变体前缀：md: / lg: / sm: / xl: / 2xl: / hover: / focus: / dark: 等
VARIANT_RE = re.compile(r"^(?:[a-z0-9]+:)+")


def load_css_classes() -> set[str]:
    """从压缩 CSS 里提取所有类名。

    压缩产物的转义规则（这是本函数最容易写错的地方）：
      `.md\\:grid-cols-4{...}`   —— 变体里的冒号被转义成 `\\:`
      `.py-1\\.5{...}`           —— 小数值里的点被转义成 `\\.`
      `.text-\\[11px\\]{...}`    —— 任意值里的方括号被转义成 `\\[` `\\]`
    所以必须按「反斜杠转义下一个字符」来解析，不能简单 `replace('\\\\','')`
    —— 后者会把 `\\.` 变成 `.` 的同时也吞掉相邻字符，得到一堆假的类名。
    """
    text = CSS.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        if text[i] != ".":
            i += 1
            continue
        # `.` 后面必须是合法类名起始字符（不能是数字，避免命中 `.5em` 之类）
        j = i + 1
        buf = []
        while j < n:
            ch = text[j]
            if ch == "\\" and j + 1 < n:      # 转义：吃掉反斜杠，保留下一个字符
                buf.append(text[j + 1])
                j += 2
                continue
            if ch.isalnum() or ch in "-_":
                buf.append(ch)
                j += 1
                continue
            break
        if buf and not buf[0].isdigit():
            out.add("".join(buf))
        i = j if j > i else i + 1
    return out


def is_tailwind_like(cls: str) -> bool:
    base = VARIANT_RE.sub("", cls)
    return any(base == p or base.startswith(p) for p in TAILWIND_PREFIXES)


def looks_like_class(cls: str) -> bool:
    """过滤掉从模板字符串里误抓的伪类名。

    页面里有大量三元表达式写在 class 属性里，例如：
        class="${x ? 'bg-slate-50' : 'text-indigo-600'}"
    朴素的 `class="([^"]*)"` 正则会把它整体当成一个类名
    （`bg-slate-50':'text-indigo-600`），产生一堆误报。
    真实类名不可能含引号、冒号之外的分隔符、大括号、括号等字符。
    """
    if not cls or any(c in cls for c in "\"'{}()<>=,;"):
        return False
    # 变体前缀（md: / hover:）里的冒号是合法的，但出现多个冒号基本是误抓
    if cls.count(":") > 1:
        return False
    return True


def project_custom_classes(html: str) -> set[str]:
    """项目自定义类名（定义在页面内联 <style> 和 console.css 里）。

    这些不是 Tailwind 工具类，不该报「缺失」—— 例如 .tnum / .col-status / .bg-wb。
    直接从内联 style 块和 CSS 文件里扫出所有 `.xxx` 选择器。
    """
    out: set[str] = set()
    sources = []
    for m in re.finditer(r"(?s)<style[^>]*>(.*?)</style>", html):
        sources.append(m.group(1))
    for css_file in (REPO / "admin/static/console.css",
                     REPO / "admin/static/desktop.css",
                     REPO / "admin/static/growth_center.css"):
        if css_file.is_file():
            sources.append(css_file.read_text(encoding="utf-8", errors="replace"))
    for text in sources:
        for m in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_-]*)", text):
            out.add(m.group(1))
    return out


def main() -> int:
    css_classes = load_css_classes()
    html = HTML.read_text(encoding="utf-8", errors="replace")
    custom = project_custom_classes(html)

    # 抽出所有 class="..." 和模板字符串里的 class="..."
    used: dict[str, list[int]] = {}
    for m in re.finditer(r'class="([^"]*)"', html):
        line = html[:m.start()].count("\n") + 1
        for cls in m.group(1).split():
            used.setdefault(cls, []).append(line)

    missing = []
    for cls, lines in sorted(used.items()):
        if not looks_like_class(cls):
            continue          # 模板字符串里误抓的伪类名
        if cls in custom:
            continue          # 项目自定义类，定义在内联 style / css 文件里
        if not is_tailwind_like(cls):
            continue
        if cls in css_classes:
            continue
        # 统计同族类有多少，用来判断「这个类是该族完全没编译，还是只漏了个别值」
        base = VARIANT_RE.sub("", cls)
        same_prefix = [c for c in css_classes if c.startswith(base[:6])]
        missing.append((cls, lines[0], len(lines), len(same_prefix)))

    print(f"预编译 CSS 类名总数: {len(css_classes)}")
    print(f"HTML 里用到的类名总数: {len(used)}")
    print()
    if not missing:
        print("✔ 没有任何 Tailwind 类缺失")
        return 0

    print(f"⚠ {len(missing)} 个 Tailwind 类**不在预编译 CSS 里**（会静默失效）：")
    print()
    for cls, line, cnt, pref_count in missing:
        flag = "  ← 同族类也很少，几乎肯定没编译" if pref_count < 3 else ""
        print(f"  {cls:<24} 首次出现 行{line:<6} 用{cnt}次{flag}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
