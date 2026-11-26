#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · AI 工具开放数据层生成器

把全站导航与已有的验证 / 健康数据聚合成三份可对外订阅的静态产物：

  * ``source/data/sites.json``   机器可读的全量站点目录（233 条，含分类 /
                                 方向标签 / 验证证据 / stars / 健康态）
  * ``source/data/sites.opml``   按「父分组 → 子分类」两层嵌套的 OPML，
                                 可一键导入书签或 RSS 阅读器
  * ``source/data/index.html``   /data/ 文档页：字段表 + 调用示例 + 统计

设计约束
--------
* 零新增依赖：只用标准库 + 仓库已有的 PyYAML。
* 标签规则与 URL 归一化直接复用 ``build_daily.py``（import 而非复制），
  保证 sites.json 的 tags 与 /daily/ 卡片标签永远一致。
* 只读数据源：绝不改写 webstack.yml / verify.json / health.json。
* 幂等：产物不写生成时间戳，同样输入产出字节一致；可用 --check 自检。
* 优雅降级：verify.json / health.json 缺失或损坏时照常产出，只是对应
  字段为 null，不抛异常、不阻断收录。
* 自包含页面：内联 CSS / JS，浅/深主题通过共享 cookie ``night=1`` 同步。
* 靠 _config.yml 的 ``skip_render: data/**`` 原样发布，无需改主题。

由用户级 skill `cybermap-daily` 的 add 在每日收录成功后自动调用；也可手动：

    python scripts/build_data.py --repo <repo>
    python scripts/build_data.py --repo <repo> --check

退出码：0 成功；1 数据/参数/写入错误（stdout 输出 JSON 诊断）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"缺少 PyYAML：{exc}"}, ensure_ascii=False))
    sys.exit(1)

# 与 build_daily.py 共享标签规则 / URL 归一化 / 日期尾注解析 / 站点根 URL。
# 直接 import 避免规则漂移；build_daily 顶层无 I/O，仅定义常量与函数。
try:
    from build_daily import (
        DATE_TAG_RE,
        infer_tags,
        norm_url,
        SITE_URL_DEFAULT,
    )
except Exception as _exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"无法从 build_daily.py 复用规则：{_exc}"},
                     ensure_ascii=False))
    sys.exit(1)

SITE_URL = SITE_URL_DEFAULT.rstrip("/")
DATA_REL = Path("source/_data/webstack.yml")
VERIFY_REL = Path("source/daily/verify.json")
HEALTH_REL = Path("source/daily/health.json")
OUT_DIR = Path("source/data")
SITES_JSON_REL = OUT_DIR / "sites.json"
SITES_OPML_REL = OUT_DIR / "sites.opml"
INDEX_REL = OUT_DIR / "index.html"

SCHEMA = 1


# ---------------------------------------------------------------- 数据聚合
def load_json_map(path: Path, key: str) -> tuple[dict, str | None]:
    """读取 JSON 的某个 dict 字段；缺失/损坏返回空 dict + 告警。"""
    if not path.is_file():
        return {}, f"{path.relative_to(path.parents[1]) if False else path.name} 缺失，对应字段降级为 null"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get(key)
        if not isinstance(value, dict):
            return {}, f"{path.name} 的 {key} 不是对象，已降级"
        return value, None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"{path.name} 读取失败，已降级：{exc}"


def collect(repo: Path) -> tuple[dict, list[str]]:
    """从 webstack.yml + verify.json + health.json 聚合出 payload。"""
    data_path = repo / DATA_REL
    if not data_path.is_file():
        raise FileNotFoundError(f"找不到数据文件 {data_path}")
    try:
        data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"webstack.yml 解析失败：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("menu"), list):
        raise ValueError("webstack.yml 顶层缺少 menu 列表")

    warnings: list[str] = []
    evidence, e_warn = load_json_map(repo / VERIFY_REL, "evidence")
    if e_warn:
        warnings.append("验证证据：" + e_warn)
    health_sites, h_warn = load_json_map(repo / HEALTH_REL, "sites")
    if h_warn:
        warnings.append("健康数据：" + h_warn)

    groups: list[dict] = []
    categories: list[dict] = []
    sites: list[dict] = []

    for parent in data["menu"]:
        if not isinstance(parent, dict):
            warnings.append("menu 中有非映射父项，已跳过")
            continue
        group_name = str(parent.get("name") or "未命名分组")
        subs = parent.get("submenu")
        if not isinstance(subs, list):
            continue
        group_cats: list[dict] = []
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            key = sub.get("config")
            cat_name = str(sub.get("name") or key or "未命名分类")
            if not key:
                continue
            block = data.get(key)
            if block is None:
                warnings.append(f"分类 {key} 不存在，按空处理")
                block = []
            if not isinstance(block, list):
                warnings.append(f"分类 {key} 不是列表，已跳过")
                continue

            cat_sites: list[dict] = []
            for raw in block:
                if not isinstance(raw, dict):
                    warnings.append(f"分类 {key} 中有非映射条目，已跳过")
                    continue
                name, url = raw.get("name"), raw.get("url")
                if not name or not url:
                    warnings.append(f"分类 {key} 中缺少 name/url 的条目已跳过")
                    continue
                name, url = str(name), str(url)
                desc = str(raw.get("description") or "").strip()
                match = DATE_TAG_RE.search(desc)
                day = match.group(1) if match else None
                clean_desc = DATE_TAG_RE.sub("", desc).strip().rstrip("·").strip() if match else desc

                vkey = norm_url(url)
                ev = evidence.get(vkey)
                verified = None
                if isinstance(ev, dict):
                    verified = {
                        "http_status": ev.get("http_status"),
                        "stars": ev.get("stars"),
                        "ai_hits": ev.get("ai_hits"),
                        "date": ev.get("date"),
                        "checked_at": ev.get("checked_at"),
                    }
                hrec = health_sites.get(vkey)
                health = hrec.get("status") if isinstance(hrec, dict) else None

                item = {
                    "name": name,
                    "url": url,
                    "img": str(raw.get("img") or ""),
                    "description": clean_desc,
                    "category": str(key),
                    "category_name": cat_name,
                    "group": group_name,
                    "date": day,
                    "tags": infer_tags(name, clean_desc),
                    "verified": verified,
                    "health": health,
                }
                cat_sites.append(item)
                sites.append(item)

            cat_meta = {
                "key": str(key),
                "name": cat_name,
                "group": group_name,
                "count": len(cat_sites),
            }
            categories.append(cat_meta)
            group_cats.append(cat_meta)

        groups.append({"name": group_name, "categories": group_cats, "count":
                       sum(c["count"] for c in group_cats)})

    payload = {
        "schema": SCHEMA,
        "site": {
            "name": "cyberMap",
            "url": SITE_URL + "/",
            "description": "AI 工具与开源项目导航 · 全站结构化目录",
        },
        "counts": {
            "sites": len(sites),
            "groups": len(groups),
            "categories": len(categories),
            "verified": sum(1 for s in sites if s["verified"] is not None),
            "health_checked": len(health_sites),
        },
        "categories": categories,
        "sites": sites,
        # groups 只放元数据（分类 key 列表），站点实体只在扁平 sites 里出现一次，
        # 避免同一条数据在两个地方各存一份导致体积翻倍与不同步。
        "group_index": [{"name": g["name"], "count": g["count"],
                         "categories": [c["key"] for c in g["categories"]]} for g in groups],
    }
    return payload, warnings


# ---------------------------------------------------------------- 三份产物
def render_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_opml(payload: dict) -> str:
    """按父分组 → 子分类两层 outline 嵌套；叶子是站点。不写 dateCreated 保证幂等。"""
    root = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = "cyberMap · AI 工具开放目录"
    ET.SubElement(head, "htmlUrl").text = SITE_URL + "/"
    body = ET.SubElement(root, "body")

    by_cat: dict[str, list[dict]] = {}
    for s in payload["sites"]:
        by_cat.setdefault(s["category"], []).append(s)

    for g in payload["group_index"]:
        gnode = ET.SubElement(body, "outline", {"text": g["name"]})
        for ck in g["categories"]:
            cat = next((c for c in payload["categories"] if c["key"] == ck), None)
            cnode = ET.SubElement(gnode, "outline", {
                "text": cat["name"] if cat else ck,
                "title": cat["name"] if cat else ck,
            })
            for s in by_cat.get(ck, []):
                attrs = {
                    "type": "link",
                    "text": s["name"],
                    "title": s["name"],
                    "url": s["url"],
                    "htmlUrl": s["url"],
                }
                if s["description"]:
                    attrs["description"] = s["description"]
                ET.SubElement(cnode, "outline", attrs)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


PAGE_CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
 --bg:#f4f7fc;--surface:rgba(255,255,255,.86);--solid:#fff;
 --border:rgba(15,23,42,.09);--border2:rgba(15,23,42,.15);
 --text:#1b2436;--soft:#45526b;--muted:#6b7790;
 --accent:#4f46e5;--accent2:#06b6d4;--chip:rgba(79,70,229,.09);
 --glow-a:rgba(56,189,248,.20);--glow-b:rgba(167,139,250,.18);
 --shadow:0 4px 18px rgba(19,32,62,.055);--code:#0f1830;
}
body.night{
 /* 设计稿 05 号板 = 全站设计语言：VOID/SURFACE/EDGE/NEON-C/NEON-M/ONLINE/IDLE/TEXT */
 --bg:#05070b;--surface:rgba(11,18,27,.82);--solid:#0b121b;
 --border:rgba(18,48,63,.9);--border2:#12303f;
 --text:#e6f5ff;--soft:#b7c9df;--muted:#8ba0bd;
 --accent:#00e5ff;--accent2:#ff2ea6;--chip:rgba(0,229,255,.12);
 --glow-a:rgba(0,229,255,.13);--glow-b:rgba(255,46,166,.11);
 --shadow:0 8px 28px rgba(0,0,0,.45);--code:#050912;
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
.hero{padding:56px 0 34px}
.hero h1{margin:0 0 12px;font-size:30px;font-weight:600;letter-spacing:-.02em}
.hero p{margin:0;color:var(--soft);font-size:15px;max-width:720px}
.tag{display:inline-block;padding:3px 10px;border-radius:20px;background:var(--chip);
 color:var(--accent);font-size:12px;margin-bottom:14px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:8px 0 40px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:14px;
 padding:18px 20px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:26px;font-weight:600;line-height:1.2}
.stat span{font-size:12px;color:var(--muted)}
.sec{margin:0 0 42px}
.sec h2{font-size:18px;font-weight:600;margin:0 0 6px}
.sec .hint{color:var(--muted);font-size:13px;margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.card{display:block;background:var(--surface);border:1px solid var(--border);
 border-radius:14px;padding:20px;box-shadow:var(--shadow);transition:transform .15s,border-color .15s}
.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.card .ext{font-size:12px;color:var(--accent);font-weight:600}
.card h3{margin:8px 0 6px;font-size:15px;font-weight:600}
.card p{margin:0;color:var(--soft);font-size:13px}
.card .path{margin-top:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 font-size:11px;color:var(--muted);word-break:break-all}
.panel{background:var(--solid);border:1px solid var(--border);border-radius:14px;
 box-shadow:var(--shadow);overflow:hidden}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:11px 16px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:500;background:var(--chip);white-space:nowrap}
td code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent);font-size:12px}
tr:last-child td,tr:last-child th{border-bottom:0}
pre{margin:0;padding:16px 18px;background:var(--code);color:#d7e2ff;
 border-radius:12px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 font-size:12px;line-height:1.7}
.tabs{display:flex;gap:8px;margin-bottom:12px}
.tab{padding:6px 13px;border-radius:8px;border:1px solid var(--border2);
 background:var(--solid);font-size:12px;color:var(--soft);cursor:pointer}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.foot{padding:30px 0 50px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
@media(max-width:720px){.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
/* ---- 设计稿 05 号板：开放数据页赛博态（仅 body.night 生效，经典态零改动） ---- */
.dy-data-design-only{display:none!important}
body.night .dy-data-design-only{display:flex!important}
body.night::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;
 background:repeating-linear-gradient(0deg,rgba(0,0,0,.12) 0 1px,transparent 1px 3px);opacity:.42}
body.night .top{top:28px;background:rgba(11,18,27,.9);border-bottom:1px solid #12303f}
body.night .top .brand{font-family:"CM Orbitron",sans-serif;font-weight:900;letter-spacing:.04em;color:var(--accent)}
body.night .btn{border-radius:2px;border-color:#12303f;background:rgba(11,18,27,.86);
 font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px;letter-spacing:.05em}
body.night .btn:hover{color:var(--accent2);border-color:var(--accent2)}
body.night .wrap{max-width:1180px}
body.night .tag{border-radius:2px;font-family:"CM Mono","JetBrains Mono",monospace;
 font-size:10px;letter-spacing:.1em;color:var(--accent)}
body.night .hero h1{font-family:"CM Chakra","Chakra Petch",sans-serif;font-weight:900;
 font-size:clamp(30px,3.4vw,44px);letter-spacing:-.02em}
body.night .hero p{font-size:13px;color:var(--muted)}
body.night .stat,body.night .card,body.night .panel{border-radius:3px;border-color:#12303f}
body.night .stat b{font-family:"CM Orbitron",sans-serif;font-size:30px;font-weight:900;color:var(--accent)}
body.night .stat span{font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.06em}
body.night .card h3{font-family:"CM Chakra","Chakra Petch",sans-serif;font-weight:600}
body.night .card .ext,body.night .card .path{font-family:"CM Mono","JetBrains Mono",monospace;color:var(--accent)}
body.night .sec h2{font-family:"CM Chakra","Chakra Petch",sans-serif;font-weight:600;letter-spacing:.02em}
body.night .sec h2::before{content:"// ";color:var(--accent2);font-family:"CM Mono","JetBrains Mono",monospace}
body.night th{font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px;letter-spacing:.06em;color:var(--accent)}
body.night td code{color:var(--accent2)}
body.night .tab{border-radius:2px;border-color:#12303f;background:rgba(11,18,27,.86);
 font-family:"CM Mono","JetBrains Mono",monospace}
body.night .tab.on{background:rgba(255,46,166,.16);border-color:var(--accent2);color:var(--accent2)}
body.night pre{border-radius:3px;border:1px solid #12303f}
@media (prefers-reduced-motion:reduce){body.night::after{background:none}}
"""


def render_html(payload: dict) -> str:
    c = payload["counts"]
    e = html.escape
    cards = f"""      <a class="card" href="/data/sites.json">
        <div class="ext">JSON · application/json</div>
        <h3>sites.json</h3>
        <p>全量结构化目录。每条站点含分类、方向标签、验证证据、stars 与健康态，随每日收录自动更新。</p>
        <div class="path">/data/sites.json</div>
      </a>
      <a class="card" href="/data/sites.opml">
        <div class="ext">OPML · text/x-opml</div>
        <h3>sites.opml</h3>
        <p>按「父分组 → 子分类」两层组织的订阅文件，一键导入书签或 RSS 阅读器。</p>
        <div class="path">/data/sites.opml</div>
      </a>
      <a class="card" href="/daily/">
        <div class="ext">HTML · text/html</div>
        <h3>每日速递</h3>
        <p>按日期回看每天新增的 AI 站点，带核验徽章、质量回执与分类订阅 RSS。</p>
        <div class="path">/daily/</div>
      </a>"""

    field_rows = [
        ("name", "string", "站点名称"),
        ("url", "string", "官网或仓库地址"),
        ("category", "string", "分类 key，如 <code>aiChat</code> / <code>githubGPT</code>"),
        ("category_name", "string", "分类中文名"),
        ("group", "string", "所属父分组"),
        ("date", "string|null", "收录日期 YYYY-MM-DD，无尾注则为 null"),
        ("tags", "string[]", "方向标签，最多 3 个（与 /daily/ 卡片一致）"),
        ("verified", "object|null", "验证证据：http_status / stars / ai_hits / date / checked_at"),
        ("health", "string|null", "站点健康态：ok / down / unverified"),
    ]
    rows = "".join(
        f"        <tr><td><code>{e(k)}</code></td><td><code>{e(t)}</code></td><td>{d}</td></tr>\n"
        for k, t, d in field_rows
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 工具开放数据层 · cyberMap</title>
<meta name="description" content="cyberMap 全站 AI 工具与开源项目的结构化开放数据：sites.json、OPML 订阅与字段文档。">
<meta name="theme-color" content="#4f46e5">
<link rel="icon" href="/favicon.ico">
<style>@font-face{{font-family:"CM Orbitron";src:url("/fonts/cm-orbitron-latin.woff2") format("woff2");font-style:normal;font-weight:400 900;font-display:swap}}@font-face{{font-family:"CM Chakra";src:url("/fonts/cm-chakra-600-latin.woff2") format("woff2");font-style:normal;font-weight:600;font-display:swap}}@font-face{{font-family:"CM Mono";src:url("/fonts/cm-jetbrains-latin.woff2") format("woff2");font-style:normal;font-weight:400 700;font-display:swap}}</style>
<script>try{{if(document.cookie.split('; ').indexOf('night=1')>=0)document.documentElement.classList.add('night')}}catch(e){{}}</script>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="dy-data-design-only" style="position:sticky;top:0;z-index:19;display:none;align-items:center;gap:12px;height:28px;padding:0 24px;background:#07121c;border-bottom:1px solid #12303f;font-family:'CM Mono','JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;color:#6b7f99" id="dyDataHud"><b style="color:#00e5ff">SECTION 05 // OPEN DATA LAYER</b><span style="margin-left:auto;font-family:'CM Orbitron',sans-serif;font-weight:900;color:#00e5ff">{e(str(c['sites']))} NODES · {e(str(c['categories']))} SECTORS</span></div>
<header class="top">
  <div class="brand">cyberMap / data</div>
  <div class="spacer"></div>
  <a class="btn" href="/">返回首页</a>
  <button class="btn" id="themeBtn" type="button">切换主题</button>
</header>
<div class="wrap">
  <section class="hero">
    <div class="tag">Open data · 每天自动更新</div>
    <h1>AI 工具开放数据层</h1>
    <p>把全站 {e(str(c['sites']))} 个 AI 工具与开源项目，连同逐条验证证据、方向标签与站点健康态，整理成一份机器可读、可直接订阅的开放数据。导航站不只是给人看，也能给你的工具或 Agent 用。</p>
  </section>

  <section class="stats">
    <div class="stat"><b>{e(str(c['sites']))}</b><span>收录站点</span></div>
    <div class="stat"><b>{e(str(c['categories']))}</b><span>子分类 / {e(str(c['groups']))} 父分组</span></div>
    <div class="stat"><b>{e(str(c['verified']))}</b><span>带验证证据</span></div>
    <div class="stat"><b>{e(str(c['health_checked']))}</b><span>已做存活复检</span></div>
  </section>

  <section class="sec">
    <h2>三份产物</h2>
    <p class="hint">全部静态文件，无需鉴权，直接 GET 即可。数据随每日收录重建。</p>
    <div class="grid">
{cards}
    </div>
  </section>

  <section class="sec">
    <h2>字段表</h2>
    <p class="hint"><code>sites.json</code> 顶层含 <code>schema</code> / <code>site</code> / <code>counts</code> / <code>categories</code> / <code>group_index</code> / <code>sites</code>。下面是 <code>sites[]</code> 每条的字段。</p>
    <div class="panel">
      <table>
        <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
  </section>

  <section class="sec">
    <h2>调用示例</h2>
    <p class="hint">拿全量数据，筛出带验证证据的 RAG 类站点：</p>
    <div class="tabs">
      <button class="tab on" data-tab="code-curl" type="button">curl</button>
      <button class="tab" data-tab="code-py" type="button">Python</button>
      <button class="tab" data-tab="code-js" type="button">JavaScript</button>
    </div>
    <pre id="code-curl"># 全量目录
curl -s https://cybermap.halo26812.eu.org/data/sites.json | jq '.counts'

# 只看带验证证据、且打了「RAG 检索」标签的站点
curl -s https://cybermap.halo26812.eu.org/data/sites.json \
  | jq '[.sites[] | select(.verified != null and (.tags | index("RAG 检索")))] \
        | map({{name, url, stars: .verified.stars}})'</pre>
    <pre id="code-py" style="display:none">import json, urllib.request

url = "https://cybermap.halo26812.eu.org/data/sites.json"
data = json.load(urllib.request.urlopen(url))

rag = [s for s in data["sites"]
       if s["verified"] and "RAG 检索" in s["tags"]]
for s in rag[:10]:
    print(s["name"], s["url"], s["verified"]["stars"])</pre>
    <pre id="code-js" style="display:none">const res = await fetch('/data/sites.json');
const {{ sites, counts }} = await res.json();
const rag = sites.filter(s => s.verified && s.tags.includes('RAG 检索'));
console.log(counts.sites, 'total /', rag.length, 'RAG sites');</pre>
  </section>

  <section class="foot">
    数据来自 cyberMap 每日收录流水线 · 分类与标签同站内导航一致 · 验证证据由 api.github.com 与 HTTP 实探生成，stars 以 API 为准。
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
  var tabs=document.querySelectorAll('.tab');
  tabs.forEach(function(t){{
    t.addEventListener('click',function(){{
      tabs.forEach(function(x){{x.classList.remove('on')}});
      t.classList.add('on');
      ['code-curl','code-py','code-js'].forEach(function(id){{
        document.getElementById(id).style.display=(id===t.dataset.tab)?'block':'none';
      }});
    }});
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 校验 / 写入
def validate(payload: dict, json_text: str, opml_text: str, html_text: str) -> list[str]:
    """回读自检：JSON 结构一致、OPML 叶子数等于站点数、页面含关键区块。"""
    obj = json.loads(json_text)
    total = payload["counts"]["sites"]
    if obj.get("schema") != SCHEMA:
        raise ValueError("sites.json schema 不符")
    if len(obj.get("sites", [])) != total:
        raise ValueError("sites.json 的 sites 数量与 counts 不符")
    if len(obj.get("categories", [])) != payload["counts"]["categories"]:
        raise ValueError("categories 数量与 counts 不符")
    ids = [s["name"] + "|" + s["url"] for s in obj["sites"]]
    if len(ids) != len(set(ids)):
        raise ValueError("sites.json 出现重复条目")

    root = ET.fromstring(opml_text)
    if root.tag != "opml" or root.get("version") != "2.0":
        raise ValueError("sites.opml 根节点不是 opml 2.0")
    leaves = root.findall(".//outline[@type='link']")
    if len(leaves) != total:
        raise ValueError(f"sites.opml 站点 outline 数 {len(leaves)} != {total}")
    groups = root.findall("./body/outline")
    if len(groups) != payload["counts"]["groups"]:
        raise ValueError("sites.opml 父分组 outline 数不符")

    for marker in ("/data/sites.json", "/data/sites.opml", "字段表", "调用示例", str(total)):
        if marker not in html_text:
            raise ValueError(f"index.html 缺少关键内容：{marker}")
    return [f"schema={SCHEMA}", f"sites={total}", f"opml_leaves={len(leaves)}"]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 cyberMap 的开放数据层产物")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                    help="cyberMap 仓库根目录")
    ap.add_argument("--check", action="store_true", help="只校验数据与产物，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    try:
        payload, warnings = collect(repo)
        json_text = render_json(payload)
        opml_text = render_opml(payload)
        html_text = render_html(payload)
        checks = validate(payload, json_text, opml_text, html_text)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    result = {
        "ok": True,
        "counts": payload["counts"],
        "checks": checks,
        "warnings": warnings,
        "outputs": [str(SITES_JSON_REL), str(SITES_OPML_REL), str(INDEX_REL)],
    }
    if args.check:
        print(json.dumps({**result, "check_only": True}, ensure_ascii=False, indent=2))
        return 0

    try:
        atomic_write(repo / SITES_JSON_REL, json_text)
        atomic_write(repo / SITES_OPML_REL, opml_text)
        atomic_write(repo / INDEX_REL, html_text)
        # 回读三份产物，确认落盘内容就是刚校验过的那份
        validate(payload,
                 (repo / SITES_JSON_REL).read_text(encoding="utf-8"),
                 (repo / SITES_OPML_REL).read_text(encoding="utf-8"),
                 (repo / INDEX_REL).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"写入失败：{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    result["bytes"] = {
        "sites.json": len(json_text.encode("utf-8")),
        "sites.opml": len(opml_text.encode("utf-8")),
        "index.html": len(html_text.encode("utf-8")),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
