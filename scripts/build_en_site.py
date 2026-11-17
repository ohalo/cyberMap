#!/usr/bin/env python3
"""生成 cyberMap 英文首页子页面 source/en/index.md。

数据源：
  source/_data/webstack.yml   —— 中文导航的 url/img/结构（唯一权威源）
  scripts/data/en-nav-map.json —— 人工确认的英文翻译表（name/description）

机制：webstack 主题支持 flag + type:child 子页面。子页面 front-matter 里
直接内联英文的 menu + 18 个分类数据（走 index.pug 的 page.xxx 分支），
URL 与图片沿用 webstack.yml。语言菜单两个 flag：中文默认 / 英文。

用法：  python scripts/build_en_site.py
依赖：  PyYAML（托管 venv 已装）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：用 /Users/halo123456/.workbuddy/binaries/python/envs/default/bin/python 运行")

ROOT = Path(__file__).resolve().parent.parent
YML = ROOT / "source/_data/webstack.yml"
MAP = ROOT / "scripts/data/en-nav-map.json"
OUT = ROOT / "source/en/index.md"


def yaml_str(s: str) -> str:
    """把字符串安全地做成双引号 YAML 标量。"""
    return json.dumps(str(s), ensure_ascii=False)


def main() -> int:
    data = yaml.safe_load(YML.read_text(encoding="utf-8"))
    trans = json.loads(MAP.read_text(encoding="utf-8"))
    nav_map = trans["nav"]
    grp = trans["menu_groups"]
    ui = trans["ui"]

    # 收集 menu 引用的分类顺序
    configs: list[str] = []
    for g in data.get("menu", []):
        for s in g.get("submenu", []):
            configs.append(s["config"])

    # 缺失统计（不臆造：缺失则退回中文原名，并告警）
    missing: list[str] = []

    def tr(config: str, name: str) -> tuple[str, str]:
        key = f"{config}|{name}"
        hit = nav_map.get(key)
        if hit:
            return hit["n"], hit["d"]
        missing.append(key)
        return name, ""

    # ---- 组装英文 menu ----
    menu_lines = ["menu:"]
    for g in data.get("menu", []):
        gname = grp.get(g.get("name", ""), g.get("name", ""))
        menu_lines.append(f'  - name: {yaml_str(gname)}')
        if "icon" in g:
            menu_lines.append(f'    icon: {yaml_str(g["icon"])}')
        subs = g.get("submenu", [])
        if subs:
            menu_lines.append("    submenu:")
            for s in subs:
                sname = grp.get(s.get("name", ""), s.get("name", ""))
                menu_lines.append(f'      - name: {yaml_str(sname)}')
                if "icon" in s:
                    menu_lines.append(f'        icon: {yaml_str(s["icon"])}')
                menu_lines.append(f'        config: {yaml_str(s["config"])}')

    # ---- 组装 18 个分类的英文条目 ----
    cat_lines: list[str] = []
    for c in configs:
        cat_lines.append(f"{c}:")
        items = data.get(c, []) or []
        if not items:
            cat_lines.append("  []")
            continue
        for it in items:
            en_name, en_desc = tr(c, it.get("name", ""))
            cat_lines.append(f"  - name: {yaml_str(en_name)}")
            cat_lines.append(f'    url: {yaml_str(it.get("url", ""))}')
            cat_lines.append(f'    img: {yaml_str(it.get("img", ""))}')
            # 描述带日期尾注的，保留日期后缀（英文正文 + 中文收录标注统一格式）
            raw_desc = it.get("description", "") or ""
            mm = re.search(r"·\s*(\d{4}-\d{2}-\d{2})\s*收录\s*$", raw_desc)
            desc = en_desc or raw_desc
            if mm:
                desc = f"{desc} · Added {mm.group(1)}"
            cat_lines.append(f"    description: {yaml_str(desc)}")

    # ---- 英文页专用 custom：head 注入英文 JSON-LD；body 先跑全局增强再跑英文覆盖 ----
    custom_head_lines = [
        "custom:",
        "  head: |-",
        "    <!-- 英文页沿用 cyberMap 全部自定义样式（page.custom 覆盖 theme.custom） -->",
        '    <link rel="stylesheet" href="/css/cybermap.css">',
        "    <!-- 英文页 canonical：按路径动态生成 -->",
        "    <script>",
        "    (function () {",
        "      var p = location.pathname.replace(/index\\.html$/, '');",
        "      var canonical = 'https://cybermap.halo26812.eu.org' + p;",
        "      var link = document.createElement('link');",
        "      link.rel = 'canonical'; link.href = canonical;",
        "      document.head.appendChild(link);",
        "      var og = document.querySelector('meta[property=\"og:url\"]');",
        "      if (og) og.setAttribute('content', canonical);",
        "    })();",
        "    </script>",
        "    <link rel=\"alternate\" type=\"application/rss+xml\" title=\"cyberMap Daily AI Digest\" href=\"/daily/feed.xml\">",
        "    <script type=\"application/ld+json\">",
        '    {"@context":"https://schema.org","@type":"WebSite","name":"cyberMap","url":"https://cybermap.halo26812.eu.org/","description":"Daily-updated navigator for AI tools and open-source projects.","inLanguage":"en"}',
        "    </script>",
        "  body: |-",
        "    <script src=\"/js/cybermap.js\"></script>",
        "    <script src=\"/js/en-overlay.js\"></script>",
    ]

    # ---- front-matter ----
    flag_lines = [
        "flag:",
        "  - name: 中文",
        "    default: true",
        "    icon: flag-cn",
        "    index: /index.html",
        "  - name: English",
        "    default: false",
        "    icon: flag-us",
        "    index: /en/",
    ]

    head = [
        "---",
        "layout: page",
        "type: child",
        "title: English",
        "lang: en",
        f"tittle: {yaml_str(ui['tittle'])}",
        f"subtitle: {yaml_str(ui['subtitle'])}",
        f"description: {yaml_str(ui['description'])}",
        f"keywords: {yaml_str(ui['keywords'])}",
        *custom_head_lines,
        *flag_lines,
        # logo/favicon/js/css 沿用主题全局（theme），子页面只需覆盖差异项
        f"about:",
        f"  url: /about/",
        f"  icon: far fa-heart",
        f"  name: {yaml_str(ui['about_name'])}",
        *menu_lines,
        *cat_lines,
        "---",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(head) + "\n", encoding="utf-8")

    print(f"[en-site] 生成 {OUT.relative_to(ROOT)}")
    print(f"[en-site] {len(configs)} 个分类 / {sum(len(data.get(c, []) or []) for c in configs)} 条导航")
    if missing:
        print(f"[en-site] 警告：{len(missing)} 条缺翻译，已退回中文原名：", file=sys.stderr)
        for k in missing:
            print(f"   - {k}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
