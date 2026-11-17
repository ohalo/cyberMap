#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量在插件作者仓库创建 issue（告知其排名），并追踪发送状态。

三个子命令：
  scan     扫描目标仓库现有 issue，认领已手动发出的（去重），更新状态
  send     实际发送（需 GITHUB_TOKEN）；--dry-run 只打印计划不发送
  status   打印本地状态摘要

设计要点：
  * 幂等：body 内嵌 <!-- cybermap-outreach:v1 --> 标记，靠它 + 链接特征双重去重
  * 可追踪：每次尝试落 outreach/issue-log.jsonl，状态存 outreach/issue-status.json
  * 防滥用：随机间隔、每日上限、失败退避重试；被 GitHub 判重复(422)自动视为已存在
  * 可恢复：中断后重跑不重复发

用法：
  export GITHUB_TOKEN=ghp_xxx        # 或放到 outreach/.token 文件
  python3 scripts/send_issues.py scan --limit 90
  python3 scripts/send_issues.py send --limit 15 --dry-run
  python3 scripts/send_issues.py send --limit 15
  python3 scripts/send_issues.py status
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outreach")
DATA = os.path.join(OUT_DIR, "outreach-data.json")
STATUS = os.path.join(OUT_DIR, "issue-status.json")
LOG = os.path.join(OUT_DIR, "issue-log.jsonl")
BLOCKED = os.path.join(OUT_DIR, "blocked.json")
TOKEN_FILE = os.path.join(OUT_DIR, ".token")
MARK = "<!-- cybermap-outreach:v1 -->"
API = "https://api.github.com"

# 用于认领「手动发出」的 issue 的特征
SIGNATURES = ["cybermap.halo26812.eu.org", "daily ranking of AI agent plugins",
              "AI 插件每日榜单", "cybermap-outreach"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def api(path, token=None, method="GET", payload=None, timeout=30):
    url = path if path.startswith("http") else API + path
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "cybermap-outreach/1.0"}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body.strip() else {}), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"message": body[:300]}
        return e.code, parsed, dict(e.headers or {})
    except Exception as exc:
        return 0, {"message": "net:%s" % exc.__class__.__name__}, {}


def rate_info(headers):
    try:
        return {"limit": int(headers.get("X-RateLimit-Limit", 0)),
                "remaining": int(headers.get("X-RateLimit-Remaining", 0)),
                "reset": int(headers.get("X-RateLimit-Reset", 0))}
    except Exception:
        return {"limit": 0, "remaining": 0, "reset": 0}


def repo_path(rec):
    """推导 owner/repo —— GitHub issue 只能开在仓库层级，不能开在子目录。

    数据源字段有两套格式：
      top100.json      repo = https://github.com/owner/repo
      marketplace.json repo = owner/repo，另有 repo_path = 插件子目录（需丢弃）
    Tier B 部分条目 repo 为空，但 homepage 里可能带 github 链接，可作兜底。
    """
    repo = (rec.get("repo") or "").strip()
    if not repo:
        hp = (rec.get("homepage") or "").strip()
        if "github.com/" in hp:
            repo = "https://github.com/" + hp.split("github.com/", 1)[1]
    if not repo:
        return ""
    if repo.startswith("http"):
        p = repo.split("github.com/", 1)[-1]
    else:
        p = repo
    # 去掉查询串、锚点、.git 后缀
    p = p.split("?")[0].split("#")[0]
    if p.endswith(".git"):
        p = p[:-4]
    p = p.strip("/")
    parts = [x for x in p.split("/") if x]
    if len(parts) < 2:
        return ""
    return "%s/%s" % (parts[0], parts[1])


def build_body(rec):
    """Issue 正文：先给价值、明确不是推销、给退出机制、链接唯一。"""
    name = rec.get("display_name") or rec.get("owner")
    plugin = rec.get("plugin") or rec.get("owner")
    rank = rec.get("rank")
    stars = rec.get("stars")
    delta = rec.get("rank_delta")
    detail = rec.get("detail") or "https://cybermap.halo26812.eu.org/rank/"

    lines = []
    lines.append("Hi %s -" % name)
    lines.append("")
    lines.append("I keep a daily ranking of AI agent plugins across **Codex, Claude Code, dsh and WorkBuddy**.")
    if rank:
        lines.append("")
        lines.append("`%s` is currently **#%s** overall" % (plugin, rank))
        if delta is not None and delta > 0:
            lines.append("- It moved up **%d** %s since yesterday"
                         % (delta, "place" if delta == 1 else "places"))
        elif delta is not None and delta < 0:
            n = abs(delta)
            lines.append("- It moved down %d %s since yesterday"
                         % (n, "place" if n == 1 else "places"))
        if stars:
            lines.append("- %s stars on GitHub" % format(stars, ","))
    lines.append("")
    lines.append("Here is the board: %s" % detail)
    lines.append("")
    lines.append("No pitch and no marketing - you just found out where your plugin stands. If it is useful to you, feel free to share it with your users.")
    lines.append("")
    lines.append("If you would rather not be listed, just say so and I will take it down.")
    lines.append("")
    lines.append(MARK)
    return "\n".join(lines)


def build_title(rec):
    """标题格式必须与人工手发的保持一致，否则 GitHub 的重复检测不生效。

    人工手发实测格式：Your plugin ranked #1 on the AI plugin leaderboard
    """
    plugin = rec.get("plugin") or rec.get("owner")
    rank = rec.get("rank")
    if rank:
        return "Your plugin ranked #%s on the AI plugin leaderboard" % rank
    return "Added %s to the AI plugin leaderboard" % plugin


def looks_like_ours(title, body):
    hay = ((title or "") + "\n" + (body or "")).lower()
    if MARK in (body or ""):
        return True
    for sig in SIGNATURES:
        if sig.lower() in hay:
            return True
    return False


def load_blocked():
    """读取外联永久黑名单，返回 (owners_lower_set, repo_paths_lower_set)。"""
    data = load_json(BLOCKED, {}) or {}
    owners, repos = set(), set()
    for b in data.get("blocked", []):
        val = (b.get("value") or "").lower().strip()
        if not val:
            continue
        if b.get("scope") == "owner":
            owners.add(val)
        else:
            repos.add(val)
    return owners, repos


def is_blocked(rec, blocked=None):
    """某条目标是否命中永久黑名单（按 owner 或 owner/repo）。"""
    owners, repos = blocked if blocked is not None else load_blocked()
    owner = (rec.get("owner") or "").lower()
    rp = (rec.get("repo_path") or "").lower()
    return owner in owners or rp in repos


def load_targets(tier_filter="A", include_org=False):
    data = load_json(DATA, {})
    recs = data.get("records", [])
    out = []
    blocked = load_blocked()
    for r in recs:
        if tier_filter and r.get("tier") != tier_filter:
            continue
        if not include_org and r.get("is_org"):
            continue
        rp = repo_path(r)
        if not rp or "/" not in rp:
            continue
        r = dict(r)
        r["repo_path"] = rp
        if is_blocked(r, blocked):
            continue
        out.append(r)
    return out


def load_status():
    st = load_json(STATUS, {})
    st.setdefault("items", {})
    st.setdefault("daily_counts", {})
    return st


def save_status(st):
    save_json(STATUS, st)


def cmd_scan(args):
    token = get_token()
    print("扫描模式：%s" % ("带 token（可读私有/完整 issue 列表）" if token else "无 token（仅公开可见 issue，限流 60/h）"))
    targets = load_targets(args.tier, args.include_org)
    st = load_status()
    found = 0
    checked = 0
    for i, rec in enumerate(targets, 1):
        rp = rec["repo_path"]
        code, data, hdr = api("/repos/%s/issues?state=all&per_page=100" % rp, token=token)
        checked += 1
        if code != 200:
            print("  [%d/%d] %-28s 查询失败 http=%s %s" % (i, len(targets), rp, code, str(data.get("message"))[:60]))
            time.sleep(0.5)
            continue
        hit = None
        for it in (data if isinstance(data, list) else []):
            if "pull_request" in it:
                continue  # PR 不算
            if looks_like_ours(it.get("title"), it.get("body")):
                hit = it
                break
        key = rec["owner"].lower() + "|" + (rec.get("plugin") or "")
        if hit:
            found += 1
            st["items"][key] = {
                "owner": rec["owner"], "plugin": rec.get("plugin"), "repo_path": rp,
                "rank": rec.get("rank"), "status": "sent", "detected_by": "scan",
                "issue_number": hit.get("number"), "issue_url": hit.get("html_url"),
                "issue_state": hit.get("state"), "created_at": hit.get("created_at"),
                "first_seen": st["items"].get(key, {}).get("first_seen") or now_iso(),
                "last_checked": now_iso(),
            }
            print("  [%d/%d] %-28s ✓ 已存在 #%s (%s) %s" % (
                i, len(targets), rp, hit.get("number"), hit.get("state"), hit.get("html_url")))
        else:
            st["items"].setdefault(key, {
                "owner": rec["owner"], "plugin": rec.get("plugin"), "repo_path": rp,
                "rank": rec.get("rank"), "status": "pending", "first_seen": now_iso(),
                "last_checked": now_iso(),
            })
            st["items"][key]["last_checked"] = now_iso()
        if code == 200 and token:
            pass
        time.sleep(0.25 if token else 1.2)
    save_status(st)
    print()
    print("扫描完成：检查 %d 个仓库，认领到已存在 issue %d 条" % (checked, found))
    if not token:
        print("提示：无 token 时只能看到公开 issue 且限流 60/h。建议配 token 后重扫。")


def cmd_send(args):
    token = get_token()
    if not token and not args.dry_run:
        print("错误：未找到 GITHUB_TOKEN。GitHub 创建 issue 必须认证（匿名 API 返回 401）。")
        print("  获取方式：https://github.com/settings/tokens → Generate new token (classic)")
        print("  勾选 public_repo 权限即可 → export GITHUB_TOKEN=ghp_xxx")
        return 2
    if token:
        code, _, hdr = api("/rate_limit", token=token)
        ri = rate_info(hdr)
        print("认证正常 · 配额 %d/%d 剩余" % (ri["remaining"], ri["limit"]))
        if ri["limit"] <= 60:
            print("  注意：配额看起来是匿名额度，token 可能无效")

    targets = load_targets(args.tier, args.include_org)
    st = load_status()
    day = today_str()
    sent_today = st["daily_counts"].get(day, 0)
    if sent_today >= args.daily_limit:
        print("今日已发 %d 条，达到每日上限 %d，停止。如需提高用 --daily-limit。" % (sent_today, args.daily_limit))
        return 0

    # 过滤：已发 / 已在手发认领中
    queue = []
    skipped = 0
    for rec in targets:
        key = rec["owner"].lower() + "|" + (rec.get("plugin") or "")
        it = st["items"].get(key)
        if it and it.get("status") == "sent":
            skipped += 1
            continue
        if it and it.get("status") == "failed":
            queue.append((rec, key))
            continue
        queue.append((rec, key))

    # 排序：排名靠前优先，涨幅大的优先
    def prio(pair):
        rec = pair[0]
        return (rec.get("rank") or 999, -(rec.get("rank_delta") or 0))
    queue.sort(key=prio)

    batch = queue[:args.limit]
    print("待发 %d 条（跳过已完成 %d 条）· 本轮上限 %d · 今日已发 %d/%d"
          % (len(batch), skipped, args.limit, sent_today, args.daily_limit))
    print("-" * 72)

    if args.dry_run:
        for i, (rec, key) in enumerate(batch, 1):
            print("[%d] %-34s 排名=%-4s delta=%-4s stars=%s" % (
                i, rec["repo_path"], rec.get("rank"), rec.get("rank_delta"), rec.get("stars")))
            print("    标题: %s" % build_title(rec))
        print("-" * 72)
        print("DRY RUN：未发送任何内容。去掉 --dry-run 即实际发送。")
        return 0

    ok = fail = 0
    for i, (rec, key) in enumerate(batch, 1):
        if st["daily_counts"].get(day, 0) >= args.daily_limit:
            print("  达到每日上限，中断。")
            break
        title = build_title(rec)
        body = build_body(rec)
        # 发之前再查一次该仓库现有 issue —— 比依赖 GitHub 标题去重更可靠
        # （人工手发的措辞可能与脚本不完全一致）
        pre_code, pre_data, _ = api("/repos/%s/issues?state=all&per_page=100" % rec["repo_path"],
                                     token=token)
        if pre_code == 200 and isinstance(pre_data, list):
            dup = None
            for it in pre_data:
                if "pull_request" in it:
                    continue
                if looks_like_ours(it.get("title"), it.get("body")):
                    dup = it
                    break
            if dup:
                entry = st["items"].get(key, {})
                entry.update({"owner": rec["owner"], "plugin": rec.get("plugin"),
                              "repo_path": rec["repo_path"], "rank": rec.get("rank"),
                              "status": "sent", "detected_by": "precheck",
                              "issue_number": dup.get("number"), "issue_url": dup.get("html_url"),
                              "issue_state": dup.get("state"),
                              "sent_at": entry.get("sent_at") or now_iso(),
                              "last_checked": now_iso(),
                              "attempts": entry.get("attempts", 0)})
                st["items"][key] = entry
                save_status(st)
                ok += 1
                print("  [%d/%d] (approx) %-32s already exists #%s (caught before send, skipped)" % (
                    i, len(batch), rec["repo_path"], dup.get("number")))
                continue

        code, resp, hdr = api("/repos/%s/issues" % rec["repo_path"], token=token,
                              method="POST", payload={"title": title, "body": body})
        ri = rate_info(hdr)
        entry = st["items"].get(key, {})
        entry.update({"owner": rec["owner"], "plugin": rec.get("plugin"),
                      "repo_path": rec["repo_path"], "rank": rec.get("rank"),
                      "title": title, "last_checked": now_iso(),
                      "first_seen": entry.get("first_seen") or now_iso()})
        if code == 201:
            ok += 1
            st["daily_counts"][day] = st["daily_counts"].get(day, 0) + 1
            entry.update({"status": "sent", "issue_number": resp.get("number"),
                          "issue_url": resp.get("html_url"), "sent_at": now_iso(),
                          "http": 201, "attempts": entry.get("attempts", 0) + 1})
            print("  [%d/%d] ✓ %-30s #%s %s" % (i, len(batch), rec["repo_path"],
                                                 resp.get("number"), resp.get("html_url")))
        elif code in (422, 409):
            # GitHub 判定重复 —— 视为已存在
            ok += 1
            entry.update({"status": "sent", "issue_number": resp.get("number"),
                          "issue_url": resp.get("html_url"),
                          "sent_at": entry.get("sent_at") or now_iso(),
                          "http": code, "attempts": entry.get("attempts", 0) + 1,
                          "note": "github_marked_duplicate"})
            print("  [%d/%d] ≈ %-30s GitHub 判为重复（已存在）" % (i, len(batch), rec["repo_path"]))
        else:
            fail += 1
            msg = str(resp.get("message"))[:200]
            entry.update({"status": "failed", "http": code,
                          "error": msg,
                          "attempts": entry.get("attempts", 0) + 1,
                          "last_attempt_at": now_iso()})
            print("  [%d/%d] ✗ %-30s http=%s %s" % (i, len(batch), rec["repo_path"], code,
                                                     msg[:80]))
            # 403 是致命错误：继续发只会全部失败并浪费配额，立即中断
            # 两种成因需区分：
            #   a) Issues 写权限没开   → 改 fine-grained token 的 Issues 权限
            #   b) 写权限已开但类型受限 → fine-grained PAT 无法给第三方仓库提 issue，
            #                                必须换 classic token（public_repo scope）
            if code == 403 and "personal access token" in msg.lower():
                fine = (token or "").startswith("github_pat_")
                print()
                if fine:
                    print("  ⚠ 中断：token 无法给第三方仓库提 issue。")
                    print()
                    print("    判定：这是 fine-grained PAT 的【设计限制】，不是配置没改对。")
                    print("    GitHub 官方文档：只有 classic token 能给「非你所属」的公开仓库写。")
                    print("    你不是对方仓库的协作者，token 无法授予超出账号本身的权限。")
                    print()
                    print("    解法：新建 classic token")
                    print("      https://github.com/settings/tokens/new")
                    print("      → 勾选唯一一项 public_repo → 生成后写入 outreach/.token")
                    print()
                    print("    临时替代：outreach/manual-queue.html（不依赖 token）")
                else:
                    print("  ⚠ 中断：token 缺少 Issues 写权限。")
                    print("    编辑 https://github.com/settings/personal-access-tokens")
                    print("    → Repository permissions → Issues → Read and write")
                    print("    → Repository access → All repositories")
                st["items"][key] = entry
                save_status(st)
                append_log({"ts": now_iso(), "repo": rec["repo_path"], "http": code,
                            "error": "permission_denied", "aborted": True})
                print("-" * 72)
                print("本轮完成：成功 %d · 失败 %d（因权限中断）· 今日累计 %d"
                      % (ok, fail, st["daily_counts"].get(day, 0)))
                return 3
        append_log({"ts": now_iso(), "repo": rec["repo_path"], "plugin": rec.get("plugin"),
                     "http": code, "url": resp.get("html_url"), "title": title})
        st["items"][key] = entry
        save_status(st)

        if i < len(batch):
            delay = args.delay + random.uniform(0, args.jitter)
            time.sleep(delay)
        if ri["remaining"] == 0 and ri["reset"]:
            wait = max(0, ri["reset"] - int(time.time())) + 5
            print("  配额耗尽，等待 %d 秒…" % wait)
            time.sleep(wait)

    save_status(st)
    print("-" * 72)
    print("本轮完成：成功 %d · 失败 %d · 今日累计 %d" % (ok, fail, st["daily_counts"].get(day, 0)))
    print("状态文件: %s" % STATUS)
    print("日志文件: %s" % LOG)
    return 0


def cmd_status(args):
    st = load_status()
    items = st["items"]
    sent = [v for v in items.values() if v.get("status") == "sent"]
    failed = [v for v in items.values() if v.get("status") == "failed"]
    pending = [v for v in items.values() if v.get("status") != "sent" and v.get("status") != "failed"]
    print("状态总览")
    print("=" * 52)
    print("已发成功 : %d" % len(sent))
    print("失败     : %d" % len(failed))
    print("待发     : %d" % len(pending))
    print("累计尝试 : %d 次" % sum(v.get("attempts", 0) for v in items.values()))
    print()
    print("按日发送量:")
    for d in sorted(st.get("daily_counts", {}).keys()):
        print("  %s : %d 条" % (d, st["daily_counts"][d]))
    if failed:
        print()
        print("失败明细:")
        for v in failed:
            print("  %-30s http=%s %s" % (v.get("repo_path"), v.get("http"), (v.get("error") or "")[:70]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="批量给插件作者发 issue 并追踪状态")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--tier", default="A", choices=["A", "B", ""], help="目标层级，默认 A（有排名）")
        p.add_argument("--include-org", action="store_true", help="包含大厂组织方")
        p.add_argument("--limit", type=int, default=15)

    ps = sub.add_parser("scan", help="扫描现有 issue，认领已发出的")
    common(ps)

    pd = sub.add_parser("send", help="实际发送")
    common(pd)
    pd.add_argument("--dry-run", action="store_true", help="只打印计划，不发送")
    pd.add_argument("--delay", type=float, default=12.0, help="每条间隔秒数")
    pd.add_argument("--jitter", type=float, default=8.0, help="随机抖动秒数")
    pd.add_argument("--daily-limit", type=int, default=30, help="每日发送上限")

    pst = sub.add_parser("status", help="查看发送状态")
    pst.add_argument("--limit", type=int, default=0)

    args = ap.parse_args()
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "send":
        return cmd_send(args)
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
