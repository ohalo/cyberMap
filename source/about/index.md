---
layout: page
type: about
title: 关于本站
lang: zh-CN
tittle: "关于本站 · cyberMap"
subtitle: AI 工具与开源项目导航
description: "关于 cyberMap —— 每日更新的 AI 工具与开源项目导航站，含每日 AI 速递质量回执与 AI 插件排行榜。"
keywords: "关于本站,cyberMap,AI 导航,AI 工具,开源项目"
custom:
  head: |-
    <!-- about 页沿用 cyberMap 全部自定义样式（page.custom 覆盖 theme.custom） -->
    <link rel="stylesheet" href="/css/cybermap.css">
    <script>
    (function () {
      var p = location.pathname.replace(/index\.html$/, '');
      var canonical = 'https://cybermap.halo26812.eu.org' + p;
      var link = document.createElement('link');
      link.rel = 'canonical'; link.href = canonical;
      document.head.appendChild(link);
      var og = document.querySelector('meta[property="og:url"]');
      if (og) og.setAttribute('content', canonical);
    })();
    </script>
    <script>
    (function () {
      var base = 'https://cybermap.halo26812.eu.org';
      [['x-default', base + '/']].forEach(function (pair) {
        var l = document.createElement('link');
        l.rel = 'alternate'; l.hreflang = pair[0]; l.href = pair[1];
        document.head.appendChild(l);
      });
    })();
    </script>
    <link rel="alternate" type="application/rss+xml" title="cyberMap 每日 AI 速递" href="/daily/feed.xml">
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"AboutPage","name":"关于 cyberMap","url":"https://cybermap.halo26812.eu.org/about/","inLanguage":"zh-CN"}
    </script>
  body: |-
    <script src="/js/cybermap.js"></script>
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-YGLB3LVYFC"></script>
    <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-YGLB3LVYFC');
    </script>
---
