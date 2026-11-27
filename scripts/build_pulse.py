#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 项目脉搏时间机器（source/daily/stars-history.json）

把上游变更雷达每天采到的真实 stars 观测点归档成时间序列，供 /daily/ 渲染
每个项目的迷你增长曲线与「近 30 天涨星榜」。**零新增网络探测**：只读
source/daily/updates.json，不访问 GitHub、不改写 webstack.yml。

数据严谨性（用户重视数据可信）
--------------------------------
* 只使用真实观测值：updates.json 里 ``changes[kind=star]`` 的 ``{date, to}``
  是采集器当天实探到的 stars；最近一次 ``last_checked`` 日期 + ``stars``
  也是实探值。绝不用「当前 stars 倒推每天」的方式编造历史。
* 冷启动诚实：某仓库只有 1 个点时归入 ``baseline_only``，不进涨星榜、曲线
  显示为单点基线；数组不足 2 点不画趋势线。随着每日采集自然积累。
* 幂等：产物里的 ``generated_at`` 直接取 updates.json 的时间戳，同日连跑
  字节一致（md5 相同），可安全重跑。原子写入，自检不通过不落盘。
* 优雅降级：updates.json 缺失 / 损坏 / 无仓库数据时退出码 0 并输出空产物，
  不阻断每日收录；build_daily 读不到本产物时也不渲染脉搏模块。

用法
----
    python scripts/build_pulse.py --repo <repo>
    python scripts/build_pulse.py --repo <repo> --check
    python scripts/build_pulse.py --repo <repo> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UPDATES_REL = Path("source/daily/updates.json")
OUT_REL = Path("source/daily/stars-history.json")
SITE_URL_DEFAULT = "https://cybermap.halo26812.eu.org"
CST = timezone(timedelta(hours=8))
WINDOW_DAYS = 30          # 近 30 天窗口（月度涨星）
MAX_POINTS_PER_REPO = 40  # 每仓库最多保留的点数，防止产物膨胀
MAX_RANKING = 12          # 涨星榜最多输出的仓库数（页面只展示前若干）


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_history(updates: dict, site_url: str) -> dict:
    """从 updates.json 的真实观测点构建 stars 时间序列。"""
    repos = updates.get("repos") or {}
    generated = updates.get("generated_at") or ""
    base_date = generated[:10] or datetime.now(CST).date().isoformat()
    try:
        cutoff = (date.fromisoformat(base_date) - timedelta(days=WINDOW_DAYS)).isoformat()
    except ValueError:
        cutoff = "1970-01-01"

    entries: dict[str, dict] = {}
    all_dates: set[str] = set()
    for key, snap in sorted(repos.items()):
        if not isinstance(snap, dict):
            continue
        points: dict[str, int] = {}
        # ① 采集器记录的涨星观测：{date, kind="star", to=当天实探 stars}
        for ch in snap.get("changes") or []:
            if not isinstance(ch, dict) or ch.get("kind") != "star":
                continue
            d, to = ch.get("date"), ch.get("to")
            if not isinstance(d, str) or d < cutoff or not isinstance(to, int) or to < 0:
                continue
            points[d] = to  # 同一天多条时取最后一条（当天最新观测）
        # ② 最近一次实探值，日期取 last_checked（不是产物生成日，避免误标）
        stars, checked = snap.get("stars"), (snap.get("last_checked") or "")[:10]
        if isinstance(stars, int) and stars >= 0 and checked and checked >= cutoff:
            points[checked] = stars

        if not points:
            continue
        seq = [{"date": d, "stars": points[d]} for d in sorted(points)][-MAX_POINTS_PER_REPO:]
        all_dates.update(p["date"] for p in seq)
        first, latest = seq[0]["stars"], seq[-1]["stars"]
        entries[key] = {
            "name": snap.get("name") or key,
            "url": snap.get("url") or "",
            "category": snap.get("category") or "",
            "points": seq,
            "latest": latest,
            "delta": latest - first,
            "days": len(seq),
            "span": [seq[0]["date"], seq[-1]["date"]],
        }

    with_trend = [k for k, r in entries.items() if r["days"] >= 2 and r["delta"] > 0]
    ranking = sorted(with_trend, key=lambda k: (-entries[k]["delta"], k))[:MAX_RANKING]
    summary = {
        "repos": len(entries),
        "with_trend": len(with_trend),
        "baseline_only": sum(1 for r in entries.values() if r["days"] < 2),
        "observed_dates": len(all_dates),
        "total_points": sum(r["days"] for r in entries.values()),
        "window_days": WINDOW_DAYS,
    }
    return {
        "schema": 1,
        "site": site_url.rstrip("/"),
        "source": "source/daily/updates.json :: repos[*].changes(kind=star) + last_checked/stars",
        "generated_at": generated,
        "note": ("只归档采集器真实观测到的 stars（changes 中的 star 点与最近一次探测值）；"
                 "同一天去重取最后观测值；单点项目仅建基线不进涨星榜；不伪造任何历史。"),
        "summary": summary,
        "ranking": ranking,
        "repos": dict(sorted(entries.items())),
    }


def main() -> int:
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser(description="归档项目 stars 快照，生成项目脉搏时间机器数据")
    ap.add_argument("--repo", type=Path, default=here.parent.parent)
    ap.add_argument("--out", type=Path, default=None, help="输出目录（默认 <repo>/source/daily）")
    ap.add_argument("--site-url", default=SITE_URL_DEFAULT)
    ap.add_argument("--check", action="store_true", help="只校验现有产物，不重新生成")
    args = ap.parse_args()

    repo = args.repo.resolve()
    updates_path = repo / UPDATES_REL
    out_dir = (args.out or (repo / OUT_REL).parent).resolve()
    out_path = out_dir / OUT_REL.name

    if args.check:
        if not out_path.is_file():
            print(json.dumps({"ok": False, "error": f"产物不存在：{out_path}"}, ensure_ascii=False))
            return 1
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            assert data.get("schema") == 1, "schema 不是 1"
            assert isinstance(data.get("repos"), dict), "repos 不是 dict"
            assert isinstance(data.get("ranking"), list), "ranking 不是 list"
            assert isinstance(data.get("summary"), dict), "summary 不是 dict"
            for key, r in data["repos"].items():
                assert isinstance(r.get("points"), list) and r["points"], f"{key} points 为空"
                assert r["points"][0]["date"] <= r["points"][-1]["date"], f"{key} 日期未升序"
        except (OSError, json.JSONDecodeError, AssertionError, KeyError, TypeError) as exc:
            print(json.dumps({"ok": False, "error": f"stars-history.json 校验失败：{exc}"},
                             ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "check_only": True,
                          "repos": len(data["repos"]), "ranking": len(data["ranking"]),
                          "summary": data["summary"]}, ensure_ascii=False, indent=2))
        return 0

    updates: dict = {}
    load_warnings: list[str] = []
    if updates_path.is_file():
        try:
            loaded = json.loads(updates_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("repos"), dict):
                updates = loaded
            else:
                load_warnings.append("updates.json 结构不完整，已生成空产物")
        except (OSError, json.JSONDecodeError) as exc:
            load_warnings.append(f"updates.json 读取失败，已生成空产物：{exc}")
    else:
        load_warnings.append("updates.json 不存在，已生成空产物")

    payload = build_history(updates, args.site_url)
    payload["warnings"] = load_warnings
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        check = json.loads(text)
        assert check["schema"] == 1
        assert isinstance(check["repos"], dict) and isinstance(check["ranking"], list)
        for key, r in check["repos"].items():
            assert r["points"] == sorted(r["points"], key=lambda p: p["date"]), f"{key} 未升序"
    except (json.JSONDecodeError, AssertionError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": f"产物自检失败：{exc}"}, ensure_ascii=False))
        return 1
    try:
        atomic_write(out_path, text)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"写入失败：{exc}"}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "ok": True,
        "output": str(out_path.relative_to(repo)) if out_path.is_relative_to(repo) else str(out_path),
        "bytes": out_path.stat().st_size,
        "summary": payload["summary"],
        "top": [payload["repos"][k]["name"] for k in payload["ranking"][:8]],
        "warnings": load_warnings,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
