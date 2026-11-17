#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集插件作者对我们外联 Issue 的回复 —— 幂等、可反复运行。

数据源：
    outreach/issue-status.json 中 status=sent 且带 issue_number 的条目（我们真正发出的 Issue）
输出：
    outreach/replies.json —— 每个 Issue 的最新评论（作者回复），供看板与网站使用

设计要点：
  · 只读 GitHub 公开 Issue 评论，不写任何 issue、不改发送状态。
  · 逐个 GET /repos/{owner}/{repo}/issues/{n}/comments；401/403/限流/网络失败时
    保留该条目上次的旧数据（fetch_code 记下错误码），绝不因一次失败清空已有回复。
  · 合并而非覆盖：以 issue_url 为键，用本次结果刷新成功的条目，失败的沿用旧条目。
  · token 只用于抬高限额；无 token 也能跑（匿名 60 次/小时）。

用法：
    python3 scripts/collect_replies.py
    python3 scripts/collect_replies.py --limit 100      # 最多采集 N 个 Issue
    python3 scripts/collect_replies.py --only-with-new   # 只看本次新增回复的条目
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outreach")
STATUS = os.path.join(OUT_DIR, "issue-status.json")
REPLIES = os.path.join(OUT_DIR, "replies.json")
TOKEN_FILE = os.path.join(OUT_DIR, ".token")
API = "https://api.github.com"

# 认领为「作者/维护者回复」的用户类型（其余比如 bot 也保留，但看板会区分）
BOT_SUFFIX = "[bot]"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def api(path, token=None, timeout=25):
    url = path if path.startswith("http") else API + path
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "cybermap-reply-collector/1.0"}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    req = urllib.request.Request(url, headers=headers, method="GET")
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


def remaining_from(headers):
    try:
        return int(headers.get("X-RateLimit-Remaining", 0))
    except Exception:
        return 0


def sent_issues(status):
    """从 issue-status.json 取出我们真正发出去的 Issue 列表。"""
    items = status.get("items", {}) if isinstance(status, dict) else {}
    out = []
    for key, rec in items.items():
        if rec.get("status") != "sent":
            continue
        num = rec.get("issue_number")
        repo = (rec.get("repo_path") or "").strip()  # 已是 owner/repo
        if not num or not repo or "/" not in repo:
            continue
        out.append({
            "owner": rec.get("owner") or repo.split("/", 1)[0],
            "plugin": rec.get("plugin") or repo.split("/", 1)[1],
            "repo_path": repo,
            "rank": rec.get("rank"),
            "issue_number": int(num),
            "issue_url": rec.get("issue_url")
                         or "https://github.com/%s/issues/%s" % (repo, num),
        })
    out.sort(key=lambda r: (r.get("rank") if isinstance(r.get("rank"), int) else 9999,
                            r["repo_path"]))
    return out


def normalize_comment(c):
    u = (c.get("user") or {})
    return {
        "author": u.get("login") or "",
        "author_type": u.get("type") or "",
        "body": c.get("body") or "",
        "created_at": c.get("created_at") or "",
        "html_url": c.get("html_url") or "",
        "issue_author": (c.get("_issue_author") or ""),
    }


def collect(limit, token, pause):
    status = load_json(STATUS, {})
    prev = load_json(REPLIES, {})
    prev_by_url = {}
    for it in prev.get("items", []):
        key = it.get("issue_url")
        if key:
            prev_by_url[key] = it

    targets = sent_issues(status)
    if limit and limit > 0:
        targets = targets[:limit]

    results = []
    new_reply_issues = 0
    remaining = None
    for i, t in enumerate(targets, 1):
        url = t["issue_url"]
        old = prev_by_url.get(url, {})
        # 首个评论页（100 条足够覆盖外联 Issue 的讨论）
        path = "/repos/%s/%s/issues/%s/comments?per_page=100" % (
            urllib.parse.quote(t["owner"], safe=""),
            urllib.parse.quote(t["plugin"], safe=""),
            t["issue_number"])
        code, data, headers = api(path, token=token)
        remaining = remaining_from(headers) if headers else remaining

        if code == 200 and isinstance(data, list):
            comments = [normalize_comment(c) for c in data]
            fetch_code = 200
            # 认领 Issue 本身的状态（能拿到就带上）
            state = old.get("issue_state", "")
        else:
            # 失败：沿用旧数据，绝不伪造/清空
            comments = old.get("comments", [])
            fetch_code = code
            state = old.get("issue_state", "")
            print("  [!] %-38s fetch failed code=%s (kept %d old comments)" % (
                t["repo_path"], code, len(comments)), file=sys.stderr)

        old_count = len(old.get("comments", []))
        if len(comments) > old_count:
            new_reply_issues += 1

        results.append({
            "owner": t["owner"],
            "plugin": t["plugin"],
            "repo_path": t["repo_path"],
            "rank": t.get("rank"),
            "issue_number": t["issue_number"],
            "issue_url": url,
            "issue_state": state,
            "comment_count": len(comments),
            "comments": comments,
            "fetch_code": fetch_code,
        })
        if i % 10 == 0 or i == len(targets):
            print("  [%d/%d] collected, remaining=%s" % (i, len(targets), remaining))
        if pause and i < len(targets):
            time.sleep(pause)

    # 合并：本次 sent 目标用新结果覆盖；prev 里不在本次 targets 的条目（被拉黑的、
    # 手工补录的明确拒绝声明等）原样保留，绝不因一次采集把它们抹掉。
    target_urls = {t["issue_url"] for t in targets}
    kept = [it for it in prev.get("items", [])
            if it.get("issue_url") not in target_urls]
    merged = results + kept

    with_replies = sum(1 for r in merged if r["comments"])
    out = {
        "fetched_at": now_iso(),
        "total_issues": len(merged),
        "issues_with_replies": with_replies,
        "new_reply_issues": new_reply_issues,
        "items": merged,
    }
    save_json(REPLIES, out)
    print("\nDONE: %d collected + %d kept, %d with replies, %d with new comments this run -> %s" % (
        len(results), len(kept), with_replies, new_reply_issues, REPLIES))
    return out


def main():
    ap = argparse.ArgumentParser(description="采集插件作者对已发 Issue 的回复")
    ap.add_argument("--limit", type=int, default=0, help="最多采集 N 个 Issue（0=全部）")
    ap.add_argument("--pause", type=float, default=0.15, help="每次请求间隔秒（默认 0.15）")
    ap.add_argument("--only-with-new", action="store_true",
                    help="运行后仅打印本次新增回复的 Issue")
    args = ap.parse_args()

    token = get_token()
    print("token: %s" % ("yes" if token else "no (anonymous, 60 req/h)"))
    out = collect(args.limit, token, args.pause)

    if args.only_with_new:
        for it in out["items"]:
            if it.get("fetch_code") == 200 and it["comments"]:
                print("  %-32s #%s — %d comment(s)" % (
                    it["repo_path"], it["issue_number"], len(it["comments"])))


if __name__ == "__main__":
    main()
