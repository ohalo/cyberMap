#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 每日收录周报生成器（weekly digest）

复用现有数据资产，零新采集、零新增依赖：
  * source/_data/webstack.yml —— 带「· YYYY-MM-DD 收录」尾注的条目，按 ISO 周聚合
  * source/daily/verify.json  —— 每日收录漏斗（候选 → pass → added）
  * source/daily/updates.json —— 上游变更雷达 recent（涨星/新提交 → 活跃项目 Top10）

产出静态站点 ``source/weekly/index.html`` 与独立 RSS ``source/weekly/feed.xml``：
  * 页面：本周新增 N 站 + 收录项目清单（含分类/方向标签）+ 验证漏斗 +
    最活跃项目 Top10 + 方向分布；滚动展示最近若干周，可回看。
  * RSS：每个 ISO 周一个 item（标题含站点数），guid 为 cybermap-weekly-<周一日期>，
    与 /daily/ 各 feed 完全隔离，不串味。

设计约束（与 build_daily.py 一致）
  * 只用标准库 + 已有 PyYAML；复用 build_daily 的 infer_tags / norm_url / DATE_TAG_RE /
    CATEGORY_LABELS / short_stars，标签规则只有一处定义，零漂移。
  * 页面自包含内联 CSS/JS，浅/深主题靠共享 cookie ``night=1`` 与首页同步。
  * 只读数据文件、绝不改写 webstack.yml；幂等可重跑（不写生成时间戳）。
  * 原子写入（临时文件 + os.replace）； weekly/** 由 _config.yml 的 skip_render 原样发布。

用法
----
    python scripts/build_weekly.py [--repo /path/to/cyberMap]
    python scripts/build_weekly.py --check     # 只校验数据，不写文件
退出码：0 成功；1 数据/参数错误。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"缺少 PyYAML：{exc}"}, ensure_ascii=False))
    sys.exit(1)

# 复用 build_daily 的单一数据源规则（同目录，脚本直跑时路径天然可用）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_daily import (  # noqa: E402
    CATEGORY_LABELS, CST, DATE_TAG_RE, short_stars,
    infer_tags, norm_url,
)

SITE_URL_DEFAULT = "https://cybermap.halo26812.eu.org"
DATA_REL = Path("source/_data/webstack.yml")
VERIFY_REL = Path("source/daily/verify.json")
UPDATES_REL = Path("source/daily/updates.json")
OUT_REL = Path("source/weekly")
WEEKS_TO_SHOW = 8          # 页面滚动展示最近 8 周
TOP_ACTIVE = 10            # 活跃项目 Top10


# ---------------------------------------------------------------- 内联样式
CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --wk-font:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --wk-bg:#f4f7fc;--wk-surface:rgba(255,255,255,.86);--wk-solid:#fff;
  --wk-border:rgba(15,23,42,.09);--wk-border-strong:rgba(15,23,42,.15);
  --wk-text:#1b2436;--wk-soft:#45526b;--wk-muted:#6b7790;
  --wk-accent:#4f46e5;--wk-accent-2:#06b6d4;--wk-chip:rgba(79,70,229,.09);
  --wk-good:#16a34a;--wk-good-bg:rgba(22,163,74,.10);
  --wk-warn:#d97706;--wk-glow:rgba(56,189,248,.20);
  --wk-shadow:0 4px 18px rgba(19,32,62,.055),0 1px 2px rgba(19,32,62,.04);
}
body.night{
  --wk-bg:#080d1a;--wk-surface:rgba(17,25,44,.78);--wk-solid:#121a2e;
  --wk-border:rgba(148,163,184,.16);--wk-border-strong:rgba(148,163,184,.28);
  --wk-text:#e8edf8;--wk-soft:#b6c2da;--wk-muted:#aebbd6;
  --wk-accent:#8b8bff;--wk-accent-2:#22d3ee;--wk-chip:rgba(139,139,255,.14);
  --wk-good:#39ff88;--wk-good-bg:rgba(57,255,136,.10);--wk-warn:#fbbf24;
  --wk-glow:rgba(34,211,238,.16);
  --wk-shadow:0 6px 24px rgba(0,0,0,.32);
}
body{margin:0;background:var(--wk-bg);color:var(--wk-text);font-family:var(--wk-font);
  -webkit-font-smoothing:antialiased;line-height:1.6}
a{color:var(--wk-accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 72px}
.hero{position:relative;overflow:hidden;border:1px solid var(--wk-border);
  border-radius:18px;background:var(--wk-surface);padding:30px 32px;box-shadow:var(--wk-shadow)}
.hero::after{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;
  border-radius:50%;background:radial-gradient(circle,var(--wk-glow),transparent 70%);pointer-events:none}
.eyebrow{font-size:11px;letter-spacing:.16em;color:var(--wk-accent-2);font-weight:700;text-transform:uppercase}
.hero h1{margin:8px 0 4px;font-size:30px;line-height:1.25}
.hero h1 b{color:var(--wk-accent)}
.hero p{margin:6px 0 0;color:var(--wk-soft);font-size:14px}
.hero .nav{margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:999px;
  border:1px solid var(--wk-border-strong);color:var(--wk-soft);font-size:12.5px;background:var(--wk-solid)}
.pill.primary{border-color:var(--wk-accent);color:var(--wk-accent);font-weight:600}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}
.stat{border:1px solid var(--wk-border);border-radius:14px;background:var(--wk-surface);padding:16px 18px}
.stat .n{font-size:26px;font-weight:800;color:var(--wk-accent)}
.stat .l{font-size:12px;color:var(--wk-muted);margin-top:2px}
.grid{display:grid;grid-template-columns:1.5fr 1fr;gap:20px;margin-top:8px}
.panel{border:1px solid var(--wk-border);border-radius:16px;background:var(--wk-surface);padding:20px 22px;margin-bottom:20px}
.panel h2{margin:0 0 14px;font-size:16px;display:flex;align-items:center;gap:8px}
.panel h2 .dot{width:8px;height:8px;border-radius:50%;background:var(--wk-accent-2)}
.week-block{border-top:1px solid var(--wk-border);padding-top:16px;margin-top:16px}
.week-block:first-child{border-top:0;padding-top:0;margin-top:0}
.week-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.week-head h3{margin:0;font-size:15px}
.week-head .meta{font-size:12px;color:var(--wk-muted)}
.funnel{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px}
.funnel span{font-size:11.5px;padding:4px 10px;border-radius:8px;background:var(--wk-chip);color:var(--wk-soft)}
.funnel b{color:var(--wk-accent)}
.sites{list-style:none;padding:0;margin:12px 0 0;display:grid;gap:9px}
.sites li{border:1px solid var(--wk-border);border-radius:11px;padding:11px 13px;background:var(--wk-solid)}
.sites .row1{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.sites .nm{font-weight:650;font-size:14px}
.sites .cat{font-size:11px;color:var(--wk-accent-2)}
.sites .ds{font-size:12.5px;color:var(--wk-soft);margin-top:3px}
.tags{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
.tag{font-size:10.5px;padding:2px 8px;border-radius:6px;background:var(--wk-chip);color:var(--wk-accent)}
.rank{list-style:none;padding:0;margin:0;counter-reset:r}
.rank li{counter-increment:r;display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--wk-border)}
.rank li:last-child{border-bottom:0}
.rank li::before{content:counter(r);width:22px;height:22px;flex:0 0 22px;display:grid;place-items:center;
  border-radius:6px;background:var(--wk-chip);color:var(--wk-accent);font-size:11px;font-weight:700}
.rank .rn{flex:1;min-width:0;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rank .delta{font-size:12px;color:var(--wk-good);font-weight:650}
.bars{margin:0}
.bar{margin:9px 0}
.bar .bl{display:flex;justify-content:space-between;font-size:12px;color:var(--wk-soft);margin-bottom:4px}
.bar .track{height:7px;border-radius:6px;background:var(--wk-chip);overflow:hidden}
.bar .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--wk-accent),var(--wk-accent-2))}
.empty{color:var(--wk-muted);font-size:13px;padding:8px 0}
.foot{text-align:center;color:var(--wk-muted);font-size:11.5px;margin-top:28px}
.switch{cursor:pointer;user-select:none}
@media(max-width:820px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.hero h1{font-size:24px}}
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


# ---------------------------------------------------------------- 数据加载
def load_entries(data_file: Path) -> list[dict]:
    """读取带日期尾注的条目；标签/分类名复用 build_daily 的规则。"""
    if not data_file.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_file}")
    data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("webstack.yml 顶层不是映射")
    out = []
    for cat, (label, _short) in CATEGORY_LABELS.items():
        block = data.get(cat) or []
        if not isinstance(block, list):
            continue
        for raw in block:
            if not isinstance(raw, dict):
                continue
            name, url = raw.get("name"), raw.get("url")
            if not name or not url:
                continue
            desc = str(raw.get("description") or "").strip()
            m = DATE_TAG_RE.search(desc)
            if not m:
                continue
            day = m.group(1)
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                continue
            clean = DATE_TAG_RE.sub("", desc).strip().rstrip("·").strip()
            out.append({
                "name": str(name), "url": str(url), "category": cat,
                "label": label, "description": clean, "day": day,
                "tags": infer_tags(str(name), clean),
            })
    return out


def load_json(path: Path) -> tuple[dict, str | None]:
    if not path.is_file():
        return {}, f"{path.name} 缺失，相关模块降级"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data, None) if isinstance(data, dict) else ({}, f"{path.name} 结构异常")
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"{path.name} 读取失败：{exc}"


def iso_week_start(day: date) -> date:
    """返回该日期所在 ISO 周的周一。"""
    return day - timedelta(days=day.weekday())


def group_by_week(entries: list[dict]) -> list[tuple[date, list[dict]]]:
    buckets: dict[date, list[dict]] = {}
    for item in entries:
        d = datetime.strptime(item["day"], "%Y-%m-%d").date()
        buckets.setdefault(iso_week_start(d), []).append(item)
    return [(w, sorted(buckets[w], key=lambda i: i["day"], reverse=True))
            for w in sorted(buckets, reverse=True)]


def week_funnel(days: dict, week_start: date) -> dict:
    """汇总某一周内各日的 verify 漏斗。"""
    total = {"checked": 0, "pass": 0, "review": 0, "fail": 0, "added": 0}
    for i in range(7):
        day = (week_start + timedelta(days=i)).isoformat()
        record = (days or {}).get(day)
        if isinstance(record, dict):
            for k in total:
                try:
                    total[k] += int(record.get(k) or 0)
                except (TypeError, ValueError):
                    pass
    return total


def active_top10(updates: dict) -> list[dict]:
    """从雷达 recent 取涨星最多的前 N 个项目（无涨星则用有提交的）。"""
    recent = [r for r in (updates.get("recent") or []) if isinstance(r, dict)]
    recent.sort(key=lambda r: (int(r.get("star_delta") or 0), bool(r.get("has_push"))), reverse=True)
    return [r for r in recent if (int(r.get("star_delta") or 0) or r.get("has_push"))][:TOP_ACTIVE]


# ---------------------------------------------------------------- HTML
def week_label(week_start: date) -> str:
    end = week_start + timedelta(days=6)
    tag = "本周" if iso_week_start(date.today()) == week_start else ""
    return f"{week_start.isoformat()} ~ {end.isoformat()}" + (f" · {tag}" if tag else "")


def render_html(weeks, verify: dict, updates: dict, site_url: str, today: date) -> str:
    total_sites = sum(len(items) for _w, items in weeks)
    current = weeks[0][1] if weeks else []
    top = active_top10(updates)
    # 方向分布基于本周条目
    tag_count: dict[str, int] = {}
    for item in current:
        for t in item["tags"]:
            tag_count[t] = tag_count.get(t, 0) + 1
    tags_sorted = sorted(tag_count.items(), key=lambda kv: -kv[1])
    max_tag = tags_sorted[0][1] if tags_sorted else 1

    days = verify.get("days") or {}
    recent_total = len(updates.get("recent") or [])

    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cyberMap · 每日收录周报</title>
<meta name="description" content="cyberMap 每周 AI 站点收录摘要：本周新增、验证漏斗、最活跃项目与方向分布。">
<link rel="alternate" type="application/rss+xml" title="cyberMap 周报" href="/weekly/feed.xml">
<script>document.cookie.indexOf('night=1')>-1&&document.documentElement.classList.add('night');</script>
<style>{CSS}</style></head><body>
<div class="wrap">
<section class="hero">
  <div class="eyebrow">CYBERMAP / WEEKLY DIGEST</div>
  <h1>每日收录 <b>周报</b></h1>
  <p>每周一聚合一周的 AI 站点收录：本周新增、验证质量、最活跃项目与方向分布。数据来自每日收录的真实核验记录。</p>
  <div class="nav">
    <a class="pill primary" href="/weekly/feed.xml">订阅周报 RSS</a>
    <a class="pill" href="/daily/">每日速递</a>
    <a class="pill" href="/">返回导航首页</a>
    <span class="pill switch" onclick="t()">切换主题</span>
  </div>
</section>
<div class="stats">
  <div class="stat"><div class="n">{len(current)}</div><div class="l">本周新增站点</div></div>
  <div class="stat"><div class="n">{total_sites}</div><div class="l">累计 · 近 {len(weeks)} 周</div></div>
  <div class="stat"><div class="n">{len(top)}</div><div class="l">活跃项目 · 雷达</div></div>
  <div class="stat"><div class="n">{recent_total}</div><div class="l">近期变更记录</div></div>
</div>
<div class="grid">
<section class="panel">
  <h2><span class="dot"></span>按周收录回顾</h2>"""]

    if not weeks:
        parts.append('<div class="empty">暂无带日期尾注的收录，等待每日收录写入后自动汇总。</div>')
    for week_start, items in weeks[:WEEKS_TO_SHOW]:
        funnel = week_funnel(days, week_start)
        parts.append(f"""<div class="week-block">
  <div class="week-head"><h3>{esc(week_label(week_start))}</h3>
    <span class="meta">{len(items)} 个站点</span></div>
  <div class="funnel">
    <span>候选 <b>{funnel['checked']}</b></span>
    <span>通过 <b>{funnel['pass']}</b></span>
    <span>收录 <b>{funnel['added']}</b></span>
    <span>复核 <b>{funnel['review']}</b></span>
    <span>未过 <b>{funnel['fail']}</b></span>
  </div>
  <ul class="sites">""")
        for item in items:
            tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in item["tags"])
            parts.append(f"""<li>
      <div class="row1"><a class="nm" href="{esc(item['url'])}" target="_blank" rel="noopener">{esc(item['name'])}</a>
        <span class="cat">{esc(item['label'])}</span></div>
      <div class="ds">{esc(item['description'])}</div>
      <div class="tags">{tag_html}</div>
    </li>""")
        parts.append("</ul></div>")

    parts.append("""</section>
<aside>
<section class="panel">
  <h2><span class="dot"></span>最活跃项目 Top10</h2>""")
    if top:
        parts.append('<ol class="rank">')
        for r in top:
            delta = int(r.get("star_delta") or 0)
            name = r.get("name") or norm_url(r.get("url") or "")
            parts.append(f"""<li>
        <a class="rn" href="{esc(r.get('url') or '#')}" target="_blank" rel="noopener">{esc(name)}</a>
        <span class="delta">{('+' + str(delta) + ' 星') if delta else ('新提交' if r.get('has_push') else '')}</span>
      </li>""")
        parts.append("</ol>")
    else:
        parts.append('<div class="empty">上游雷达尚无近期变更，基线建立后自动显示。</div>')
    parts.append(f"""</section>
<section class="panel">
  <h2><span class="dot"></span>本周方向分布</h2>""")
    if tags_sorted:
        parts.append('<div class="bars">')
        for tag, count in tags_sorted:
            pct = int(count * 100 / max_tag)
            parts.append(f"""<div class="bar"><div class="bl"><span>{esc(tag)}</span><span>{count}</span></div>
        <div class="track"><div class="fill" style="width:{pct}%"></div></div></div>""")
        parts.append("</div>")
    else:
        parts.append('<div class="empty">本周暂无收录，方向分布待更新。</div>')
    parts.append(f"""</section>
</aside>
</div>
<div class="foot">数据来源：每日收录核验记录 · 上游变更雷达 · 每周一自动聚合 · {esc(site_url)}/weekly/</div>
</div>
<script>
function t(){{var n=document.body.classList.toggle('night');document.cookie='night='+(n?1:0)+';path=/;max-age=31536000';location.reload();}}
if(document.documentElement.classList.contains('night'))document.body.classList.add('night');
</script>
</body></html>""")
    return "".join(parts)


def build_feed(weeks, site_url: str) -> bytes:
    root = site_url.rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "cyberMap · 每日收录周报"
    ET.SubElement(ch, "link").text = f"{root}/weekly/"
    ET.SubElement(ch, "description").text = "cyberMap 每周核验收录的 AI 站点摘要，每周一期。"
    ET.SubElement(ch, "language").text = "zh-CN"
    ET.SubElement(ch, "generator").text = "cybermap-daily/build_weekly.py"
    ET.SubElement(ch, "ttl").text = "10080"  # 一周（分钟）
    for week_start, items in weeks:
        if not items:
            continue
        item = ET.SubElement(ch, "item")
        ET.SubElement(item, "title").text = (
            f"AI 收录周报 · {week_start.isoformat()}（{len(items)} 个站点）"
        )
        ET.SubElement(item, "link").text = f"{root}/weekly/"
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = (
            f"cybermap-weekly-{week_start.isoformat()}"
        )
        ET.SubElement(item, "pubDate").text = format_datetime(
            datetime.combine(week_start, time(0, 0), tzinfo=CST)
        )
        lines = [f'{i["name"]}［{i["label"]}］{i["description"]} — {i["url"]}' for i in items]
        ET.SubElement(item, "description").text = "\n".join(lines)
        ET.SubElement(item, "category").text = "AI 周报"
    if hasattr(ET, "indent"):
        ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    here = Path(__file__).resolve()
    default_repo = Path(os.environ.get("CYBERMAP_REPO", here.parent.parent))
    ap = argparse.ArgumentParser(description="生成 cyberMap 每日收录周报与 RSS")
    ap.add_argument("--repo", type=Path, default=default_repo, help="cyberMap 仓库根目录")
    ap.add_argument("--out", type=Path, default=None, help="输出目录（默认 <repo>/source/weekly）")
    ap.add_argument("--site-url", default=SITE_URL_DEFAULT, help="站点根 URL（用于 RSS 绝对链接）")
    ap.add_argument("--check", action="store_true", help="只校验数据，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    out_dir = (args.out or (repo / OUT_REL)).resolve()
    site_url = args.site_url.rstrip("/")
    today = date.today()

    try:
        entries = load_entries(repo / DATA_REL)
    except (FileNotFoundError, ValueError) as exc:
        fail(str(exc))
    verify, v_warn = load_json(repo / VERIFY_REL)
    updates, u_warn = load_json(repo / UPDATES_REL)
    warnings = [w for w in (v_warn, u_warn) if w]
    weeks = group_by_week(entries)
    top = active_top10(updates)

    summary = {
        "ok": True,
        "dated_sites": len(entries),
        "weeks": len(weeks),
        "current_week_start": iso_week_start(today).isoformat(),
        "current_week_sites": len(weeks[0][1]) if weeks else 0,
        "active_top": len(top),
        "feed_items": len([1 for _w, items in weeks if items]),
        "warnings": warnings,
    }
    if args.check:
        print(json.dumps({**summary, "check_only": True}, ensure_ascii=False, indent=2))
        return

    html_text = render_html(weeks, verify, updates, site_url, today)
    feed = build_feed(weeks, site_url)
    root = ET.fromstring(feed)
    if root.tag != "rss":
        fail("周报 RSS 根节点不是 rss，未写入")
    if "<html" not in html_text or 'class="hero"' not in html_text:
        fail("周报 HTML 结构自检未通过，未写入")
    if 'href="/weekly/feed.xml"' not in html_text:
        fail("周报页面缺少 RSS 订阅入口，未写入")
    try:
        atomic_write(out_dir / "index.html", html_text.encode("utf-8"))
        atomic_write(out_dir / "feed.xml", feed)
    except OSError as exc:
        fail(f"写入周报产物失败：{exc}")
    summary["outputs"] = {
        "index": str(out_dir / "index.html"),
        "feed": str(out_dir / "feed.xml"),
        "feed_items": len(root.findall("./channel/item")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
