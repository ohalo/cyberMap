#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 收录站点存活复检器（source/daily/health.json）

对 ``webstack.yml`` 里全部分类的站点做一次周期性存活复检，
产出仓库内静态数据 ``source/daily/health.json``，供 ``build_daily.py`` 在时间轴
卡片上渲染「持续在线 / 疑似失效 / 待核对」小标记，把一次性收录核验升级为长期可信导航。

设计要点
--------
* 并入每日收录，但内部 7 天降频：``cybermap.py add`` 每天顺带调用本脚本，脚本
  先读现有 health.json 的 ``generated_at``——距上次复检 < ``--interval-days``（默认
  7 天）则**直接跳过**（不探测、不重写产物、退出码 0，输出 ``skipped=true``），
  绝大多数日子是零成本 no-op。等效每周一次，且无需额外建独立定时任务。
  产物缺失 / 时间戳损坏时必跑；手动想立即复检用 ``--force`` 绕过降频。
* 三态判定，绝不误伤（用户重视数据严谨）：
    - ``ok``        在线：HTTP 2xx/3xx，或 GitHub API 200 未归档。
    - ``down``      疑似失效：404/410、域名停放、明确软 404、GitHub 仓库 404/归档。
    - ``unverified`` 待核对：本机网络策略导致的 ConnectTimeout / ProxyError /
                     502 隧道失败 / 429 限流 / 403 反爬 —— 这些**不代表站点失效**，
                     判为待核对，既不标红也不算在线，等下次网络正常时复检。
* GitHub 仓库走 ``api.github.com``（网页经本机代理会 502），用 ``requests`` 时
  调用方需前置 ``NO_PROXY='*' no_proxy='*'``（见 memory 的环境事实）。
* 零新增依赖：requests（仓库已有）+ 标准库；只读 webstack.yml，绝不改写。
* 非破坏性：health.json 缺失或损坏时 build_daily 优雅降级；本脚本失败不阻断任何东西。
* 输入决定输出：时间戳用运行时刻（这是复检快照，不是幂等产物），结构稳定可 --check 校验。

用法
----
    NO_PROXY='*' no_proxy='*' python scripts/health_check.py --repo <repo>
    NO_PROXY='*' no_proxy='*' python scripts/health_check.py --repo <repo> --check
    NO_PROXY='*' no_proxy='*' python scripts/health_check.py --repo <repo> --force
    NO_PROXY='*' no_proxy='*' python scripts/health_check.py --repo <repo> --interval-days 14
    NO_PROXY='*' no_proxy='*' python scripts/health_check.py --repo <repo> --workers 8 --timeout 12

退出码：0 成功或因降频跳过（stdout JSON 含 ``skipped`` 字段）；1 参数/写入错误（stdout 输出 JSON 诊断）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"缺少 PyYAML：{exc}"}, ensure_ascii=False))
    sys.exit(1)

try:
    import requests
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"缺少 requests：{exc}"}, ensure_ascii=False))
    sys.exit(1)


DATA_REL = Path("source/_data/webstack.yml")
OUT_REL = Path("source/daily/health.json")
# 复检范围：全部分类（每日收录按性质路由进常设分类后，新站点可能落在任何分类）。
# 扫描方式是「读所有顶层列表分类」，不再依赖固定分类名单；6 并发 + 单站 12s
# 超时 + 7 天降频闸门控制成本。
ALL_SITE_CATEGORIES = (
    "dailyAI_oss", "dailyAI_tool", "dailyAI_model",
    "aiChat", "aiImage", "aiVideo", "aiCode", "aiOffice", "aiAgent",
    "GPTModels", "githubGPT", "aiFrameworks", "ragKnowledge", "agentFrameworks",
    "studyGPT", "techBlog", "aiNav", "likeGPT", "hotTools", "myBlog",
)
CST = timezone(timedelta(hours=8))
CHECK_INTERVAL_DAYS = 7  # 距上次复检不足此天数则跳过（并入每日任务的降频闸门）

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 域名停放 / 待建 / 软 404 文本特征（命中即判 down，但仅在 HTTP 200 且有明确特征时）
PARKING_RE = re.compile(
    r"domain (?:is )?(?:for sale|parked|expired)|buy this domain|"
    r"this domain (?:has expired|is pending)|网站已过期|域名已过期|"
    r"待建站|under construction|site not found|404 not found|page not found",
    re.I,
)
GH_REPO_RE = re.compile(r"^/?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$")

# 本机网络策略特征：出现这些网络层错误时判 unverified，绝不判死链
NETWORK_ERR_TOKENS = (
    "proxerror", "proxyerror", "tunnel connection failed", "502",
    "connecttimeout", "connection timed out", "timed out", "timeout",
    "connection refused", "name or service not known", "temporary failure in name resolution",
    "ssl", "certificate verify failed", "connectionerror", "max retries exceeded",
)


def norm(url: str) -> str:
    """与 cybermap.py / build_verify.py 的 norm() 完全一致，保证按 URL 命中。"""
    from urllib.parse import urlparse
    raw = (url or "").strip().rstrip(",;'\"")
    p = urlparse(raw if "://" in raw else "https://" + raw)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = (p.path or "/").rstrip("/").lower() or "/"
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host}{path}"


def load_sites(data_file: Path) -> tuple[list[dict], list[str]]:
    """读取全部分类的 (name, url) 列表，按 URL 去重。"""
    if not data_file.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_file}")
    try:
        data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"webstack.yml 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("webstack.yml 顶层不是映射")

    sites, warnings, seen = [], [], set()
    for cat in ALL_SITE_CATEGORIES:
        block = data.get(cat)
        if not isinstance(block, list):
            warnings.append(f"分类 {cat} 不是列表或不存在，已跳过")
            continue
        for raw in block:
            if not isinstance(raw, dict) or not raw.get("url") or not raw.get("name"):
                warnings.append(f"分类 {cat} 中存在缺 name/url 的条目，已跳过")
                continue
            key = norm(str(raw["url"]))
            if not key or key in seen:
                continue
            seen.add(key)
            sites.append({
                "name": str(raw["name"]),
                "url": str(raw["url"]),
                "key": key,
                "category": cat,
            })
    return sites, warnings


def github_slug(url: str) -> str | None:
    """若是 github.com/owner/repo 返回 'owner/repo'，否则 None。"""
    p = urlparse(url if "://" in url else "https://" + url)
    host = (p.hostname or "").lower()
    if host not in ("github.com", "www.github.com"):
        return None
    m = GH_REPO_RE.match(p.path)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def classify_network_error(msg: str) -> bool:
    low = (msg or "").lower()
    return any(tok in low for tok in NETWORK_ERR_TOKENS)


def probe_github(slug: str, timeout: int, session) -> dict:
    """GitHub 仓库：以 api.github.com 元数据为准（存在性 / 归档 / 最近推送）。"""
    url = f"https://api.github.com/repos/{slug}"
    try:
        r = session.get(url, timeout=timeout,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
    except requests.RequestException as exc:
        if classify_network_error(str(exc)):
            return {"status": "unverified", "http_status": None,
                    "note": f"GitHub API 网络不可判定：{type(exc).__name__}"}
        return {"status": "unverified", "http_status": None,
                "note": f"GitHub API 请求异常：{type(exc).__name__}"}
    code = r.status_code
    if code == 200:
        try:
            data = r.json()
        except ValueError:
            return {"status": "unverified", "http_status": code, "note": "GitHub API 返回非 JSON"}
        if data.get("archived") or data.get("disabled"):
            return {"status": "down", "http_status": code,
                    "note": f"仓库已归档/禁用（archived={data.get('archived')}）"}
        return {"status": "ok", "http_status": code,
                "note": f"GitHub 仓库在线 · ★{data.get('stargazers_count')} · 最近推送 {str(data.get('pushed_at'))[:10]}",
                "stars": data.get("stargazers_count")}
    if code == 404:
        return {"status": "down", "http_status": code, "note": "GitHub 仓库 404（不存在或已删除）"}
    if code in (403, 429):
        return {"status": "unverified", "http_status": code, "note": "GitHub API 限流/拒绝，待核对"}
    return {"status": "unverified", "http_status": code, "note": f"GitHub API 异常状态 {code}，待核对"}


def probe_web(url: str, timeout: int, session) -> dict:
    """非 GitHub 站点：HTTP 实探 + 停放页特征检测。"""
    try:
        r = session.get(url, timeout=timeout, headers={"User-Agent": UA},
                        allow_redirects=True, stream=True)
    except requests.RequestException as exc:
        if classify_network_error(str(exc)):
            return {"status": "unverified", "http_status": None,
                    "note": f"本机网络策略不可判定：{type(exc).__name__}"}
        return {"status": "unverified", "http_status": None,
                "note": f"请求异常：{type(exc).__name__}"}
    code = r.status_code
    final = r.url
    title = ""
    snippet = ""
    try:
        chunk = ""
        for part in r.iter_content(4096):
            chunk += part.decode("utf-8", "replace")
            if len(chunk) >= 65536:
                break
        m = re.search(r"<title[^>]*>(.*?)</title>", chunk, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:160]
        snippet = re.sub(r"<[^>]+>", " ", chunk[:20000])
    except Exception:  # noqa: BLE001 - 读正文失败不影响状态码判定
        pass
    finally:
        r.close()

    if code in (404, 410):
        return {"status": "down", "http_status": code, "note": f"HTTP {code}（页面不存在）"}
    if code in (401, 403, 429):
        return {"status": "unverified", "http_status": code,
                "note": f"HTTP {code}（反爬/需鉴权/限流），待核对"}
    if 200 <= code < 400:
        if PARKING_RE.search(snippet):
            return {"status": "down", "http_status": code, "note": "命中域名停放/软 404 特征"}
        note = f"HTTP {code} 在线"
        if title:
            note += f" · {title}"
        return {"status": "ok", "http_status": code, "note": note,
                "title": title, "final_url": final}
    return {"status": "unverified", "http_status": code, "note": f"HTTP {code}，待核对"}


def check_one(site: dict, timeout: int) -> dict:
    """对单个站点复检，返回可写入 health.json 的记录（含三态）。"""
    slug = github_slug(site["url"])
    # 每个线程一个 Session，避免共享连接池的线程安全问题
    session = requests.Session()
    session.trust_env = False  # 强制忽略系统代理（本机 7890 死代理），直连
    try:
        if slug:
            result = probe_github(slug, timeout, session)
            result["target"] = slug
        else:
            result = probe_web(site["url"], timeout, session)
    finally:
        session.close()

    checked_at = datetime.now(CST).isoformat(timespec="seconds")
    record = {
        "name": site["name"],
        "url": site["url"],
        "category": site["category"],
        "status": result["status"],
        "http_status": result.get("http_status"),
        "note": result.get("note", ""),
        "checked_at": checked_at,
    }
    for extra in ("stars", "title", "final_url", "target"):
        if extra in result:
            record[extra] = result[extra]
    return site["key"], record


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def check_due(out: Path, interval_days: int, now: datetime | None = None) -> dict:
    """降频闸门：判断本次是否该真正复检。

    读现有产物的 ``generated_at``，距现在 < ``interval_days`` 天则 ``due=False``。
    产物缺失 / 时间戳损坏 / 间隔参数非法时一律 ``due=True``（宁可多跑，不可漏检）。
    返回诊断 dict，供 stdout 的 ``skip_info`` 使用。
    """
    now = now or datetime.now(CST)
    info: dict = {"interval_days": interval_days}
    if not out.is_file():
        return {"due": True, "reason": "no_existing_report", **info}
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
        ts = data.get("generated_at")
        if not ts:
            return {"due": True, "reason": "missing_generated_at", **info}
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=CST)
        age = now - last
        info["generated_at"] = ts
        info["age_hours"] = round(age.total_seconds() / 3600, 1)
        if age < timedelta(days=interval_days):
            return {"due": False, "reason": "within_interval", **info}
        return {"due": True, "reason": "interval_elapsed", **info}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"due": True, "reason": f"unreadable_report:{type(exc).__name__}", **info}


def main() -> int:
    ap = argparse.ArgumentParser(description="复检 cyberMap 收录站点存活状态")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                    help="cyberMap 仓库根目录")
    ap.add_argument("--workers", type=int, default=6, help="并发线程数（默认 6）")
    ap.add_argument("--timeout", type=int, default=12, help="单站点超时秒数（默认 12）")
    ap.add_argument("--check", action="store_true", help="只校验现有 health.json，不探测/不写")
    ap.add_argument("--force", action="store_true",
                    help="忽略 7 天降频闸门，强制立即复检（人工想立刻看最新状态时用）")
    ap.add_argument("--interval-days", type=int, default=CHECK_INTERVAL_DAYS,
                    help=f"复检间隔天数（默认 {CHECK_INTERVAL_DAYS}）")
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = repo / OUT_REL

    if args.interval_days < 0:
        print(json.dumps({"ok": False, "error": "--interval-days 不能为负数"},
                         ensure_ascii=False, indent=2))
        return 1

    # --check 是纯校验，放在降频闸门之前，不受 7 天降频影响。
    if args.check:
        if not out.is_file():
            print(json.dumps({"ok": False, "error": f"health.json 不存在：{out}"},
                             ensure_ascii=False, indent=2))
            return 1
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            sites = data.get("sites") or {}
            statuses = [s.get("status") for s in sites.values()]
            assert data.get("schema") == 1, "schema 不是 1"
            assert all(x in ("ok", "down", "unverified") for x in statuses), "存在非法状态"
        except (OSError, json.JSONDecodeError, AssertionError) as exc:
            print(json.dumps({"ok": False, "error": f"health.json 校验失败：{exc}"},
                             ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"ok": True, "check_only": True, "sites": len(sites),
                          "summary": data.get("summary")}, ensure_ascii=False, indent=2))
        return 0

    # 降频闸门：并入每日任务后每天都会被调用，但距上次复检不足 N 天直接跳过，
    # 不探测、不重写产物（blob 不变 → commit 无额外 diff）。--force 可绕过。
    if not args.force:
        gate = check_due(out, args.interval_days)
        if not gate["due"]:
            print(json.dumps({
                "ok": True, "skipped": True, "reason": "within_interval",
                "output": str(OUT_REL), "skip_info": gate,
            }, ensure_ascii=False, indent=2))
            return 0

    if args.workers < 1 or args.timeout < 1:
        print(json.dumps({"ok": False, "error": "--workers / --timeout 必须为正整数"},
                         ensure_ascii=False, indent=2))
        return 1

    try:
        sites, warnings = load_sites(repo / DATA_REL)
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    if not sites:
        print(json.dumps({"ok": False, "error": "webstack.yml 中没有可复检的站点"},
                         ensure_ascii=False, indent=2))
        return 1

    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_one, site, args.timeout): site for site in sites}
        for fut in concurrent.futures.as_completed(futures):
            try:
                key, record = fut.result()
                results[key] = record
            except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮整批
                site = futures[fut]
                warnings.append(f"{site['name']} 复检异常：{type(exc).__name__}: {exc}")
                results[site["key"]] = {
                    "name": site["name"], "url": site["url"], "category": site["category"],
                    "status": "unverified", "http_status": None,
                    "note": f"复检异常：{type(exc).__name__}",
                    "checked_at": datetime.now(CST).isoformat(timespec="seconds"),
                }

    summary = {"checked": len(results)}
    for status in ("ok", "down", "unverified"):
        summary[status] = sum(1 for r in results.values() if r["status"] == status)

    payload = {
        "schema": 1,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "source": "source/_data/webstack.yml :: 全部分类",
        "note": "三态：ok=在线 / down=疑似失效 / unverified=本机网络不可判定（不算失效）。并入每日收录、脚本内 7 天降频复检。",
        "summary": summary,
        "sites": dict(sorted(results.items())),
        "warnings": warnings,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    # 回读自检
    try:
        check = json.loads(text)
        assert len(check["sites"]) == len(results), "站点数不一致"
        assert check["summary"]["checked"] == len(results), "汇总数不一致"
    except (json.JSONDecodeError, AssertionError) as exc:
        print(json.dumps({"ok": False, "error": f"产物自检失败：{exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    try:
        atomic_write(out, text)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"写入失败：{exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "ok": True,
        "output": str(OUT_REL),
        "bytes": out.stat().st_size,
        "summary": summary,
        "down_sites": [r["name"] for r in results.values() if r["status"] == "down"],
        "unverified_sites": [r["name"] for r in results.values() if r["status"] == "unverified"],
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
