#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 每日 AI 速递生成器

读取 ``source/_data/webstack.yml`` 里 ``dailyAI_oss`` / ``dailyAI_tool`` /
``dailyAI_model`` 三个分类，按描述尾注「· YYYY-MM-DD 收录」聚合成时间轴页面
``source/daily/index.html``，并输出 RSS 2.0 订阅源 ``source/daily/feed.xml``。

设计约束
--------
* 零新增依赖：只用标准库 + 仓库已有的 PyYAML。
* 页面自包含：内联 CSS / JS，不加载主题资源。浅/深主题通过共享 cookie
  ``night=1`` 与首页保持一致，在任一页面切换都会同步。
* 只读数据文件：绝不改写 webstack.yml；同样输入产出同样输出，可反复运行。
* 与 ``/rank/`` 同构：产物是纯静态文件，靠 _config.yml 的
  ``skip_render: ['rank/**', 'daily/**']`` 原样发布。
* 原子写入：先写同目录临时文件再 os.replace，避免留下半成品。

用法
----
    python scripts/build_daily.py [--repo /path/to/cyberMap]
                                  [--site-url https://cybermap.halo26812.eu.org]
    python scripts/build_daily.py --check     # 只校验数据，不写文件

退出码：0 成功；1 数据/参数错误（stdout 输出 JSON 诊断）。
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


SITE_URL_DEFAULT = "https://cybermap.halo26812.eu.org"
DATA_REL = Path("source/_data/webstack.yml")
OUT_REL = Path("source/daily")

# 分类 -> (中文标签, 短名)。顺序决定同一天内卡片的展示顺序。
CATEGORY_LABELS = OrderedDict([
    ("dailyAI_oss", ("开源项目", "oss")),
    ("dailyAI_tool", ("工具官网", "tool")),
    ("dailyAI_model", ("模型框架", "model")),
])

# 形如「 · 2026-11-15 收录」，允许尾部空白；只匹配结尾，避免误伤正文里的日期。
DATE_TAG_RE = re.compile(r"[·•]\s*(\d{4}-\d{2}-\d{2})\s*收录\s*$")
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 内联资源
# 用独立字符串常量而不是 f-string 模板，避免 CSS 里的大量花括号需要转义。
CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --dy-font:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --dy-bg:#f4f7fc;
  --dy-surface:rgba(255,255,255,.86);
  --dy-solid:#fff;
  --dy-border:rgba(15,23,42,.09);
  --dy-border-strong:rgba(15,23,42,.15);
  --dy-text:#1b2436;
  --dy-soft:#45526b;
  --dy-muted:#6b7790;
  --dy-accent:#4f46e5;
  --dy-accent-2:#06b6d4;
  --dy-chip:rgba(79,70,229,.09);
  --dy-icon-bg:rgba(241,245,251,.9);
  --dy-shadow:0 4px 18px rgba(19,32,62,.055),0 1px 2px rgba(19,32,62,.04);
  --dy-shadow-hover:0 16px 34px rgba(38,52,92,.15),0 3px 8px rgba(38,52,92,.06);
  --dy-glow-a:rgba(56,189,248,.20);
  --dy-glow-b:rgba(167,139,250,.18);
}
body.night{
  --dy-bg:#080d1a;
  --dy-surface:rgba(17,25,44,.78);
  --dy-solid:#121a2e;
  --dy-border:rgba(148,163,184,.16);
  --dy-border-strong:rgba(148,163,184,.28);
  --dy-text:#e8edf8;
  --dy-soft:#b6c2da;
  --dy-muted:#aebbd6;
  --dy-accent:#8b8bff;
  --dy-accent-2:#22d3ee;
  --dy-chip:rgba(139,139,255,.14);
  --dy-icon-bg:rgba(30,41,68,.9);
  --dy-shadow:0 8px 28px rgba(0,0,0,.28);
  --dy-shadow-hover:0 18px 38px rgba(0,0,0,.42);
  --dy-glow-a:rgba(34,211,238,.16);
  --dy-glow-b:rgba(139,92,246,.18);
}
html{scroll-behavior:smooth}
body{
  margin:0;
  font-family:var(--dy-font);
  color:var(--dy-text);
  background:var(--dy-bg);
  background-image:
    radial-gradient(900px 600px at 8% -8%,var(--dy-glow-a),transparent 62%),
    radial-gradient(800px 560px at 96% 4%,var(--dy-glow-b),transparent 60%);
  background-attachment:fixed;
  line-height:1.65;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit;text-decoration:none}
.dy-top{
  position:sticky;top:0;z-index:20;
  display:flex;align-items:center;gap:14px;
  padding:10px clamp(16px,4vw,42px);
  background:var(--dy-surface);
  border-bottom:1px solid var(--dy-border);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
}
.dy-back{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--dy-soft)}
.dy-back:hover{color:var(--dy-accent)}
.dy-back svg{width:15px;height:15px}
.dy-brand{font-size:12.5px;color:var(--dy-muted);padding-left:14px;border-left:1px solid var(--dy-border)}
.dy-top-spacer{flex:1}
.dy-top-link,.dy-theme{
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 11px;border-radius:999px;
  border:1px solid var(--dy-border-strong);
  background:transparent;color:var(--dy-soft);
  font:600 12px var(--dy-font);cursor:pointer;
}
.dy-top-link:hover,.dy-theme:hover{color:var(--dy-accent);border-color:var(--dy-accent)}
.dy-top-link svg,.dy-theme svg{width:14px;height:14px;fill:currentColor}
.dy-wrap{max-width:1080px;margin:0 auto;padding:0 clamp(16px,4vw,42px) 72px}
.dy-hero{padding:clamp(38px,6vw,68px) 0 30px}
.dy-kicker{
  display:inline-block;padding:4px 11px;border-radius:999px;
  background:var(--dy-chip);color:var(--dy-accent);
  font-size:11.5px;font-weight:700;letter-spacing:.04em;
}
.dy-hero h1{
  margin:16px 0 10px;font-size:clamp(28px,4.6vw,44px);
  line-height:1.2;letter-spacing:-.02em;font-weight:800;
  background:linear-gradient(100deg,var(--dy-accent),var(--dy-accent-2));
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.dy-hero p{margin:0;max-width:720px;color:var(--dy-soft);font-size:14.5px}
.dy-stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
.dy-stat{
  flex:1 1 150px;min-width:130px;padding:13px 16px;
  border:1px solid var(--dy-border);border-radius:14px;
  background:var(--dy-surface);box-shadow:var(--dy-shadow);
}
.dy-stat span{display:block;font-size:11.5px;color:var(--dy-muted)}
.dy-stat strong{display:block;margin-top:2px;font-size:21px;line-height:1.3;font-weight:750}
.dy-rssbar{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin:8px 0 6px;padding:12px 16px;
  border:1px dashed var(--dy-border-strong);border-radius:12px;
  font-size:12.5px;color:var(--dy-muted);
}
.dy-rssbar code{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--dy-soft);background:var(--dy-chip);padding:2px 7px;border-radius:6px;
  word-break:break-all;
}
.dy-rssbar a{color:var(--dy-accent);font-weight:650}
.dy-timeline{position:relative;margin-top:34px;padding-left:26px}
.dy-timeline::before{
  content:"";position:absolute;left:6px;top:8px;bottom:8px;width:2px;
  background:linear-gradient(180deg,var(--dy-accent),var(--dy-accent-2),transparent);
  opacity:.45;border-radius:2px;
}
.dy-day{position:relative;margin-bottom:38px;scroll-margin-top:76px}
.dy-day::before{
  content:"";position:absolute;left:-26px;top:9px;width:14px;height:14px;
  border-radius:50%;background:var(--dy-solid);
  border:3px solid var(--dy-accent);box-shadow:0 0 0 4px var(--dy-chip);
}
.dy-day-head{display:flex;align-items:baseline;gap:11px;flex-wrap:wrap;margin-bottom:14px}
.dy-day-head h2{margin:0;font-size:19px;font-weight:750;letter-spacing:-.01em}
.dy-week{font-size:12.5px;color:var(--dy-muted)}
.dy-count{
  padding:2px 9px;border-radius:999px;background:var(--dy-chip);
  color:var(--dy-accent);font-size:11px;font-weight:700;
}
.dy-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:12px}
.dy-card{
  display:flex;gap:12px;padding:15px;
  border:1px solid var(--dy-border);border-radius:14px;
  background:var(--dy-surface);box-shadow:var(--dy-shadow);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;
}
.dy-card:hover{transform:translateY(-3px);box-shadow:var(--dy-shadow-hover);border-color:var(--dy-accent)}
.dy-icon{
  position:relative;flex:0 0 38px;width:38px;height:38px;border-radius:10px;
  background:var(--dy-icon-bg);overflow:hidden;
  display:flex;align-items:center;justify-content:center;
}
.dy-icon img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:5px}
.dy-initial{font-size:16px;font-weight:750;color:var(--dy-accent)}
.dy-card-body{min-width:0;flex:1}
.dy-card-name{
  display:block;font-size:14px;font-weight:700;line-height:1.4;
  overflow-wrap:anywhere;
}
.dy-card:hover .dy-card-name{color:var(--dy-accent)}
.dy-tag{
  display:inline-block;margin:6px 0 5px;padding:1px 8px;border-radius:6px;
  background:var(--dy-chip);color:var(--dy-accent);font-size:10.5px;font-weight:650;
}
.dy-desc{margin:0;font-size:12.5px;color:var(--dy-soft);line-height:1.6}
.dy-footer{
  margin-top:46px;padding-top:20px;border-top:1px solid var(--dy-border);
  font-size:12px;color:var(--dy-muted);
}
.dy-footer a{color:var(--dy-accent)}
.dy-empty{padding:26px;border:1px dashed var(--dy-border-strong);border-radius:14px;color:var(--dy-muted)}
@media (max-width:600px){
  .dy-brand{display:none}
  .dy-top{padding:10px 16px;gap:9px}
  .dy-cards{grid-template-columns:1fr}
  .dy-timeline{padding-left:20px}
  .dy-day::before{left:-20px}
}
@media (prefers-reduced-motion:reduce){
  *{scroll-behavior:auto!important;transition:none!important}
}
"""

JS = r"""
(function(){
  var body=document.body;
  function isNight(){return /(?:^|;\s*)night=1(?:;|$)/.test(document.cookie);}
  function apply(){body.classList.toggle('night',isNight());}
  apply();
  var btn=document.getElementById('dy-theme');
  if(btn){btn.addEventListener('click',function(){
    document.cookie=(isNight()?'night=0':'night=1')+';path=/;max-age=31536000';
    apply();
  });}
  // favicon 取不到时移除 <img>，露出底下的首字母占位
  Array.prototype.forEach.call(document.querySelectorAll('.dy-icon img'),function(img){
    img.addEventListener('error',function(){if(img.parentNode)img.parentNode.removeChild(img);});
  });
})();
"""

ICON_BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M11 18l-6-6 6-6"/></svg>'
ICON_RSS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11a9 9 0 0 1 9 9h-3a6 6 0 0 0-6-6v-3zm0-6a15 15 0 0 1 15 15h-3A12 12 0 0 0 4 8V5zm1.8 12.2a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/></svg>'
ICON_MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.3 3a9 9 0 1 0 8.7 11.4A7.2 7.2 0 0 1 12.3 3z"/></svg>'


# ---------------------------------------------------------------- 数据读取
def esc(value) -> str:
    """所有来自 YAML 的文本统一转义，避免破坏 HTML 结构。"""
    return html.escape(str(value if value is not None else ""), quote=True)


def load_entries(data_file: Path) -> tuple[list[dict], list[str]]:
    """返回 (条目列表, 警告列表)。条目按分类顺序、分类内原始顺序排列。"""
    if not data_file.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_file}")
    try:
        data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"webstack.yml 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("webstack.yml 顶层不是映射")

    entries, warnings = [], []
    for cat, (label, short) in CATEGORY_LABELS.items():
        block = data.get(cat)
        if block is None:
            warnings.append(f"分类 {cat} 不存在，按空处理")
            continue
        if not isinstance(block, list):
            raise ValueError(f"分类 {cat} 不是列表")
        for raw in block:
            if not isinstance(raw, dict):
                warnings.append(f"分类 {cat} 中有非映射条目，已跳过")
                continue
            name, url = raw.get("name"), raw.get("url")
            if not name or not url:
                warnings.append(f"分类 {cat} 中缺少 name/url，已跳过")
                continue
            desc = str(raw.get("description") or "").strip()
            match = DATE_TAG_RE.search(desc)
            day = match.group(1) if match else None
            if day:
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                except ValueError:
                    day, match = None, None
                    warnings.append(f"{name} 的日期尾注非法，归入早期收录")
            clean_desc = DATE_TAG_RE.sub("", desc).strip().rstrip("·").strip() if match else desc
            entries.append({
                "name": str(name),
                "url": str(url),
                "img": str(raw.get("img") or ""),
                "description": clean_desc,
                "category": cat,
                "label": label,
                "short": short,
                "day": day,
            })
    return entries, warnings


def group_by_day(entries: list[dict]):
    """按日期倒序分组；无日期的放到最后的「早期收录」。"""
    dated: dict[str, list[dict]] = {}
    undated = []
    for item in entries:
        if item["day"]:
            dated.setdefault(item["day"], []).append(item)
        else:
            undated.append(item)
    days = [(d, dated[d]) for d in sorted(dated, reverse=True)]
    return days, undated


# ---------------------------------------------------------------- HTML 生成
def day_heading(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return f"{d.year} 年 {d.month} 月 {d.day} 日", WEEKDAYS[d.weekday()]


def card_html(item: dict) -> str:
    initial = esc(next((c for c in item["name"] if not c.isspace()), "A").upper())
    icon = ""
    if item["img"]:
        icon = f'<img src="{esc(item["img"])}" alt="" loading="lazy">'
    desc = f'<p class="dy-desc">{esc(item["description"])}</p>' if item["description"] else ""
    return (
        f'<a class="dy-card" href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">'
        f'<span class="dy-icon"><span class="dy-initial">{initial}</span>{icon}</span>'
        f'<span class="dy-card-body">'
        f'<span class="dy-card-name">{esc(item["name"])}</span>'
        f'<span class="dy-tag">{esc(item["label"])}</span>'
        f'{desc}</span></a>'
    )


def build_html(entries: list[dict], days, undated, site_url: str, generated: datetime) -> str:
    dated_count = sum(len(v) for _, v in days)
    latest = days[0][0] if days else "—"
    root = site_url.rstrip("/")
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>每日 AI 速递 · cyberMap</title>",
        '<meta name="description" content="cyberMap 每日核验收录的 AI 开源项目、工具官网与模型框架，按收录日期倒序回看，支持 RSS 订阅。">',
        f'<link rel="canonical" href="{root}/daily/">',
        '<link rel="icon" href="/favicon.ico">',
        '<link rel="alternate" type="application/rss+xml" title="cyberMap 每日 AI 速递" href="/daily/feed.xml">',
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        '<header class="dy-top">',
        f'<a class="dy-back" href="/" title="返回 cyberMap 导航首页">{ICON_BACK}<span>cyberMap 导航</span></a>',
        '<span class="dy-brand">每日 AI 速递</span>',
        '<span class="dy-top-spacer"></span>',
        f'<a class="dy-top-link" href="/daily/feed.xml" title="RSS 2.0 订阅源">{ICON_RSS}<span>RSS 订阅</span></a>',
        f'<button class="dy-theme" id="dy-theme" type="button" title="切换深浅色" aria-label="切换深浅色">{ICON_MOON}</button>',
        "</header>",
        '<main class="dy-wrap">',
        '<section class="dy-hero">',
        '<span class="dy-kicker">每日更新 · 逐条核验</span>',
        "<h1>每日 AI 速递</h1>",
        "<p>每天从公开来源核验后收录 2-3 个 AI 站点，按类型归入开源项目 / 工具官网 / 模型框架。"
        "这里按收录日期倒序回看，不再让新站点淹没在分类列表里。</p>",
        '<div class="dy-stats">',
        f'<div class="dy-stat"><span>累计收录</span><strong>{len(entries)}</strong></div>',
        f'<div class="dy-stat"><span>每日期数</span><strong>{len(days)}</strong></div>',
        f'<div class="dy-stat"><span>最近更新</span><strong>{esc(latest)}</strong></div>',
        f'<div class="dy-stat"><span>生成时间</span><strong>{generated.strftime("%m-%d %H:%M")}</strong></div>',
        "</div></section>",
        '<div class="dy-rssbar">订阅地址 <code>' + esc(f"{root}/daily/feed.xml") +
        '</code> · 每天一期，含当日全部新收录站点。<a href="/daily/feed.xml">打开订阅源 →</a></div>',
        '<div class="dy-timeline">',
    ]

    if not days and not undated:
        parts.append('<div class="dy-empty">暂无已收录站点，等待第一次每日收录。</div>')

    for day, items in days:
        title, week = day_heading(day)
        parts.append(f'<section class="dy-day" id="day-{esc(day)}">')
        parts.append(
            '<div class="dy-day-head">'
            f'<h2>{esc(title)}</h2><span class="dy-week">{esc(week)}</span>'
            f'<span class="dy-count">{len(items)} 个站点</span></div>'
        )
        parts.append('<div class="dy-cards">' + "".join(card_html(i) for i in items) + "</div>")
        parts.append("</section>")

    if undated:
        parts.append('<section class="dy-day" id="day-early">')
        parts.append(
            '<div class="dy-day-head"><h2>早期收录</h2>'
            '<span class="dy-week">描述中没有日期尾注</span>'
            f'<span class="dy-count">{len(undated)} 个站点</span></div>'
        )
        parts.append('<div class="dy-cards">' + "".join(card_html(i) for i in undated) + "</div>")
        parts.append("</section>")

    parts += [
        "</div>",  # /dy-timeline
        '<footer class="dy-footer">',
        f'数据来源：<a href="{esc(root)}/">cyberMap</a> 的 <code>dailyAI_*</code> 分类，'
        "每条收录前均经过 HTTP 实探与内容核验。日期取自描述尾注「· YYYY-MM-DD 收录」。",
        f'<br>共 {len(entries)} 个站点、{len(days)} 期（其中 {dated_count} 条有明确日期）；'
        f'最后生成于 {generated.strftime("%Y-%m-%d %H:%M")} (UTC+8)。',
        "</footer>",
        "</main>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- RSS 生成
def build_feed(days, site_url: str, generated: datetime) -> bytes:
    """每天一个 item；无日期的「早期收录」不进 RSS，避免伪造发布时间。"""
    root = site_url.rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "cyberMap · 每日 AI 速递"
    ET.SubElement(channel, "link").text = f"{root}/daily/"
    ET.SubElement(channel, "description").text = (
        "cyberMap 每日核验收录的 AI 开源项目、工具官网与模型框架，每天一期。"
    )
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "generator").text = "cybermap-daily/build_daily.py"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    ET.SubElement(channel, "ttl").text = "1440"

    for day, items in days:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"每日 AI 速递 · {day}（{len(items)} 个站点）"
        link = f"{root}/daily/#day-{day}"
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        d = datetime.strptime(day, "%Y-%m-%d").date()
        ET.SubElement(item, "pubDate").text = format_datetime(
            datetime.combine(d, time(0, 0), tzinfo=CST)
        )
        lines = [f'{i["name"]}［{i["label"]}］{i["description"]} — {i["url"]}' for i in items]
        ET.SubElement(item, "description").text = "\n".join(lines)
        ET.SubElement(item, "category").text = "AI"

    if hasattr(ET, "indent"):
        ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 写入与入口
def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    here = Path(__file__).resolve()
    default_repo = Path(os.environ.get("CYBERMAP_REPO", here.parent.parent))
    ap = argparse.ArgumentParser(description="生成 cyberMap 每日 AI 速递时间轴与 RSS")
    ap.add_argument("--repo", type=Path, default=default_repo, help="cyberMap 仓库根目录")
    ap.add_argument("--out", type=Path, default=None, help="输出目录（默认 <repo>/source/daily）")
    ap.add_argument("--site-url", default=SITE_URL_DEFAULT, help="站点根 URL（用于 RSS 绝对链接）")
    ap.add_argument("--check", action="store_true", help="只校验数据，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    data_file = repo / DATA_REL
    out_dir = (args.out or (repo / OUT_REL)).resolve()
    site_url = args.site_url.rstrip("/")

    try:
        entries, warnings = load_entries(data_file)
    except (FileNotFoundError, ValueError) as exc:
        fail(str(exc))

    days, undated = group_by_day(entries)
    generated = datetime.now(CST)
    summary = {
        "ok": True,
        "sites": len(entries),
        "days": len(days),
        "undated": len(undated),
        "latest": days[0][0] if days else None,
        "warnings": warnings,
    }
    if args.check:
        print(json.dumps({**summary, "check_only": True}, ensure_ascii=False, indent=2))
        return

    html_text = build_html(entries, days, undated, site_url, generated)
    feed_bytes = build_feed(days, site_url, generated)

    # 写完再自检一遍，避免把语法错误的产物发布出去
    ET.fromstring(feed_bytes)
    if "<html" not in html_text or html_text.count('<section class="dy-day"') != (
        len(days) + (1 if undated else 0)
    ):
        fail("生成的 HTML 结构自检未通过，未写入")

    index_path = out_dir / "index.html"
    feed_path = out_dir / "feed.xml"
    try:
        atomic_write(index_path, html_text.encode("utf-8"))
        atomic_write(feed_path, feed_bytes)
    except OSError as exc:
        fail(f"写入产物失败：{exc}")

    summary["outputs"] = {
        "index": str(index_path),
        "feed": str(feed_path),
        "index_bytes": index_path.stat().st_size,
        "feed_bytes": feed_path.stat().st_size,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
