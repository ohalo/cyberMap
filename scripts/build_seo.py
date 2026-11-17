#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap SEO 产物生成器：source/robots.txt + source/sitemap.xml。

只读仓库源码与 webstack.yml 的文件时间，零新增依赖（纯标准库），
原子写入、幂等（产物里不写生成时间，重跑字节一致）、可 --check 自检。

由用户级 skill `cybermap-daily` 的 add 在每日收录成功后自动调用；
也可手动运行：

    python scripts/build_seo.py --repo <repo>
    python scripts/build_seo.py --repo <repo> --check

设计取舍：
  * sitemap 只列「值得被索引」的页面。Hexo 自动生成的 archives/、示例文章
    hello-world、about 页都是薄内容，不进 sitemap（不等于禁止抓取）。
  * fragment（#day-YYYY-MM-DD）不是独立 URL，不进 sitemap。
  * rank 详情页由独立流水线维护，这里只读不写。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SITE_URL = "https://cybermap.halo26812.eu.org"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

DATA_REL = Path("source/_data/webstack.yml")
ROBOTS_REL = Path("source/robots.txt")
SITEMAP_REL = Path("source/sitemap.xml")

# 不 Disallow /css/ /js/：Google 需要加载资源才能正确渲染页面。
ROBOTS_TEXT = (
    "# cyberMap - allow all crawlers\n"
    "User-agent: *\n"
    "Allow: /\n"
    "\n"
    f"Sitemap: {SITE_URL}/sitemap.xml\n"
)


def iso_mtime(path: Path) -> str:
    """文件最后修改时间 → W3C datetime（UTC，秒精度）。"""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat()


def collect(repo: Path) -> tuple[list[dict], list[str], dict]:
    """收集 URL 清单。返回 (url 记录, 警告, 分类计数)。"""
    urls: list[dict] = []
    warnings: list[str] = []
    counts = {"home": 0, "daily": 0, "feed": 0, "rank": 0, "rank_detail": 0}

    def add(path: str, src: Path, priority: str, freq: str, kind: str):
        if not src.is_file():
            warnings.append(f"缺少 {src.relative_to(repo)}，跳过 {path}")
            return
        urls.append({
            "loc": SITE_URL + path,
            "lastmod": iso_mtime(src),
            "changefreq": freq,
            "priority": priority,
        })
        counts[kind] += 1

    add("/", repo / DATA_REL, "1.0", "daily", "home")
    add("/daily/", repo / "source/daily/index.html", "0.9", "daily", "daily")
    # RSS：全量流 + 三个分类流。feed.xml 是主订阅源，分类流按 lastmod 更新。
    for feed in ("feed.xml", "feed-oss.xml", "feed-tool.xml", "feed-model.xml"):
        add("/daily/" + feed, repo / "source/daily" / feed, "0.6", "daily", "feed")
    add("/rank/", repo / "source/rank/index.html", "0.8", "daily", "rank")

    rank_root = repo / "source" / "rank"
    if not rank_root.is_dir():
        warnings.append("source/rank/ 不存在，sitemap 只含首页与 /daily/")
    else:
        for p in sorted(rank_root.rglob("*.html")):
            rel = p.relative_to(rank_root).as_posix()
            if rel == "index.html":
                continue
            if rel.startswith("p/"):
                add("/rank/" + rel, p, "0.5", "weekly", "rank_detail")
            else:
                add("/rank/" + rel, p, "0.6", "weekly", "rank")

    # 去重（同一个 URL 只出现一次）
    seen: set[str] = set()
    unique = []
    for u in urls:
        if u["loc"] in seen:
            warnings.append(f"重复 URL 已合并：{u['loc']}")
            continue
        seen.add(u["loc"])
        unique.append(u)
    return unique, warnings, counts


def render_xml(urls: list[dict]) -> str:
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}urlset")
    for u in urls:
        node = ET.SubElement(root, f"{{{NS}}}url")
        for tag in ("loc", "lastmod", "changefreq", "priority"):
            ET.SubElement(node, f"{{{NS}}}{tag}").text = u[tag]
    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


def validate(xml_text: str, expected: int) -> list[str]:
    """产物自检：能被解析、URL 数正确、无重复、全部指向本站。"""
    root = ET.fromstring(xml_text)
    if root.tag != f"{{{NS}}}urlset":
        raise ValueError(f"根节点不是 urlset：{root.tag}")
    locs = [e.text or "" for e in root.iter(f"{{{NS}}}loc")]
    if len(locs) != expected:
        raise ValueError(f"URL 数不符：期望 {expected}，实际 {len(locs)}")
    if len(set(locs)) != len(locs):
        raise ValueError("sitemap 出现重复 URL")
    bad = [loc for loc in locs if not loc.startswith(SITE_URL + "/")]
    if bad:
        raise ValueError(f"存在非本站 URL：{bad[:3]}")
    for u in root.iter(f"{{{NS}}}url"):
        tags = {child.tag.split("}")[-1] for child in u}
        if not {"loc", "lastmod", "changefreq", "priority"}.issubset(tags):
            raise ValueError("url 节点缺少必需字段")
    return locs


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 cyberMap 的 robots.txt 与 sitemap.xml")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]),
                    help="仓库根目录（默认取脚本上级目录）")
    ap.add_argument("--check", action="store_true", help="只校验数据与产物，不写文件")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / DATA_REL).is_file():
        print(json.dumps({"ok": False, "error": f"找不到数据文件 {repo / DATA_REL}"},
                         ensure_ascii=False, indent=2))
        return 1

    try:
        urls, warnings, counts = collect(repo)
        if not urls:
            raise ValueError("没有可写入 sitemap 的 URL")
        xml_text = render_xml(urls)
        locs = validate(xml_text, len(urls))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    if args.check:
        print(json.dumps({
            "ok": True, "check_only": True, "urls": len(urls), "counts": counts,
            "first": locs[:3], "last": locs[-2:], "warnings": warnings,
            "would_write": [str(ROBOTS_REL), str(SITEMAP_REL)],
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        atomic_write(repo / SITEMAP_REL, xml_text)
        atomic_write(repo / ROBOTS_REL, ROBOTS_TEXT)
        # 回读校验，确认落盘内容就是刚校验过的那份
        validate((repo / SITEMAP_REL).read_text(encoding="utf-8"), len(urls))
        robots = (repo / ROBOTS_REL).read_text(encoding="utf-8")
        if f"Sitemap: {SITE_URL}/sitemap.xml" not in robots:
            raise ValueError("robots.txt 缺少 Sitemap 指令")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"写入失败：{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "ok": True, "urls": len(urls), "counts": counts, "warnings": warnings,
        "outputs": [str(ROBOTS_REL), str(SITEMAP_REL)],
        "sitemap_bytes": len(xml_text.encode("utf-8")),
        "robots_bytes": len(ROBOTS_TEXT.encode("utf-8")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
