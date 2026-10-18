"""生成「离线静态预览」单文件 HTML：面板页 + 全部真实数据打包成一个可直接双击打开的 .html。

为什么必须内联（否则 file:// 打不开）：
  * admin/static/index.html 的资源都用绝对路径 /static/...，file:// 下会解析到盘符根；
  * 页面数据全走 fetch(/api/...)，file:// 源请求 http://127.0.0.1 会被 CORS 拦。

产物：C:\\Users\\<user>\\Desktop\\workbuddy-panel-preview.html —— 双击即开，无需任何服务。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(r"G:\ZCode\workbuddy2api-xiaofan6ya")
STATIC = REPO / "admin" / "static"
DATA = Path(r"E:\1反代项目\workbuddy2api-xiaofan6ya")
OUT = Path(os.path.expanduser("~")) / "Desktop" / "workbuddy-panel-preview.html"

CFG = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
BASE = f"http://127.0.0.1:{CFG['port']}"

#: 首屏 enterApp() 立刻请求的 + 各面板打开时请求的接口。
ENDPOINTS = [
    "/api/accounts",
    "/api/keys",
    "/api/models/configs",
    "/api/models/display",
    "/api/schedules",
    "/api/sync/config",
    "/api/app/network",
    "/api/app/version",
    "/api/groups",
    "/api/client-profile",
    "/api/app-source/status",
    "/api/credits/expiry?include_disabled=1",
    "/api/credits/usage?days=7&top=12",
    "/api/logs/accounts?days=1",
    "/api/logs/summary?days=1",
    "/api/logs?days=1&page=1&page_size=50",
    "/api/stats/usage/options?days=1",
    "/api/stats/usage?days=1&granularity=hour",
    "/api/accounts/model-limits",
    "/api/accounts/duplicates",
]

MIME = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf",
        "otf": "font/otf", "svg": "image/svg+xml", "png": "image/png"}


def make_token() -> str:
    import jwt
    return jwt.encode({"sub": CFG["username"], "local_shell": True},
                      CFG["jwt_secret"], algorithm="HS256")


def fetch(path: str, token: str):
    req = urllib.request.Request(BASE + path, headers={"X-Admin-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, {"_error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return 0, {"_error": str(e)}


def read_asset(rel: str) -> bytes | None:
    p = STATIC / rel
    return p.read_bytes() if p.is_file() else None


def inline_css(rel: str, missing: list[str]) -> str | None:
    """读一个 CSS，并把里面的 url(...) 字体/图片转成 data URI。"""
    blob = read_asset(rel)
    if blob is None:
        missing.append(rel)
        return None
    text = blob.decode("utf-8", "replace")
    parent = Path(rel).parent

    def repl_url(m: re.Match) -> str:
        target = m.group(1).strip().strip("'\"")
        if not target or target.startswith(("data:", "http:", "https:", "#")):
            return m.group(0)
        resolved = (parent / target).as_posix()
        resolved = re.sub(r"^\./", "", resolved)
        # 处理 ../ 跳出
        parts: list[str] = []
        for seg in resolved.split("/"):
            if seg == "..":
                if parts:
                    parts.pop()
            elif seg not in ("", "."):
                parts.append(seg)
        resolved = "/".join(parts)
        b = read_asset(resolved)
        if b is None:
            missing.append(resolved)
            return m.group(0)
        mime = MIME.get(resolved.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        return f"url('data:{mime};base64,{base64.b64encode(b).decode()}')"

    return re.sub(r"url\(([^)]+)\)", repl_url, text)


def inline_all(html: str) -> tuple[str, list[str], int]:
    missing: list[str] = []
    count = 0

    def repl_link(m: re.Match) -> str:
        nonlocal count
        rel = m.group(1)
        css = inline_css(rel, missing)
        if css is None:
            return m.group(0)
        count += 1
        return f'<style data-inlined="{rel}">\n{css}\n</style>'

    html = re.sub(
        r'<link[^>]*?rel="stylesheet"[^>]*?href="/static/([^"]+)"[^>]*?/?>',
        repl_link, html)

    def repl_script(m: re.Match) -> str:
        nonlocal count
        rel = m.group(1)
        blob = read_asset(rel)
        if blob is None:
            missing.append(rel)
            return m.group(0)
        count += 1
        return f'<script data-inlined="{rel}">\n{blob.decode("utf-8", "replace")}\n</script>'

    html = re.sub(r'<script[^>]*?src="/static/([^"]+)"[^>]*?>\s*</script>',
                  repl_script, html)

    # 图标是唯一一个 /api 引用：file:// 下取不到，直接去掉（浏览器会回退到默认 favicon）
    html = re.sub(r'<link[^>]*?rel="icon"[^>]*?/?>', "", html)
    return html, missing, count


def build_shim(snapshot: dict) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False)
    at = json.dumps(snapshot.get("__meta__", {}).get("at", ""))
    return f"""<script>
/* ===== 离线预览：数据快照 + fetch 拦截 =====
 * 生成时间 {snapshot.get('__meta__', {}).get('at', '')}，数据来自真实网关 {BASE}
 * 页面里所有 fetch('/api/...') 都被本地快照接管，因此无需后端、无需起服务。
 * 想恢复「真实联网」，控制台执行 window.__WB_OFFLINE = false 再刷新。
 */
window.__WB_SNAPSHOT_AT = {at};
window.__WB_OFFLINE = true;
window.__WB_SNAPSHOT = {payload};

(function () {{
  const snap = window.__WB_SNAPSHOT;

  /* 从请求 URL 里抽出「路径 + 查询串」。
   *
   * ⚠️ 这里**不能**用 new URL(u, location.href)：页面是以 file:// 打开的，
   * 绝对路径 '/api/accounts' 在 file 协议下会被解析成 file:///C:/api/accounts，
   * pathname 变成 '/C:/api/accounts'，于是下面的 startsWith('/api/') 判断失败、
   * 请求漏给真实 fetch，整页数据全空（这个坑实测踩过一次）。
   * 所以改用纯字符串处理：先砍掉协议+主机，再取 pathname+search。 */
  function normalize(u) {{
    let s = String(u || '');
    // 去掉 http(s)://host、file:// 之类的前缀
    s = s.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\\/\\/[^/]*/, '');
    // file:///C:/api/x 这种带盘符的，去掉前导 '/C:' / '/D:' 之类
    s = s.replace(/^\\/[a-zA-Z]:/, '');
    if (!s.startsWith('/')) {{
      // 相对路径：退化成用 URL 解析（file:// 下相对路径是安全的）
      try {{
        const url = new URL(s, location.href);
        s = url.pathname + (url.search || '');
      }} catch (e) {{ return s; }}
    }}
    return s;
  }}

  /* 三级匹配：精确 URL -> 仅路径 -> 最长公共前缀，保证带查询串的请求也能命中 */
  function lookup(key) {{
    if (key in snap) return snap[key];
    const pathOnly = key.split('?')[0];
    if (pathOnly in snap) return snap[pathOnly];
    let best, bestLen = -1;
    for (const k of Object.keys(snap)) {{
      const kp = k.split('?')[0];
      if (key.startsWith(kp) && kp.length > bestLen) {{ best = snap[k]; bestLen = kp.length; }}
    }}
    return best;
  }}

  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {{
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const key = normalize(url);
    if (window.__WB_OFFLINE && key.startsWith('/api/')) {{
      const hit = lookup(key);
      const body = hit !== undefined
        ? (typeof hit === 'string' ? hit : JSON.stringify(hit))
        : JSON.stringify({{ detail: '离线快照未含此接口: ' + key }});
      return Promise.resolve(new Response(body, {{
        status: 200, headers: {{ 'Content-Type': 'application/json; charset=utf-8' }},
      }}));
    }}
    return realFetch(input, init);
  }};
}})();
</script>
"""


def main() -> int:
    token = make_token()
    print(f"数据源 {BASE}")
    snapshot: dict = {}
    ok = fail = 0
    for ep in ENDPOINTS:
        status, data = fetch(ep, token)
        good = status == 200 and not (isinstance(data, dict) and "_error" in data)
        if good:
            snapshot[ep] = data
            ok += 1
            print(f"  ok   {ep}  ({len(json.dumps(data, ensure_ascii=False))} B)")
        else:
            fail += 1
            detail = data if isinstance(data, str) else data.get("_error")
            print(f"  skip {ep}  -> {status} {detail}")

    snapshot["__meta__"] = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "source": BASE, "ok": ok, "fail": fail}

    print("\n内联静态资源 …")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html, missing, count = inline_all(html)
    print(f"  内联成功 {count} 个，缺失 {len(missing)} 个")
    for m in missing:
        print(f"    miss {m}")

    html = html.replace("<head>", "<head>\n" + build_shim(snapshot), 1)
    # 离线预览直接进应用，不停在登录页
    html = html.replace('let TOKEN = localStorage.getItem(TOKEN_KEY) || "";',
                        'let TOKEN = localStorage.getItem(TOKEN_KEY) || "offline-preview";', 1)

    OUT.write_text(html, encoding="utf-8")
    print(f"\n已生成 {OUT}")
    print(f"  {OUT.stat().st_size / 1048576:.2f} MB  |  接口 {ok} ok / {fail} skip")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
