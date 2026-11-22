#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 上游变更雷达（source/daily/updates.json）

每天对 webstack.yml 里 dailyAI_* 的 GitHub 项目做一次「上游动态」采集：
记录每个仓库的 pushed_at / stars，与上一次快照对比，算出「有新提交 / 涨星」，
在 /daily/ 时间轴顶部渲染「上游变更雷达」区块。与 health.json（站点是否存活）
正交：health 回答「站还在吗」，updates 回答「项目最近动了吗」。

设计要点（严谨性优先，用户重视数据可信）
----------------------------------------
* 冷启动不误报：第一次见到某仓库（无历史快照）只建立基线（etag/pushed_at/stars），
  **不产生任何变更记录**。否则首次运行会把全部仓库误报成「今日有新动态」。
  只有第二次及以后，确实对比到 pushed_at 变新 / stars 增长才记变更。
* ETag 条件请求破限流：已跟踪仓库带 ``If-None-Match`` 请求，未变更返回 304，
  GitHub 对 304 **不计入 primary rate limit**；只有真正变化的仓库才计 1 次。
  稳态下每天成本 = verify 的收录数 + 少数变更仓库，远低于匿名 60 次/小时。
* 配额闸门 + 分批覆盖：无 ETag 的「新仓库」是冷请求，每天限量（默认 35 个），
  并持续监控响应头 ``X-RateLimit-Remaining``，低于保留值（默认 6）即停手，
  未覆盖的标 ``pending`` 留到次日。全站约 66 个 GitHub 项目，2 天内全量收敛。
  优先新收录（dailyAI_* 里靠前）的项目建立基线，用户最关心的先上线。
* 同日闸门：若快照 generated_at 就是今天且非 --force，直接跳过（零请求、零写入），
  防止同日二次触发重复烧配额。产物缺失 / 时间戳损坏 / --force 时必跑。
* 三态网络处理：403/429 判限流（停手 + warning，不误判仓库异常）；404 跳过；
  超时/代理/连接错误记 warning 并保留旧快照，绝不伪造变更。
* 零新增依赖：requests（仓库已有）+ PyYAML + 标准库；只读 webstack.yml，绝不改写。
* 优雅降级：updates.json 缺失或损坏时 build_daily 不渲染雷达区块，不阻断任何东西。

用法
----
    NO_PROXY='*' no_proxy='*' python scripts/track_updates.py --repo <repo>
    NO_PROXY='*' no_proxy='*' python scripts/track_updates.py --repo <repo> --force
    NO_PROXY='*' no_proxy='*' python scripts/track_updates.py --repo <repo> --check
    NO_PROXY='*' no_proxy='*' python scripts/track_updates.py --repo <repo> --max-fresh 10

退出码：0 成功或因同日闸门跳过（stdout JSON 含 skipped）；1 参数/写入错误。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
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
OUT_REL = Path("source/daily/updates.json")
DAILY_CATEGORIES = ("dailyAI_oss", "dailyAI_tool", "dailyAI_model")
CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
DEFAULT_MAX_FRESH = 35      # 每天最多建立基线的新仓库数（匿名配额 60/h，留足余量）
DEFAULT_RESERVE = 6         # X-RateLimit-Remaining 低于此值即停手
RECENT_DAYS = 7             # 雷达展示最近 N 天的变更
MAX_RECENT = 40             # 雷达最多展示的变更条数
MAX_CHANGES_PER_REPO = 6    # 每仓库保留的最近变更条数


def github_slug(url: str) -> str | None:
    """是 github.com/owner/repo 则返回 'owner/repo'，否则 None。"""
    p = urlparse(url if "://" in url else "https://" + url)
    if (p.hostname or "").lower().removeprefix("www.") != "github.com":
        return None
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def norm(url: str) -> str:
    raw = (url or "").strip().rstrip(",;'\"")
    p = urlparse(raw if "://" in raw else "https://" + raw)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = (p.path or "/").rstrip("/").lower() or "/"
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host}{path}"


def load_repos(data_file: Path) -> tuple[list[dict], list[str]]:
    """读取 dailyAI_* 中的 GitHub 仓库，按在 YAML 里的顺序（新收录在前）。"""
    if not data_file.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_file}")
    data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("webstack.yml 顶层不是映射")
    repos, warnings, seen = [], [], set()
    for cat in DAILY_CATEGORIES:
        block = data.get(cat)
        if not isinstance(block, list):
            warnings.append(f"分类 {cat} 不是列表或不存在，已跳过")
            continue
        for raw in block:
            if not isinstance(raw, dict) or not raw.get("url") or not raw.get("name"):
                continue
            slug = github_slug(str(raw["url"]))
            if not slug or slug.lower() in seen:
                continue
            seen.add(slug.lower())
            repos.append({
                "slug": slug,
                "name": str(raw["name"]),
                "url": str(raw["url"]),
                "category": cat,
                "key": norm(str(raw["url"])),
            })
    return repos, warnings


def load_prev(out: Path) -> tuple[dict, dict]:
    """读上一次快照，返回 (repos dict, payload 诊断)。文件缺失时返回空。"""
    if not out.is_file():
        return {}, {}
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
            raise ValueError("updates.json 结构不完整")
        return data["repos"], data
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, {"load_error": str(exc)}


def is_same_day(prev_payload: dict, now: datetime) -> bool:
    ts = (prev_payload or {}).get("generated_at") or ""
    return ts[:10] == now.date().isoformat()


def probe_one(site: dict, prev: dict, state: dict, lock: threading.Lock,
              max_fresh: int, reserve: int, timeout: int) -> tuple[str, dict | None, str]:
    """采集单仓库。返回 (key, 新快照 or None, 结果标记)。"""
    slug = site["slug"]
    key = site["key"]
    prev_etag = (prev or {}).get("etag")
    is_fresh = not prev_etag  # 无 ETag = 冷请求，需要建基线

    with lock:
        if state["stop"]:
            return key, None, "stopped"
        if state["remaining"] is not None and state["remaining"] <= reserve:
            return key, None, "rate_low"
        if is_fresh:
            if state["fresh_used"] >= max_fresh:
                return key, None, "fresh_cap"
            state["fresh_used"] += 1  # 原子占位，防止并发超发（在发请求前锁定名额）

    session = requests.Session()
    session.trust_env = False  # 绕开本机 7890 死代理，直连 api.github.com
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA,
               "X-GitHub-Api-Version": "2022-11-28"}
    if not is_fresh:
        headers["If-None-Match"] = prev_etag

    try:
        r = session.get(f"https://api.github.com/repos/{slug}", timeout=timeout, headers=headers)
        with lock:
            rem = r.headers.get("X-RateLimit-Remaining")
            if rem is not None and rem.isdigit():
                state["remaining"] = (min(state["remaining"], int(rem))
                                      if state["remaining"] is not None else int(rem))
        today = datetime.now(CST).date().isoformat()

        if r.status_code == 304:
            # 未变更：304 不计配额。保留旧快照，只更新检查时间。
            snap = dict(prev)
            snap["last_checked"] = datetime.now(CST).isoformat(timespec="seconds")
            return key, snap, "not_modified"

        if r.status_code == 403 or r.status_code == 429:
            with lock:
                state["stop"] = True
                state["remaining"] = 0
            return key, None, "rate_limited"

        if r.status_code == 404:
            return key, None, "not_found"

        if r.status_code != 200:
            return key, None, f"http_{r.status_code}"

        data = r.json()
        etag = r.headers.get("ETag") or prev_etag
        pushed_at = data.get("pushed_at")
        stars = data.get("stargazers_count")
        if stars is not None and not isinstance(stars, int):
            stars = None

        changes = list((prev or {}).get("changes") or [])
        status = "baseline" if not prev else "checked"

        if prev and prev.get("etag"):
            # 有历史基线：对比产生变更（严谨：只有确实变新/变多才记）
            old_push, old_stars = prev.get("pushed_at"), prev.get("stars")
            if pushed_at and old_push and pushed_at > old_push:
                changes.append({"date": today, "kind": "push", "from": old_push, "to": pushed_at})
            if (stars is not None and old_stars is not None and isinstance(old_stars, int)
                    and stars > old_stars):
                changes.append({"date": today, "kind": "star", "from": old_stars,
                                "to": stars, "delta": stars - old_stars})
            if len(changes) != len((prev or {}).get("changes") or []):
                status = "changed"

        changes = changes[-MAX_CHANGES_PER_REPO:]
        snap = {
            "name": site["name"], "url": site["url"], "category": site["category"],
            "etag": etag, "pushed_at": pushed_at, "stars": stars,
            "last_checked": datetime.now(CST).isoformat(timespec="seconds"),
            "first_seen": (prev or {}).get("first_seen") or today,
            "changes": changes,
        }
        return key, snap, status
    except requests.RequestException as exc:
        return key, None, f"network_{type(exc).__name__}"
    finally:
        session.close()


def build_recent(all_repos: dict, now: datetime) -> list[dict]:
    """聚合各仓库近 RECENT_DAYS 天的变更，按 (仓库, 日期) 合并为一条。"""
    cutoff = (now.date() - timedelta(days=RECENT_DAYS)).isoformat()
    grouped: dict[tuple[str, str], dict] = {}
    for key, snap in all_repos.items():
        for ch in snap.get("changes") or []:
            d = ch.get("date") or ""
            if d < cutoff:
                continue
            k = (key, d)
            item = grouped.setdefault(k, {
                "name": snap.get("name"), "url": snap.get("url"),
                "category": snap.get("category"), "date": d,
                "has_push": False, "star_delta": 0,
                "pushed_at": snap.get("pushed_at"), "stars": snap.get("stars"),
            })
            if ch.get("kind") == "push":
                item["has_push"] = True
            elif ch.get("kind") == "star":
                item["star_delta"] += int(ch.get("delta") or 0)
    recent = sorted(grouped.values(), key=lambda x: (x["date"], x["star_delta"]), reverse=True)
    return recent[:MAX_RECENT]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="采集 cyberMap 收录项目的上游变更（每天更新）")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--max-fresh", type=int, default=DEFAULT_MAX_FRESH,
                    help=f"每天最多建立基线的新仓库数（默认 {DEFAULT_MAX_FRESH}）")
    ap.add_argument("--reserve", type=int, default=DEFAULT_RESERVE,
                    help=f"API 剩余配额低于此值即停手（默认 {DEFAULT_RESERVE}）")
    ap.add_argument("--force", action="store_true", help="忽略同日闸门，强制重新采集")
    ap.add_argument("--check", action="store_true", help="只校验现有 updates.json，不探测/不写")
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = repo / OUT_REL
    now = datetime.now(CST)

    if args.workers < 1 or args.timeout < 1 or args.max_fresh < 0 or args.reserve < 0:
        print(json.dumps({"ok": False, "error": "参数非法（workers/timeout/max-fresh/reserve）"},
                         ensure_ascii=False, indent=2))
        return 1

    if args.check:
        if not out.is_file():
            print(json.dumps({"ok": False, "error": f"updates.json 不存在：{out}"},
                             ensure_ascii=False, indent=2))
            return 1
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            assert data.get("schema") == 1, "schema 不是 1"
            assert isinstance(data.get("repos"), dict), "repos 不是 dict"
            assert isinstance(data.get("recent"), list), "recent 不是 list"
        except (OSError, json.JSONDecodeError, AssertionError) as exc:
            print(json.dumps({"ok": False, "error": f"updates.json 校验失败：{exc}"},
                             ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"ok": True, "check_only": True,
                          "tracked": len(data["repos"]),
                          "recent": len(data["recent"]),
                          "summary": data.get("summary")}, ensure_ascii=False, indent=2))
        return 0

    try:
        repos, warnings = load_repos(repo / DATA_REL)
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    if not repos:
        print(json.dumps({"ok": False, "error": "dailyAI_* 中没有 GitHub 仓库可追踪"},
                         ensure_ascii=False, indent=2))
        return 1

    prev_repos, prev_payload = load_prev(out)
    if not args.force and is_same_day(prev_payload, now):
        print(json.dumps({
            "ok": True, "skipped": True, "reason": "already_ran_today",
            "output": str(OUT_REL), "generated_at": prev_payload.get("generated_at"),
            "tracked": len(prev_repos),
        }, ensure_ascii=False, indent=2))
        return 0
    if prev_payload.get("load_error"):
        warnings.append(f"旧快照读取失败，将重建基线：{prev_payload['load_error']}")

    state = {"stop": False, "fresh_used": 0, "remaining": None}
    lock = threading.Lock()
    results: dict[str, dict] = {}
    counts: dict[str, int] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe_one, s, prev_repos.get(s["key"]), state, lock,
                               args.max_fresh, args.reserve, args.timeout): s for s in repos}
        for fut in concurrent.futures.as_completed(futures):
            site = futures[fut]
            try:
                key, snap, status = fut.result()
            except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮整批
                warnings.append(f"{site['name']} 采集异常：{type(exc).__name__}: {exc}")
                key, snap, status = site["key"], None, "error"
            counts[status] = counts.get(status, 0) + 1
            if snap is not None:
                results[key] = snap
            if status in ("rate_limited", "rate_low"):
                warnings.append(f"{site['name']} 因 API 配额未采集，留待明日")
            elif status == "fresh_cap":
                warnings.append(f"{site['name']} 本日基线名额已满，留待明日")
            elif status == "not_found":
                warnings.append(f"{site['name']} GitHub 仓库 404（存活判定交 health.json）")
            elif status.startswith("network_") or status.startswith("http_"):
                warnings.append(f"{site['name']} 采集失败（{status}），保留旧快照")

    # 未采到但旧快照存在的，保留旧快照（不丢历史基线/变更）
    for key, old in prev_repos.items():
        if key not in results:
            results[key] = old

    tracked = sum(1 for s in results.values() if s.get("etag"))
    changed = counts.get("changed", 0)
    summary = {
        "total_repos": len(repos),
        "tracked": tracked,
        "checked_today": sum(v for k, v in counts.items() if k != "fresh_cap" and k != "stopped" and k != "rate_low"),
        "not_modified": counts.get("not_modified", 0),
        "changed": changed,
        "new_pushes": sum(1 for s in results.values() for c in s.get("changes", [])
                          if c.get("kind") == "push" and c.get("date") == now.date().isoformat()),
        "star_gains": sum(1 for s in results.values() for c in s.get("changes", [])
                          if c.get("kind") == "star" and c.get("date") == now.date().isoformat()),
        "baseline_added": counts.get("baseline", 0),
        "pending": counts.get("fresh_cap", 0) + counts.get("rate_low", 0) + counts.get("stopped", 0),
        "rate_remaining": state["remaining"],
    }
    payload = {
        "schema": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "source": "source/_data/webstack.yml :: dailyAI_* GitHub repos",
        "note": "每天采集 pushed_at/stars 并与上次快照对比；304 条件请求不计配额；"
                "首次采集仅建立基线不报变更；配额不足的仓库留待次日。",
        "summary": summary,
        "recent": build_recent(results, now),
        "repos": dict(sorted(results.items())),
        "warnings": warnings,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        check = json.loads(text)
        assert isinstance(check["recent"], list) and isinstance(check["repos"], dict)
    except (json.JSONDecodeError, AssertionError) as exc:
        print(json.dumps({"ok": False, "error": f"产物自检失败：{exc}"}, ensure_ascii=False, indent=2))
        return 1
    try:
        atomic_write(out, text)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"写入失败：{exc}"}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "ok": True, "output": str(OUT_REL), "bytes": out.stat().st_size,
        "summary": summary,
        "changed_names": [s["name"] for s in results.values()
                          if any(c.get("date") == now.date().isoformat() for c in s.get("changes", []))],
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
