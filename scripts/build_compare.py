#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 同类项目对比矩阵生成器（/compare/）

把全站导航中「同分类 + 同方向标签」的站点自动聚成对比组，一张表并排看：
stars、近 24h 涨星、最近推送、健康态、收录日期，组内最高星标的列打 NEON 高亮。

  * ``source/compare/index.html``  /compare/ 对比矩阵页（内联 CSS/JS，自包含）

设计约束（与 build_data.py / build_weekly.py 同口径）
----------------------------------------------------
* 零新增依赖、零新增网络探测：只读 webstack.yml 与已生成的
  verify.json / health.json / updates.json，stars 一律以既有证据为准。
* 数据聚合直接 ``import build_data.collect``，字段与 sites.json 永远一致；
  标签 / URL 归一化经 build_data 复用 build_daily 规则。
* 只读数据源：绝不改写 webstack.yml 及任何 daily/data 产物。
* 幂等：产物不写生成时间戳，同样输入产出字节一致。
* 优雅降级：updates.json 缺失照常产出，只是雷达列显示「—」。
* 赛博态遵循设计稿 05 号板（仅 body.night 生效，经典态零改动），
  顶栏接 /css/cm-unified-header.css 的 cm-u-* 契约。
* 靠 _config.yml 的 ``skip_render: compare/**`` 原样发布，不改主题。

由用户级 skill `cybermap-daily` 的 add 在每日收录成功后自动调用（置于
build_weekly 之后）；也可手动：

    python scripts/build_compare.py --repo <repo>
    python scripts/build_compare.py --repo <repo> --check

退出码：0 成功；1 数据/参数/写入错误（stdout 输出 JSON 诊断）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from build_data import collect as collect_sites  # 复用聚合，字段同 sites.json
    from build_daily import SITE_URL_DEFAULT, norm_url
except Exception as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"无法复用 build_data/build_daily 规则：{exc}"},
                     ensure_ascii=False))
    sys.exit(1)

SITE_URL = SITE_URL_DEFAULT.rstrip("/")
UPDATES_REL = Path("source/daily/updates.json")
OUT_DIR = Path("source/compare")
INDEX_REL = OUT_DIR / "index.html"

SCHEMA = 1
MAX_GROUPS = 12          # 首页最多展示的对比组数
MAX_SITES_PER_GROUP = 4  # 每组最多并排展示的站点数
NEW_WINDOW_DAYS = 30     # 收录日期在最新日期 30 天内的打上 NEW 标记


# ---------------------------------------------------------------- 数据准备
def load_radar(repo: Path) -> tuple[dict, dict, list[str]]:
    """读 updates.json，返回 (recent_by_url, radar_by_url)；缺失时降级为空。

    recent_by_url: norm_url -> 最近一次观测 {stars, star_delta, pushed_at, ...}
    radar_by_url : norm_url -> 累计近 7 天 star 变化 {star7, pushed} （从 changes 汇总）
    """
    path = repo / UPDATES_REL
    if not path.is_file():
        return {}, {}, ["上游雷达 updates.json 缺失，雷达列降级为 —"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, {}, [f"updates.json 读取失败，雷达列降级为 —：{exc}"]

    recent: dict[str, dict] = {}
    for item in data.get("recent") or []:
        if isinstance(item, dict) and item.get("url"):
            recent[norm_url(item["url"])] = item

    radar: dict[str, dict] = {}
    today = datetime.now().date()
    for key, rec in (data.get("repos") or {}).items():
        if not isinstance(rec, dict):
            continue
        star7 = 0
        pushed = None
        for ch in rec.get("changes") or []:
            if not isinstance(ch, dict):
                continue
            d = ch.get("date")
            if ch.get("kind") == "star" and ch.get("delta"):
                try:
                    if (today - date.fromisoformat(str(d))).days <= 7:
                        star7 += int(ch["delta"])
                except (TypeError, ValueError):
                    pass
            if ch.get("kind") == "push" and ch.get("to"):
                if pushed is None or str(ch["to"]) > str(pushed):
                    pushed = str(ch["to"])
        # radar 键与 recent 键统一用 norm_url 后的站点 url；repos 键是
        # github.com/owner/repo 小写，直接再 norm 一次兜住两种索引。
        u = norm_url("https://" + str(key))
        radar[u] = {"star7": star7, "pushed": pushed}
    return recent, radar, []


def parse_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def build_groups(sites: list[dict], recent: dict, radar: dict) -> tuple[list[dict], list[str]]:
    """按 (category, 主标签) 聚合；组内 >=2 站点成组，排序截断后返回。"""
    warnings: list[str] = []
    buckets: dict[tuple[str, str], list[dict]] = {}
    no_tag = 0
    for s in sites:
        tags = s.get("tags") or []
        if not tags:
            no_tag += 1
            continue
        buckets.setdefault((s["category"], tags[0]), []).append(s)
    if no_tag:
        warnings.append(f"{no_tag} 条站点未命中任何方向标签，未参与对比聚合")

    ref_day = max((d for d in (parse_date(s.get("date")) for s in sites) if d),
                  default=None)
    groups: list[dict] = []
    for (cat, tag), members in buckets.items():
        if len(members) < 2:
            continue
        enriched = []
        for s in members:
            u = norm_url(s["url"])
            obs = recent.get(u) or {}
            rad = radar.get(u) or {}
            stars = None
            if isinstance(s.get("verified"), dict) and s["verified"].get("stars"):
                stars = s["verified"]["stars"]
            if stars is None and obs.get("stars"):
                stars = obs["stars"]
            day = parse_date(s.get("date"))
            enriched.append({
                "name": s["name"],
                "url": s["url"],
                "description": s.get("description") or "",
                "health": s.get("health"),
                "date": s.get("date"),
                "stars": stars,
                "star24": obs.get("star_delta"),
                "pushed_at": obs.get("pushed_at") or rad.get("pushed"),
                "star7": rad.get("star7") or None,
                "is_new": bool(day and ref_day and (ref_day - day) <= timedelta(days=NEW_WINDOW_DAYS)),
            })
        # 组内排序：stars 降序（None 垫底），同星按名称保证稳定序
        enriched.sort(key=lambda x: (-(x["stars"] or 0), x["name"]))
        verified_cnt = sum(1 for x in enriched if x["stars"] is not None)
        top_star = max((x["stars"] or 0) for x in enriched)
        latest = max((x["date"] or "" for x in enriched), default="")
        groups.append({
            "category": cat,
            "category_name": members[0].get("category_name") or cat,
            "group_name": members[0].get("group") or "",
            "tag": tag,
            "sites": enriched[:MAX_SITES_PER_GROUP],
            "total": len(enriched),
            "verified_cnt": verified_cnt,
            "top_star": top_star,
            "latest": latest,
            "has_new": any(x["is_new"] for x in enriched[:MAX_SITES_PER_GROUP]),
        })

    # 组间排序：新收录优先 → 带证据数 → 组内最高星 → 分类/标签稳定序
    groups.sort(key=lambda g: (not g["has_new"], -g["verified_cnt"], -g["top_star"],
                               g["category"], g["tag"]))
    return groups[:MAX_GROUPS], warnings


# ---------------------------------------------------------------- 页面渲染
CM_HEX = ('<svg viewBox="0 0 32 32" aria-hidden="true">'
          '<path d="M16 2 28 9v14l-12 7L4 23V9z" fill="none" stroke="currentColor" stroke-width="2"/>'
          '<path d="M16 8 23 12v8l-7 4-7-4v-8z" fill="currentColor" opacity=".25"/></svg>')


def unified_nav(active: str = "/compare/") -> tuple[str, str]:
    links = [('/', '首页'), ('/daily/', '每日速递'), ('/rank/', '插件榜'),
             ('/data/', '开放数据'), ('/compare/', '对比矩阵'), ('/tools/', '自研工具'),
             ('/about/', '关于')]
    parts = []
    for href, label in links:
        cls = ' class="is-active"' if href == active else ''
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    brand = ('<a class="brand cm-u-brand cm-u-only" href="/" aria-label="cyberMap 首页">'
             + CM_HEX + '<b><i>cyber</i> MAP</b></a>')
    nav = '<nav class="cm-u-links cm-u-only" aria-label="全站导航">' + ''.join(parts) + '</nav>'
    return brand, nav


UNIFIED_BRAND, UNIFIED_LINKS = unified_nav()

PAGE_CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
 --bg:#f4f7fc;--surface:rgba(255,255,255,.86);--solid:#fff;
 --border:rgba(15,23,42,.09);--border2:rgba(15,23,42,.15);
 --text:#1b2436;--soft:#45526b;--muted:#6b7790;
 --accent:#4f46e5;--accent2:#06b6d4;--chip:rgba(79,70,229,.09);
 --glow-a:rgba(56,189,248,.20);--glow-b:rgba(167,139,250,.18);
 --shadow:0 4px 18px rgba(19,32,62,.055);--code:#0f1830;
 --online:#16a34a;--idle:#d97706;--down:#dc2626;
}
body.night{
 /* 设计稿 05 号板：VOID/SURFACE/EDGE/NEON-C/NEON-M/ONLINE/IDLE/TEXT */
 --bg:#05070b;--surface:rgba(11,18,27,.82);--solid:#0b121b;
 --border:rgba(18,48,63,.9);--border2:#12303f;
 --text:#e6f5ff;--soft:#b7c9df;--muted:#8ba0bd;
 --accent:#00e5ff;--accent2:#ff2ea6;--chip:rgba(0,229,255,.12);
 --glow-a:rgba(0,229,255,.13);--glow-b:rgba(255,46,166,.11);
 --shadow:0 8px 28px rgba(0,0,0,.45);--code:#050912;
 --online:#39ff88;--idle:#ffb020;--down:#ff5c5c;
}
html{scroll-behavior:smooth}
body{margin:0;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;
 color:var(--text);background:var(--bg);
 background-image:radial-gradient(900px 600px at 8% -8%,var(--glow-a),transparent 62%),
 radial-gradient(800px 560px at 96% 4%,var(--glow-b),transparent 60%);
 background-attachment:fixed;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.wrap{max-width:980px;margin:0 auto;padding:0 clamp(16px,4vw,40px)}
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;
 padding:12px clamp(16px,4vw,40px);background:var(--surface);
 border-bottom:1px solid var(--border);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.top .brand{font-weight:600;font-size:15px}
.top .spacer{flex:1}
.btn{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border-radius:9px;
 border:1px solid var(--border2);background:var(--solid);font-size:13px;color:var(--soft);cursor:pointer}
.btn:hover{color:var(--accent);border-color:var(--accent)}
.hero{padding:56px 0 26px}
.hero h1{margin:0 0 12px;font-size:30px;font-weight:600;letter-spacing:-.02em}
.hero p{margin:0;color:var(--soft);font-size:15px;max-width:760px}
.tag{display:inline-block;padding:3px 10px;border-radius:20px;background:var(--chip);
 color:var(--accent);font-size:12px;margin-bottom:14px}
.rail{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 34px}
.rail a{padding:5px 11px;border-radius:8px;border:1px solid var(--border2);
 background:var(--solid);font-size:12px;color:var(--soft)}
.rail a:hover{color:var(--accent);border-color:var(--accent)}
.cmp-group{background:var(--surface);border:1px solid var(--border);border-radius:14px;
 box-shadow:var(--shadow);margin:0 0 30px;overflow:hidden}
.cmp-head{padding:18px 20px 12px;border-bottom:1px solid var(--border)}
.cmp-head .meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.cmp-head .cat{font-size:12px;color:var(--accent);background:var(--chip);padding:2px 9px;border-radius:14px}
.cmp-head .cnt{font-size:12px;color:var(--muted)}
.cmp-head h2{margin:8px 0 0;font-size:18px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:11px 16px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:500;background:var(--chip);white-space:nowrap;font-size:12px}
tr:last-child td{border-bottom:0}
td.name{min-width:200px}
td.name a{font-weight:600}
td.name a:hover{color:var(--accent)}
td.name .desc{display:block;color:var(--soft);font-size:12px;margin-top:3px;max-width:340px}
.num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.best .num,.best a{color:var(--accent);font-weight:700}
.up{color:var(--online)}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;margin-left:6px;
 border:1px solid var(--border2)}
.badge.new{color:var(--accent2);border-color:var(--accent2)}
.badge.ok{color:var(--online)} .badge.down{color:var(--down)} .badge.un{color:var(--idle)}
.foot{padding:30px 0 50px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
@media(max-width:720px){th,td{padding:9px 10px}td.name .desc{max-width:180px}}
/* ---- 设计稿 05 号板：对比矩阵赛博态（仅 body.night 生效，经典态零改动） ---- */
.dy-cmp-design-only{display:none!important}
body.night .dy-cmp-design-only{display:flex!important}
body.night::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;
 background:repeating-linear-gradient(0deg,rgba(0,0,0,.12) 0 1px,transparent 1px 3px);opacity:.42}
body.night .top{top:28px;background:rgba(11,18,27,.9);border-bottom:1px solid #12303f}
body.night .top .brand,body.night .top .spacer{display:none}
body.night .top .brand.cm-u-brand{display:inline-flex!important}
body.night .btn,body.night .rail a{border-radius:2px;border-color:#12303f;background:rgba(11,18,27,.86);
 font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px;letter-spacing:.05em}
body.night .btn:hover,body.night .rail a:hover{color:var(--accent2);border-color:var(--accent2)}
body.night .wrap{max-width:1180px}
body.night .tag{border-radius:2px;font-family:"CM Mono","JetBrains Mono",monospace;
 font-size:10px;letter-spacing:.1em;color:var(--accent)}
body.night .hero h1{font-family:"CM Orbitron",sans-serif;font-weight:900;
 font-size:clamp(30px,3.4vw,44px);letter-spacing:-.02em}
body.night .hero p{font-size:13px;color:var(--muted)}
body.night .cmp-group{border-radius:3px;border-color:#12303f}
body.night .cmp-head h2{font-family:"CM Chakra","Chakra Petch",sans-serif;font-weight:600;letter-spacing:.02em}
body.night .cmp-head .cat{border-radius:2px;font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.08em}
body.night th{font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px;letter-spacing:.06em;color:var(--accent)}
body.night td.name a{font-family:"CM Chakra","Chakra Petch",sans-serif;font-weight:600}
body.night .best .num,body.night .best a{color:var(--accent)}
body.night .badge{border-radius:2px;font-family:"CM Mono","JetBrains Mono",monospace}
@media (prefers-reduced-motion:reduce){body.night::after{background:none}}
"""


def health_badge(h: str | None) -> str:
    if h == "ok":
        return '<span class="badge ok">OK</span>'
    if h == "down":
        return '<span class="badge down">DOWN</span>'
    if h == "unverified":
        return '<span class="badge un">未复检</span>'
    return "—"


def fmt_stars(v) -> str:
    if v is None:
        return "—"
    return f"{v:,}"


def fmt_delta(v) -> str:
    if not v:
        return "—"
    cls = "up" if v > 0 else ""
    sign = "+" if v > 0 else ""
    return f'<span class="num {cls}">{sign}{v}</span>'


def fmt_pushed(v) -> str:
    if not v:
        return "—"
    return str(v)[:10]


def render_html(groups: list[dict], stats: dict) -> str:
    e = html.escape
    rail = "".join(
        f'<a href="#cmp-{i:02d}">{e(g["category_name"])} · {e(g["tag"])}</a>'
        for i, g in enumerate(groups))

    secs = []
    for i, g in enumerate(groups):
        top = g["top_star"]
        rows = []
        for s in g["sites"]:
            best = ' class="best"' if (s["stars"] is not None and s["stars"] == top and top > 0) else ""
            newb = '<span class="badge new">NEW</span>' if s["is_new"] else ""
            rows.append(f"""        <tr{best}>
          <td class="name"><a href="{e(s['url'])}" target="_blank" rel="noopener">{e(s['name'])}</a>{newb}<span class="desc">{e(s['description'])}</span></td>
          <td class="num">{fmt_stars(s['stars'])}</td>
          <td>{fmt_delta(s['star24'])}</td>
          <td>{fmt_delta(s['star7'])}</td>
          <td class="num">{fmt_pushed(s['pushed_at'])}</td>
          <td>{health_badge(s['health'])}</td>
          <td class="num">{e(s['date'] or '—')}</td>
        </tr>""")
        more = (f'<span class="cnt">组内共 {g["total"]} 个，展示前 {len(g["sites"])} 个</span>'
                if g["total"] > len(g["sites"]) else "")
        secs.append(f"""  <section class="cmp-group" id="cmp-{i:02d}">
    <div class="cmp-head">
      <div class="meta"><span class="cat">{e(g['group_name'])} / {e(g['category_name'])}</span><span class="cnt">方向：{e(g['tag'])}</span>{more}</div>
      <h2>{e(g['category_name'])} × {e(g['tag'])}</h2>
    </div>
    <table>
      <thead><tr><th>站点</th><th>Stars</th><th>24h 涨星</th><th>7d 涨星</th><th>最近推送</th><th>健康</th><th>收录</th></tr></thead>
      <tbody>
{chr(10).join(rows)}
      </tbody>
    </table>
  </section>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>同类项目对比矩阵 · cyberMap</title>
<meta name="description" content="cyberMap 同类 AI 项目横向对比：同分类同方向的站点并排看 stars、涨星、推送、健康与收录日期，数据随每日收录自动重建。">
<meta name="theme-color" content="#4f46e5">
<link rel="icon" href="/favicon.ico">
<link rel="canonical" href="{SITE_URL}/compare/">
<style>@font-face{{font-family:"CM Orbitron";src:url("/fonts/cm-orbitron-latin.woff2") format("woff2");font-style:normal;font-weight:400 900;font-display:swap}}@font-face{{font-family:"CM Chakra";src:url("/fonts/cm-chakra-600-latin.woff2") format("woff2");font-style:normal;font-weight:600;font-display:swap}}@font-face{{font-family:"CM Mono";src:url("/fonts/cm-jetbrains-latin.woff2") format("woff2");font-style:normal;font-weight:400 700;font-display:swap}}</style>
<script>try{{if(document.cookie.split('; ').indexOf('night=1')>=0)document.documentElement.classList.add('night')}}catch(e){{}}</script>
<style>{PAGE_CSS}</style><link rel="stylesheet" href="/css/cm-unified-header.css">
</head>
<body>
<div class="dy-cmp-design-only cm-u-hud cm-u-only" id="dyCmpHud"><b>SECTION 05 // COMPARISON MATRIX</b><span class="cm-u-hud-right">{stats['groups']} GROUPS · {stats['cmp_sites']} NODES</span></div>
<header class="top cm-u-nav">
  <div class="brand">cyberMap / compare</div>
  {UNIFIED_BRAND}
  {UNIFIED_LINKS}
  <div class="spacer"></div>
  <span class="cm-u-util">
  <a class="btn" href="/">返回首页</a>
  <button class="btn" id="themeBtn" type="button">切换主题</button>
  </span>
</header>
<div class="wrap">
  <section class="hero">
    <div class="tag">Comparison matrix · 每天随收录自动重建</div>
    <h1>同类项目对比矩阵</h1>
    <p>同分类、同方向标签的 AI 项目自动聚成对比组，一张表并排看 {stats['groups']} 组 {stats['cmp_sites']} 个节点：stars、近 24h / 7d 涨星、最近推送、健康态与收录日期。数据全部来自站内既有验证证据与上游雷达，零额外探测。</p>
    <nav class="rail" aria-label="对比组导航">{rail}</nav>
  </section>
{chr(10).join(secs)}
  <section class="foot">
    对比组由 cyberMap 每日收录流水线自动生成 · stars 以 api.github.com 实探证据为准 · 涨星与推送来自上游变更雷达 updates.json · 分类与标签同站内导航一致。
  </section>
</div>
<script>
(function(){{
  function isNight(){{return document.cookie.split('; ').indexOf('night=1')>=0}}
  function apply(){{document.body.classList.toggle('night',isNight())}}
  apply();
  document.getElementById('themeBtn').addEventListener('click',function(){{
    document.cookie='night='+(isNight()?'0':'1')+';path=/;max-age=31536000';
    apply();
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 校验 / 写入
def validate(groups: list[dict], html_text: str) -> list[str]:
    if not groups:
        raise ValueError("没有任何对比组（同分类同标签 >=2 的聚合为空）")
    n = sum(len(g["sites"]) for g in groups)
    for marker in ("COMPARISON MATRIX", "同类项目对比矩阵", "24h 涨星", "7d 涨星"):
        if marker not in html_text:
            raise ValueError(f"index.html 缺少关键内容：{marker}")
    for i in range(len(groups)):
        if f'id="cmp-{i:02d}"' not in html_text:
            raise ValueError(f"index.html 缺少对比组锚点 cmp-{i:02d}")
    if html_text.count("<table") != len(groups):
        raise ValueError("对比组数量与表格数量不符")
    return [f"schema={SCHEMA}", f"groups={len(groups)}", f"cmp_sites={n}"]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 cyberMap /compare/ 同类项目对比矩阵")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                    help="cyberMap 仓库根目录")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    try:
        payload, warnings = collect_sites(repo)
        recent, radar, radar_warn = load_radar(repo)
        warnings = list(warnings) + radar_warn
        groups, agg_warn = build_groups(payload["sites"], recent, radar)
        warnings = warnings + agg_warn
        stats = {"groups": len(groups),
                 "cmp_sites": sum(len(g["sites"]) for g in groups),
                 "all_sites": payload["counts"]["sites"]}
        html_text = render_html(groups, stats)
        checks = validate(groups, html_text)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    result = {
        "ok": True,
        "stats": stats,
        "top_groups": [f"{g['category_name']}×{g['tag']}({len(g['sites'])})" for g in groups[:5]],
        "checks": checks,
        "warnings": warnings,
        "outputs": [str(INDEX_REL)],
    }
    if args.check:
        print(json.dumps({**result, "check_only": True}, ensure_ascii=False, indent=2))
        return 0

    try:
        atomic_write(repo / INDEX_REL, html_text)
        written = (repo / INDEX_REL).read_text(encoding="utf-8")
        if written != html_text:
            raise ValueError("回读内容与校验副本不一致")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"写入失败：{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    result["bytes"] = {"index.html": len(html_text.encode("utf-8"))}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
