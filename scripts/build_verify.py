#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 收录质量回执数据生成器（source/daily/verify.json）

把用户级 skill ``cybermap-daily`` 的 ``state/reports/verify-YYYY-MM-DD.json``
聚合为一份仓库内、可公开访问的机器可读证据数据，供 ``build_daily.py`` 在
每张卡片上渲染「已核验」徽章与页顶的「收录质量回执」。

为什么单独出一份数据
--------------------
验证报告在 skill 的 state 目录（不在仓库、Vercel 看不到），所以必须落成
仓库内静态产物。放在 ``daily/`` 下可直接复用已有的 ``skip_render: daily/**``，
不需要改 _config.yml；由 ``cybermap.py add`` 在每日收录成功后自动调用，
``commit`` 未指定 --files 时自动携带。

设计约束
--------
* 零新增依赖：只用标准库；不解析 YAML，日期尾注用正则计数。
* 只读：绝不改写 webstack.yml 或任何验证报告。
* 幂等：不写运行时间戳，键排序输出，重复运行字节一致；可用 --check 自检。
* 优雅降级：报告缺失/损坏时跳过并在 warnings 里说明，不抛异常阻断收录。
* 只聚合 ``verify-YYYY-MM-DD.json``，排除 ``verify-bulk-*``（那是常设分类的
  一次性批量补录证据，不属于每日收录）。

用法
----
    python scripts/build_verify.py --repo <repo>
    python scripts/build_verify.py --repo <repo> --check
    python scripts/build_verify.py --repo <repo> --state-dir /path/to/reports

退出码：0 成功；1 参数/写入错误（stdout 输出 JSON 诊断）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

DATA_REL = Path("source/_data/webstack.yml")
OUT_REL = Path("source/daily/verify.json")

# 报告文件名形如 verify-2026-11-16.json；verify-bulk-*.json 明确排除
REPORT_RE = re.compile(r"^verify-(\d{4}-\d{2}-\d{2})\.json$")
DATE_TAG_RE = re.compile(r"[·•]\s*(\d{4}-\d{2}-\d{2})\s*收录")
DEFAULT_STATE_DIR = Path.home() / ".workbuddy/skills/cybermap-daily/state/reports"


def norm(url: str) -> str:
    """与 cybermap.py 的 norm() 保持完全一致，保证徽章能按 URL 命中证据。"""
    from urllib.parse import urlparse
    raw = (url or "").strip().rstrip(",;'\"")
    p = urlparse(raw if "://" in raw else "https://" + raw)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = (p.path or "/").rstrip("/").lower() or "/"
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host}{path}"


def collect_reports(state_dir: Path) -> tuple[dict, dict, list[str]]:
    """返回 (按日期的漏斗, 按规范化 URL 的证据, 警告列表)。"""
    days: dict[str, dict] = {}
    evidence: dict[str, dict] = {}
    warnings: list[str] = []

    if not state_dir.is_dir():
        return days, evidence, [f"验证报告目录不存在：{state_dir}"]

    files = sorted(p for p in state_dir.iterdir() if REPORT_RE.match(p.name))
    if not files:
        return days, evidence, [f"未找到 verify-YYYY-MM-DD.json 报告：{state_dir}"]

    for path in files:
        day = REPORT_RE.match(path.name).group(1)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name} 读取/解析失败，已跳过：{exc}")
            continue
        results = report.get("results") or []
        if not isinstance(results, list):
            warnings.append(f"{path.name} 的 results 不是列表，已跳过")
            continue

        verdicts = Counter(r.get("verdict", "unknown") for r in results if isinstance(r, dict))
        days[day] = {
            "checked": len(results),
            "pass": verdicts.get("pass", 0),
            "review": verdicts.get("review", 0),
            "fail": verdicts.get("fail", 0),
            "rejected": [
                {
                    "url": r.get("url", ""),
                    "verdict": r.get("verdict", "unknown"),
                    "reason": "；".join(r.get("reasons") or []) or "；".join(r.get("warnings") or []),
                }
                for r in results
                if isinstance(r, dict) and r.get("verdict") != "pass"
            ],
        }

        for r in results:
            if not isinstance(r, dict) or r.get("verdict") != "pass":
                continue
            ev = r.get("evidence") or {}
            gh = ev.get("github") or {}
            key = r.get("normalized") or norm(r.get("url", ""))
            if not key:
                continue
            # 同一 URL 出现在多天报告时，保留日期最新的一份
            if key in evidence and evidence[key]["date"] > day:
                continue
            evidence[key] = {
                "date": day,
                "verdict": "pass",
                "http_status": ev.get("http_status"),
                "title": (ev.get("title") or "")[:180],
                "stars": gh.get("stars"),
                "pushed_at": gh.get("pushed_at"),
                "license": gh.get("license"),
                "ai_hits": len(ev.get("ai_keywords") or []),
                "ai_keywords": (ev.get("ai_keywords") or [])[:8],
                "checked_at": ev.get("checked_at"),
            }
    return days, evidence, warnings


def count_added(repo: Path, days: dict) -> dict[str, int]:
    """从 webstack.yml 的日期尾注统计每天实际收录数（pass 数 ≠ 收录数）。"""
    path = repo / DATA_REL
    if not path.is_file():
        return {d: 0 for d in days}
    counts = Counter(DATE_TAG_RE.findall(path.read_text(encoding="utf-8")))
    return {d: counts.get(d, 0) for d in days}


def render(days: dict, evidence: dict, added: dict, warnings: list[str]) -> str:
    for d, stat in days.items():
        stat["added"] = added.get(d, 0)
    totals = {
        "days": len(days),
        "checked": sum(s["checked"] for s in days.values()),
        "pass": sum(s["pass"] for s in days.values()),
        "review": sum(s["review"] for s in days.values()),
        "fail": sum(s["fail"] for s in days.values()),
        "added": sum(s["added"] for s in days.values()),
        "verified_sites": len(evidence),
    }
    payload = {
        "schema": 1,
        "source": "cybermap-daily/state/reports/verify-YYYY-MM-DD.json",
        "days": dict(sorted(days.items())),
        "evidence": dict(sorted(evidence.items())),
        "totals": totals,
        "warnings": warnings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="聚合验证报告为 /daily/ 收录质量回执数据")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                    help="cyberMap 仓库根目录")
    ap.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                    help="验证报告目录（默认 skill 的 state/reports）")
    ap.add_argument("--check", action="store_true", help="只校验数据，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    if not (repo / DATA_REL).is_file():
        print(json.dumps({"ok": False, "error": f"找不到数据文件 {repo / DATA_REL}"},
                         ensure_ascii=False, indent=2))
        return 1

    days, evidence, warnings = collect_reports(args.state_dir.resolve())
    if not days or not evidence:
        print(json.dumps({"ok": False, "error": "没有可用的验证报告", "warnings": warnings},
                         ensure_ascii=False, indent=2))
        return 1

    added = count_added(repo, days)
    text = render(days, evidence, added, warnings)

    # 回读自检：JSON 可解析、结构完整、键数量一致
    try:
        check = json.loads(text)
        if len(check["evidence"]) != len(evidence) or len(check["days"]) != len(days):
            raise ValueError("聚合结果自检不通过")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"产物自检失败：{exc}"}, ensure_ascii=False, indent=2))
        return 1

    result = {
        "ok": True,
        "days": len(days),
        "evidence": len(evidence),
        "totals": check["totals"],
        "warnings": warnings,
        "output": str(OUT_REL),
    }
    if args.check:
        print(json.dumps({**result, "check_only": True}, ensure_ascii=False, indent=2))
        return 0

    try:
        atomic_write(repo / OUT_REL, text)
        json.loads((repo / OUT_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"写入失败：{exc}"}, ensure_ascii=False, indent=2))
        return 1

    result["bytes"] = (repo / OUT_REL).stat().st_size
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
