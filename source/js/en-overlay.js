/* ==========================================================================
   cyberMap 英文页文案覆盖（仅 source/en/ 子页面加载）
   --------------------------------------------------------------------------
   webstack 主题与 cybermap.js 里有多处硬编码中文，本脚本在它们之后运行，
   把 DOM 里残留的中文 UI 文案替换为英文。只替换文本节点，不动数据与链接。
   加载顺序（英文页 custom.body）：cybermap.js → en-overlay.js。
   ========================================================================== */
(function () {
  'use strict';

  /* 精确短语映射：中文原文 → 英文。按长度降序，避免短词先替换破坏长词。 */
  var PHRASES = [
    ['发现好用的', 'Discover great'],
    ['AI 工具', 'AI Tools'],
    ['精选 AI 网站、开源项目与模型资源，每个链接都经过真实访问验证 · 每日自动收录',
     'Handpicked AI sites, open-source projects and model resources. Every link is verified and added daily.'],
    ['请输入关键字，按回车 / Enter 搜索', 'Enter a keyword and press Enter to search'],
    ['选择您的默认搜索引擎：', 'Choose your default search engine:'],
    ['搜索热词：', 'Trending:'],
    ['本站总访问量', 'Total visits'],
    ['本站总访客数', 'Total visitors'],
    ['收录站点', 'Sites'],
    ['精选分类', 'Categories'],
    ['自动更新', 'Auto-updated daily'],
    ['个站点', ' sites'],
    ['站点导航', 'Site nav'],
    ['总榜分类', 'Top categories'],
    ['AI 插件排行榜', 'AI Plugin Leaderboard'],
    ['AI 插件榜', 'AI Plugin Ranking'],
    ['AI 速递', 'AI Digest'],
    ['Codex 分榜', 'Codex'],
    ['dsh 分榜', 'dsh'],
    ['官方市场', 'Marketplace'],
    ['评分口径', 'Methodology'],
    ['每日速递', 'Daily Digest'],
    ['站点功能 · 非网址分类', 'Site Features · Tools, not links'],
    ['WorkBuddy 生态', 'WorkBuddy ecosystem'],
    ['站点功能', 'Site Features'],
    ['非网址分类', 'Tools, not links'],
    ['查看总榜 →', 'View leaderboard →'],
    ['平台分榜', 'Platforms'],
    ['每日 AI 速递', 'Daily AI Digest'],
    ['每日 08:00 自动更新', 'Updated daily at 08:00'],
    ['每日 08:00 更新', 'Updated daily 08:00'],
    ['每日更新', 'Daily update'],
    ['每日', 'Daily'],
    ['总榜与各分榜各取前 100', 'Top 100 in overall and each platform'],
    ['榜单是独立页面，不属于下方网址分类；', 'The leaderboard is a standalone page, not a link category;'],
    ['数据来自 GitHub / npm 公开 API，逐条可核验。', 'Data from public GitHub / npm APIs, verifiable item by item.'],
    ['打开 AI 插件排行榜', 'Open the AI Plugin Leaderboard'],
    ['打开每日 AI 速递', 'Open the Daily AI Digest'],
    ['算法与数据口径', 'Algorithm and data methodology'],
    ['每日 AI 新发现时间轴', 'Daily AI discoveries timeline'],
    ['AI 插件排行榜总榜 Top 100', 'AI Plugin Leaderboard - Overall Top 100'],
    ['每日 AI 新发现 · 时间轴与 RSS 订阅', 'Daily AI discoveries - timeline and RSS'],
    ['关于本站', 'About'],
    ['彷徨的蜗牛', 'Wandering Snail'],
    ['寻找方向', 'In search of direction']
  ].sort(function (a, b) { return b[0].length - a[0].length; });

  function translateText(s) {
    if (!s) return s;
    var out = s;
    for (var i = 0; i < PHRASES.length; i++) {
      if (out.indexOf(PHRASES[i][0]) !== -1) {
        out = out.split(PHRASES[i][0]).join(PHRASES[i][1]);
      }
    }
    return out;
  }

  /* 处理一个根节点的文本节点与属性 */
  function sweep(root) {
    if (!root || !root.querySelectorAll) return;
    // 文本节点
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var node;
    while ((node = walker.nextNode())) {
      var t = node.nodeValue;
      if (!t || t.indexOf('中') < 0 && t.indexOf('每') < 0 && t.indexOf('站') < 0 &&
          t.indexOf('搜') < 0 && t.indexOf('分') < 0 && t.indexOf('AI') < 0) {
        // 快速跳过明显不含目标短语的节点（仍可能因 AI 误入，translateText 会兜底）
        var changed0 = translateText(t);
        if (changed0 === t) continue;
      }
      var nt = translateText(t);
      if (nt !== t) node.nodeValue = nt;
    }
    // 常见属性：placeholder / title / aria-label / data-original-title
    var els = root.querySelectorAll('[placeholder],[title],[aria-label],[data-original-title]');
    for (var i = 0; i < els.length; i++) {
      ['placeholder', 'title', 'aria-label', 'data-original-title'].forEach(function (a) {
        var v = els[i].getAttribute(a);
        if (v) {
          var nv = translateText(v);
          if (nv !== v) els[i].setAttribute(a, nv);
        }
      });
    }
  }

  function run() { sweep(document.body); }

  // 首屏：DOMContentLoaded 后跑，确保 cybermap.js 的注入已完成
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setTimeout(run, 0);
    });
  } else {
    setTimeout(run, 0);
  }
  // 兜底：再延迟一次覆盖任何异步注入
  setTimeout(run, 600);

  /* 监听后续 DOM 变化（如 cybermap.js 二次注入），限频 */
  var timer = null;
  var mo = new MutationObserver(function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; sweep(document.body); }, 150);
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });
})();
