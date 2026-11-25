/* ==========================================================================
   cyberMap · Redesign 交互增强
   --------------------------------------------------------------------------
   通过 source/_data/webstack.yml 的 custom.body 注入，位于 </body> 之前。
   只做「增强」：不接管搜索、锚点跳转、侧栏折叠、lozad 懒加载等主题原有逻辑。
   ========================================================================== */
(function () {
  'use strict';

  var REPO_URL = 'https://github.com/ohalo/cyberMap';
  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function svgPlaceholder(name) {
    var ch = (name || '?').trim().charAt(0).toUpperCase();
    ch = ch.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#06b6d4"/>' +
      '</linearGradient></defs>' +
      '<rect width="64" height="64" rx="16" fill="url(#g)"/>' +
      '<text x="32" y="43" text-anchor="middle" font-family="sans-serif" ' +
      'font-size="31" font-weight="700" fill="#ffffff">' + ch + '</text></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  /* 图标加载失败 → 生成首字母渐变占位图（捕获阶段，error 不冒泡） */
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || img.dataset.cmFallback) return;
    if (!img.classList.contains('lozad')) return;
    img.dataset.cmFallback = '1';
    var card = img.closest ? img.closest('.xe-widget') : null;
    var nameEl = card && card.querySelector('.xe-user-name');
    img.src = svgPlaceholder(nameEl ? nameEl.textContent : 'AI');
  }, true);

  /* ---- Footer 重设计（全站共用，不依赖 .main-content） ----
     主题 footer.pug 只输出一行朴素版权文字；这里在 DOM 就绪后把它替换成
     「品牌 + 导航 + 版权致谢」三段式。幂等：已有 .cm-footer 就跳过。
     保留原署名链接（ohalo / Viggo / Hexo / hexo-theme-webstack）与 go-up。 */
  function rebuildFooter() {
    var inner = document.querySelector('footer.main-footer .footer-inner');
    if (!inner || inner.querySelector('.cm-footer')) return;
    var oldP = inner.querySelector('p');
    if (!oldP) return;

    /* 从原段落抓取署名链接，尊重原作者署名、避免写死 URL */
    var credits = {};
    Array.prototype.forEach.call(oldP.querySelectorAll('a'), function (a) {
      var key = (a.textContent || '').trim();
      credits[key] = a.getAttribute('href') || '#';
    });
    var year = new Date().getFullYear();
    var authorHref = credits['ohalo'] || 'https://github.com/ohalo';
    var viggoHref = credits['Viggo'] || 'http://viggoz.com';
    var hexoHref = credits['Hexo'] || 'https://hexo.io/';
    var themeHref = credits['hexo-theme-webstack'] ||
      'https://github.com/HCLonely/hexo-theme-webstack/';

    /* 统计数字只在首页（有卡片）时渲染，其它页面自动省略 */
    var siteCount = document.querySelectorAll('.main-content .row > .col-sm-3').length;
    var catCount = document.querySelectorAll('.main-content h4.text-gray').length;
    var statsHtml = '';
    if (siteCount && catCount) {
      statsHtml = '<div class="cm-footer-stats">' +
        '<span><b>' + siteCount + '</b> 收录站点</span>' +
        '<span><b>' + catCount + '</b> 精选分类</span>' +
        '<span><b>每日</b> 自动更新</span></div>';
    }

    var html =
      '<div class="cm-footer">' +
        '<div class="cm-footer-top">' +
          '<div class="cm-footer-brand">' +
            '<a class="cm-footer-logo" href="/" aria-label="cyberMap 首页">' +
              '<span class="cm-footer-logo-mark" aria-hidden="true">' +
                '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" ' +
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                'stroke-linejoin="round"><circle cx="5" cy="6" r="2"/>' +
                '<circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/>' +
                '<path d="M6.7 7.3 10.6 16M17.3 7.3 13.4 16M7 6h10"/></svg>' +
              '</span>' +
              '<span class="cm-footer-logo-word">cyber<b>Map</b></span>' +
            '</a>' +
            '<p class="cm-footer-slogan">每日更新的 AI 工具与开源项目导航，' +
              '每一个链接都经过真实访问验证。</p>' +
            statsHtml +
          '</div>' +
          '<nav class="cm-footer-nav" aria-label="页脚导航">' +
            '<div class="cm-footer-col"><h5>浏览</h5>' +
              '<a href="/">全部站点</a>' +
              '<a href="/#aiChat">对话与搜索</a>' +
              '<a href="/#githubGPT">GitHub 项目</a>' +
              '<a href="/#studyGPT">提示词与教程</a></div>' +
            '<div class="cm-footer-col"><h5>站点功能</h5>' +
              '<a href="/rank/">AI 插件榜</a>' +
              '<a href="/daily/">每日速递</a>' +
              '<a href="/daily/feed.xml">RSS 订阅</a></div>' +
            '<div class="cm-footer-col"><h5>更多</h5>' +
              '<a href="/about/">关于本站</a>' +
              '<a href="' + REPO_URL + '" target="_blank" rel="noopener">GitHub</a>' +
              '<a href="/sitemap.xml">网站地图</a></div>' +
          '</nav>' +
        '</div>' +
        '<div class="cm-footer-bottom">' +
          '<div class="cm-footer-copy">© 2023 - ' + year + ' ' +
            '<a href="' + authorHref + '">ohalo</a> · 保留所有权利</div>' +
          '<div class="cm-footer-credit">' +
            'Design by <a href="' + viggoHref + '" target="_blank" rel="noopener">Viggo</a>' +
            ' · Powered by <a href="' + hexoHref + '" target="_blank" rel="noopener">Hexo</a>' +
            ' &amp; <a href="' + themeHref + '" target="_blank" rel="noopener">' +
            'hexo-theme-webstack</a></div>' +
        '</div>' +
      '</div>';

    var box = document.createElement('div');
    box.innerHTML = html;
    inner.insertBefore(box.firstChild, oldP);
    inner.removeChild(oldP);
  }

  /* ---- 站点新鲜度徽章（首页导航卡片）----
     读 /daily/updates.json 的 pushed_at，按与 /daily/ 页相同的阈值
     （7 天内活跃 / 90 天内近期 / 更久沉寂）给已跟踪 GitHub 项目在卡片
     右下角注入微徽章。无 pushed_at（未纳入雷达 / 非 GitHub）静默跳过，
     绝不把「没数据」误读成「沉寂」。网络失败同样静默降级。 */
  function normFreshUrl(raw) {
    try {
      var s = (raw || '').trim().replace(/[,;'\"]+$/, '');
      if (s.indexOf('://') < 0) s = 'https://' + s;
      var u = new URL(s);
      var host = (u.hostname || '').toLowerCase().replace(/^www\./, '');
      var path = (u.pathname || '/').replace(/\/+$/, '').toLowerCase() || '/';
      if (/\.git$/.test(path)) path = path.slice(0, -4);
      return host + path;
    } catch (e) { return ''; }
  }

  function freshCardUrl(widget) {
    var oc = widget.getAttribute('onclick') || '';
    var m = oc.match(/window\.open\(\s*['"]([^'"]+)['"]/);
    if (m) return m[1];
    return widget.getAttribute('data-original-title') || '';
  }

  function injectFreshnessBadges() {
    var widgets = Array.prototype.slice.call(
      document.querySelectorAll('.main-content .xe-widget'));
    if (!widgets.length || !window.fetch) return;
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 8000) : null;
    var opts = ctrl ? { signal: ctrl.signal, cache: 'no-store' } : { cache: 'no-store' };
    fetch('/daily/updates.json', opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (timer) clearTimeout(timer);
        if (!data || !data.repos) return;
        var now = new Date();
        var gen = data.generated_at ? new Date(data.generated_at) : null;
        /* 用雷达采集时间做基准，保证与 /daily/ 构建期判定一致、不随跨天漂移 */
        if (gen && !isNaN(gen.getTime())) now = gen;
        var repos = data.repos;
        widgets.forEach(function (w) {
          if (w.querySelector('.cm-fresh-badge')) return; /* 幂等 */
          var key = normFreshUrl(freshCardUrl(w));
          if (!key || !repos[key]) return;
          var rec = repos[key];
          if (!rec.pushed_at) return;
          var pushed = new Date(rec.pushed_at);
          if (isNaN(pushed.getTime())) return;
          var days = Math.max(0, Math.floor((now - pushed) / 86400000));
          var level, label;
          if (days < 7) {
            level = 'active'; label = '本周活跃';
          } else if (days < 90) {
            var mo = Math.floor(days / 30);
            level = 'recent';
            label = mo ? mo + ' 月前更新' : days + ' 天前更新';
          } else {
            level = 'idle';
            label = '沉寂 ' + Math.floor(days / 30) + ' 月';
          }
          var title = '最近提交：' + rec.pushed_at + '（距今约 ' + days + ' 天）；' +
            '雷达采集：' + (rec.last_checked || '—') + '。数据来自 /daily/updates.json，非实时。';
          var badge = document.createElement('span');
          badge.className = 'cm-fresh-badge ' + level;
          badge.appendChild(document.createElement('i'));
          badge.appendChild(document.createTextNode(label));
          badge.setAttribute('title', title);
          w.appendChild(badge);
        });
      })
      .catch(function () { /* 离线 / JSON 不可达：不显示徽章，不影响导航 */ });
  }

  /* ---- 设计稿 01 号板：顶栏导航 ----
     原主题顶栏在赛博态只露出右侧几个胶囊，左侧被原侧栏占住；02 号板里
     分类导航由 .cm-matrix-rail 承担，所以这里把顶栏补成设计稿的
     cyber MAP + 五个页面入口。原 switch-mode 节点不移动，经典态零改动。 */
  function injectDesignNav() {
    var ul = document.querySelector('.user-info-navbar .user-info-menu');
    if (!ul || ul.querySelector('.cm-site-brand')) return;
    var here = (location.pathname || '/').replace(/\/+$/, '') || '/';
    var LINKS = [
      ['/', '首页'], ['/daily/', '每日速递'], ['/rank/', '插件榜'],
      ['/data/', '开放数据'], ['/about/', '关于']
    ];
    var brand = el('li', 'cm-site-brand cm-design-only',
      '<a href="/" aria-label="cyberMap 首页">' +
      '<svg viewBox="0 0 32 32" aria-hidden="true">' +
      '<path d="M16 2 28 9v14l-12 7L4 23V9z" fill="none" stroke="currentColor" stroke-width="2"/>' +
      '<path d="M16 8 23 12v8l-7 4-7-4v-8z" fill="currentColor" opacity=".25"/></svg>' +
      '<b><i>cyber</i><em> MAP</em></b></a>');
    var links = el('li', 'cm-site-links cm-design-only', LINKS.map(function (pair) {
      var href = pair[0], path = href.replace(/\/+$/, '') || '/';
      var active = path === '/' ? here === '/' : here.indexOf(path) === 0;
      return '<a href="' + href + '"' + (active ? ' class="is-active"' : '') + '>' +
        pair[1] + '</a>';
    }).join(''));
    ul.insertBefore(brand, ul.firstChild);
    ul.insertBefore(links, brand.nextSibling);
  }

  /* ---- 设计稿 02 号板：AI 插件榜前置条 ----
     读 /rank/data/top100.json 的真实前 4 名；榜单是独立流水线产物，
     这里只读不写。网络失败静默隐藏，绝不编造数字。 */
  function injectRankPreview() {
    /* 设计稿 02 号板：榜单面板排在首个分类的卡片网格之后，而非首屏 HERO 里 */
    var firstHead = document.querySelector('.main-content h4.text-gray');
    var firstRow = firstHead && firstHead.nextElementSibling;
    while (firstRow && firstRow.tagName === 'BR') firstRow = firstRow.nextElementSibling;
    var anchor = (firstRow && firstRow.classList.contains('row'))
      ? firstRow : document.querySelector('.cm-feature-cta');
    if (!anchor || document.querySelector('.cm-rank-preview') || !window.fetch) return;
    var panel = el('section', 'cm-rank-preview cm-design-only',
      '<div class="cm-rank-head">' +
      '<div class="cm-rank-title">' +
      '<h3>AI 插件榜 · 实时 TOP</h3>' +
      '<span class="cm-rank-meta">UPDATED DAILY · TOP 100</span></div>' +
      '<a class="cm-rank-cta" href="/rank/" title="查看完整榜单">完整榜单 TOP 100</a>' +
      '</div><div class="cm-rank-rows"></div>');
    panel.style.display = 'none';
    anchor.parentNode.insertBefore(panel, anchor.nextSibling);

    var esc = function (s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    };
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 8000) : null;
    var opts = ctrl ? { signal: ctrl.signal, cache: 'no-store' } : { cache: 'no-store' };
    fetch('/rank/data/top100.json', opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (timer) clearTimeout(timer);
        var rows = (data && data.overall || []).slice(0, 4);
        if (!rows.length) return;
        var html = rows.map(function (r) {
          return '<div class="cm-rank-row">' +
            '<span class="rk">' + ('0' + r.rank).slice(-2) + '</span>' +
            '<span class="nm" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
            '<span class="ds" title="' + esc(r.description_zh || r.description) + '">' +
              esc(r.description_zh || r.description) + '</span>' +
            '<span class="sc">' + Number(r.score || 0).toFixed(1) + '</span>' +
            '</div>';
        }).join('');
        panel.querySelector('.cm-rank-rows').innerHTML = html;
        var meta = panel.querySelector('.cm-rank-meta');
        if (meta) {
          meta.textContent = 'UPDATED ' + esc(data.date) + ' · TOP 100';
        }
        panel.style.display = '';
      })
      .catch(function () { /* 榜单数据不可达：不展示占位面板 */ });
  }

  /* ---- LIVE 动态流：读 /daily/updates.json.recent 前 3 条项目动态 ----
     借鉴竞品（AIbase「AI今日要闻」/ ai-bot「最新收录」）把时效内容提到首屏。
     recent[i] 形如 { name, url, date, ... }（日期为发现日期）；网络失败静默隐藏，
     不影响导航。 */
  function injectLiveTicker() {
    var ticker = document.querySelector('.cm-console > .cm-ticker, .cyber-hero .cm-ticker');
    if (!ticker || ticker.dataset.cmLoaded || !window.fetch) return;
    ticker.dataset.cmLoaded = '1';
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 8000) : null;
    var opts = ctrl ? { signal: ctrl.signal, cache: 'no-store' } : { cache: 'no-store' };
    fetch('/daily/updates.json', opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (timer) clearTimeout(timer);
        var recent = (data && data.recent) || [];
        if (!recent.length) { ticker.style.display = 'none'; return; }
        var esc = function (s) {
          return String(s || '').replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
          });
        };
        var picks = recent.slice(0, 4);
        var items = picks.map(function (rec) {
          var what = rec.has_push ? '有新提交'
            : (rec.star_delta ? '+' + rec.star_delta + ' 星' : '纳入雷达追踪');
          return '<a href="' + esc(rec.url) + '" target="_blank" rel="noopener" ' +
            'title="项目动态 · 发现于 ' + esc(rec.date || '—') + '">' +
            '<b>' + esc(rec.name) + '</b> · ' + esc(what) + '</a>';
        }).join('');
        /* 设计稿 01 号板：LIVE 面板四行动态（经典态仍用原横向流，零改动） */
        var rows = picks.map(function (rec) {
          var kind = rec.has_push ? 'push' : (rec.star_delta ? 'star' : 'idle');
          var bits = [];
          if (rec.has_push) bits.push('新提交');
          if (rec.star_delta) bits.push('涨星 +' + Number(rec.star_delta).toLocaleString('en-US'));
          if (rec.stars) bits.push(Number(rec.stars).toLocaleString('en-US') + ' stars');
          if (!bits.length) bits.push('纳入雷达追踪');
          var day = String(rec.date || '').slice(5) || '—';
          return '<a class="cm-ticker-row" href="' + esc(rec.url) +
            '" target="_blank" rel="noopener" title="' + esc(rec.name) + ' · ' + day + '">' +
            '<span class="cm-ticker-dot ' + kind + '" aria-hidden="true"></span>' +
            '<span class="cm-ticker-name">' + esc(rec.name) + '</span>' +
            '<span class="cm-ticker-desc">' + esc(bits.join(' · ')) + '</span>' +
            '<span class="cm-ticker-date">' + esc(day) + '</span></a>';
        }).join('');
        ticker.innerHTML =
          '<div class="cm-ticker-strip">' +
          '<span class="cm-ticker-label"><i class="fas fa-satellite-dish" aria-hidden="true"></i>LIVE</span>' +
          '<div class="cm-ticker-items">' + items + '</div></div>' +
          '<div class="cm-ticker-panel cm-design-only">' +
          '<div class="cm-ticker-head"><span class="cm-live-badge">LIVE</span>' +
          '<span class="cm-ticker-title">项目动态速递 / 上游雷达</span>' +
          '<a class="cm-ticker-all" href="/daily/" title="查看全部项目动态">VIEW ALL →</a></div>' +
          '<div class="cm-ticker-rows">' + rows + '</div></div>';
      })
      .catch(function () {
        if (ticker) ticker.style.display = 'none';
      });
  }

  /* ---- 设计稿 02 号板：首页节点矩阵控制台 ----
     赛博态把「分类导航 + 当前分类状态 + 卡片网格 + 榜单前置条 + 最近节点」
     组织成设计稿的双栏控制台；经典态 wrapper/main 都是 display:contents，
     新增装饰节点默认隐藏，原主题 DOM 顺序与外观一字不改。 */
  function injectNodeMatrix(main, heads, cols) {
    if (!main || !heads.length || !cols.length || document.querySelector('.cm-matrix')) return;
    var firstHead = heads[0];
    var esc = function (s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    };
    var d0 = new Date();
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var today = d0.getFullYear() + '-' + pad(d0.getMonth() + 1) + '-' + pad(d0.getDate());

    var wrapper = el('div', 'cm-matrix');
    var hud = el('div', 'cm-matrix-hud cm-design-only',
      '<span class="cm-matrix-hud-dot" aria-hidden="true"></span>' +
      '<span class="cm-matrix-hud-title">SECTION 02 // NODE MATRIX</span>' +
      '<span class="cm-matrix-hud-right"><span class="cm-matrix-date">' + today +
      '</span> · VERIFIED ' + cols.length + ' · <span class="cm-matrix-clock">--:--:--</span></span>');
    var rail = el('div', 'cm-matrix-rail cm-design-only');
    var mainCol = el('div', 'cm-matrix-main');
    var foot = el('div', 'cm-matrix-foot cm-design-only',
      '<div class="cm-recent-nodes"><span class="cm-recent-label">RECENT NODES »</span>' +
      '<span class="cm-recent-items">加载中…</span></div>' +
      '<div class="cm-matrix-foot-note">cyberMap · 每日更新的 AI 工具与开源项目导航 · ' +
      '开放数据 <a href="/data/">/data/</a> · RSS ×6</div>' +
      '<a class="cm-scroll-hint" href="#cm-matrix-main">SCROLL ↓ 更多分类</a>');

    wrapper.appendChild(hud);
    wrapper.appendChild(rail);
    wrapper.appendChild(mainCol);
    wrapper.appendChild(foot);
    firstHead.parentNode.insertBefore(wrapper, firstHead);
    mainCol.id = 'cm-matrix-main';

    /* 设计稿 02 号板的三组分类：用真实站点数替换稿中的静态数字 */
    var GROUPS = [
      ['对话与创作', ['对话与搜索', '图像与设计', '视频与音频']],
      ['模型与开源', ['大语言模型', 'GitHub 项目', '智能体框架', 'RAG 与知识库']],
      ['工具箱', ['编程与开发', '办公与效率']]
    ];
    function rowOf(head) {
      var n = head.nextElementSibling;
      while (n && n.tagName === 'BR') n = n.nextElementSibling;
      return n && n.classList.contains('row') ? n : null;
    }
    function anchorOf(head) {
      var icon = head.querySelector('i.linecons-tag');
      if (!icon) return '';
      if (!icon.id) icon.id = 'cm-cat-' + heads.indexOf(head);
      return icon.id;
    }
    var railHtml = '';
    GROUPS.forEach(function (group) {
      railHtml += '<div class="cm-rail-group">' + esc(group[0]) + '</div>';
      group[1].forEach(function (label) {
        var head = null;
        for (var i = 0; i < heads.length; i++) {
          if ((heads[i].textContent || '').trim().indexOf(label) === 0) { head = heads[i]; break; }
        }
        if (!head) return;
        var row = rowOf(head);
        var count = row ? row.querySelectorAll('.col-sm-3').length : 0;
        var anchor = anchorOf(head);
        railHtml += '<a class="cm-rail-link' + (head === firstHead ? ' is-active' : '') +
          '" href="#' + esc(anchor) + '"><span>' + esc(label) + '</span><b>' + count + '</b></a>';
      });
    });
    railHtml += '<a class="cm-rail-more" href="/">+ ' + Math.max(0, heads.length - 9) +
      ' 个分类 · 查看全部</a>';
    rail.innerHTML = railHtml;

    var firstRow = rowOf(firstHead);
    var firstCount = firstRow ? firstRow.querySelectorAll('.col-sm-3').length : 0;
    var intro = el('div', 'cm-matrix-intro cm-design-only',
      '<div class="cm-matrix-kicker">// 02   BROWSE SECTORS</div>' +
      '<h2>浏览节点分类</h2>');
    var catbar = el('div', 'cm-matrix-catbar cm-design-only',
      '<span class="cm-cat-title">' + esc((firstHead.textContent || '').replace(/\d+\s*个站点/g, '').trim()) + '</span>' +
      '<span class="cm-cat-count">' + firstCount + ' NODES · 逐条核验</span>' +
      '<span class="cm-cat-filters">全部 / 已核验 / 本周活跃 / 开源优先</span>' +
      '<span class="cm-cat-sort">SORT: LATEST</span>');
    firstHead.classList.add('cm-first-head');
    mainCol.appendChild(intro);
    mainCol.appendChild(catbar);

    /* 把原主题的分类标题与卡片整体搬进 main 列；wrapper/main 在经典态是
       display:contents，因此这一步不会改变经典态的视觉顺序。 */
    var nodes = [];
    var node = firstHead;
    while (node) { nodes.push(node); node = node.nextElementSibling; }
    nodes.forEach(function (n) {
      if (n !== wrapper && n !== mainCol) mainCol.appendChild(n);
    });

    /* 最近节点：只展示真实雷达动态，失败时静默隐藏 */
    if (window.fetch) {
      var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 8000) : null;
      var opts = ctrl ? { signal: ctrl.signal, cache: 'no-store' } : { cache: 'no-store' };
      fetch('/daily/updates.json', opts)
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (timer) clearTimeout(timer);
          var recent = (data && data.recent) || [];
          var box = foot.querySelector('.cm-recent-items');
          if (!box) return;
          if (!recent.length) {
            var strip = foot.querySelector('.cm-recent-nodes');
            if (strip) strip.style.display = 'none';
            return;
          }
          box.textContent = recent.slice(0, 11).map(function (rec) {
            return rec.name;
          }).join(' · ') + ' …';
        })
        .catch(function () {
          var strip = foot.querySelector('.cm-recent-nodes');
          if (strip) strip.style.display = 'none';
        });
    }

    var clock = hud.querySelector('.cm-matrix-clock');
    if (clock) {
      var tick = function () {
        var d = new Date();
        clock.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
      };
      tick();
      setInterval(tick, 1000);
    }
  }

  function boot() {
    var main = document.querySelector('.main-content');
    if (!main) return;

    injectDesignNav();

    var heads = Array.prototype.slice.call(main.querySelectorAll('h4.text-gray'));
    var cols = Array.prototype.slice.call(main.querySelectorAll('.row > .col-sm-3'));

    /* ---- 1. 顶栏工具：侧栏收起/展开 + GitHub 按钮 + 外观切换器 ---- */
    var ul = document.querySelector('.user-info-navbar .user-info-menu');
    var switchItem = ul && ul.querySelector('li.switch-mode');
    if (ul) {
      /* 侧栏收起/展开（桌面端生效，移动端隐藏）
         主题自带的 a[data-toggle=sidebar] 会切 .sidebar-menu.collapsed，
         与新版固定侧栏布局冲突，这里改用 body.cm-collapsed 自管状态。 */
      var SIDE_KEY = 'cm-collapsed';
      var sideLi = ul.querySelector('.cyber-side-toggle-li');
      if (!sideLi) {
        sideLi = el('li', 'cyber-side-toggle-li hover-line');
        sideLi.appendChild(el('a', 'cyber-side-toggle',
          '<i class="fas fa-angle-left" aria-hidden="true"></i>'));
        /* 放在最左侧，紧贴侧栏边缘 */
        ul.insertBefore(sideLi, ul.firstChild);
      }
      var sideLink = sideLi.querySelector('a');
      function applyCollapsed(on) {
        document.body.classList.toggle('cm-collapsed', !!on);
        if (sideLink) {
          sideLink.innerHTML = '<i class="' +
            (on ? 'fas fa-angle-right' : 'fas fa-angle-left') +
            '" aria-hidden="true"></i>';
          sideLink.setAttribute('title', on ? '展开功能栏' : '收起功能栏');
          sideLink.setAttribute('aria-label', on ? '展开功能栏' : '收起功能栏');
          sideLink.setAttribute('aria-expanded', on ? 'false' : 'true');
        }
      }
      function syncCollapsed() {
        applyCollapsed(document.body.classList.contains('cm-collapsed'));
      }
      if (sideLink) {
        sideLink.addEventListener('click', function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          var next = !document.body.classList.contains('cm-collapsed');
          applyCollapsed(next);
          try { localStorage.setItem(SIDE_KEY, next ? '1' : '0'); } catch (e) {}
        });
        /* 恢复上次的收起状态（仅宽屏） */
        var saved = null;
        try { saved = localStorage.getItem(SIDE_KEY); } catch (e) {}
        if (saved === '1' && window.innerWidth >= 992) applyCollapsed(true);
        else syncCollapsed();
        /* 窄屏时始终展开，交给主题的抽屉式侧栏 */
        window.addEventListener('resize', function () {
          if (window.innerWidth < 992) {
            if (document.body.classList.contains('cm-collapsed')) {
              document.body.classList.remove('cm-collapsed');
              try { localStorage.setItem(SIDE_KEY, '0'); } catch (e) {}
            }
            syncCollapsed();
          }
        });
      }

      if (!ul.querySelector('.cyber-top-gh-li')) {
        var ghLi = el('li', 'cyber-top-gh-li hover-line');
        ghLi.appendChild(el('a', 'cyber-top-gh',
          '<i class="fab fa-github" aria-hidden="true"></i><span>GitHub</span>'));
        ghLi.firstChild.setAttribute('href', REPO_URL);
        ghLi.firstChild.setAttribute('target', '_blank');
        ghLi.firstChild.setAttribute('rel', 'noopener');
        ghLi.firstChild.setAttribute('title', '在 GitHub 查看 cyberMap 仓库');
        ul.insertBefore(ghLi, switchItem || null);
      }
      /* ---- 1.5 外观切换器：经典模式 CLASSIC / 赛博模式 CYBER ----
         保留主题 li.switch-mode 的 onclick='switchNightMode()'（切 body.night +
         写 night cookie），这里只把原来的太阳/月亮图标正名为显性的二选一控件：
           经典 = night=0 → 浅色靛蓝（原样式完整保留）
           赛博 = night=1 → 深色霓虹（CRT 扫描线 / HUD / LIVE 氛围层）
         两个分段都阻止冒泡，避免原点击被 li 的 onclick 无条件切换；
         真正需要切换时改为程序化 li.click()，只走一次主题函数。
         主题写的 cookie 不带 max-age（关浏览器即丢），这里补写一年有效期，
         保证「切到经典」的选择被长期记住。 */
      if (switchItem) {
        var modeLink = switchItem.querySelector('a');
        if (modeLink) {
          modeLink.classList.add('cm-skin');
          modeLink.setAttribute('href', '#');
          modeLink.innerHTML =
            '<span class="cm-skin-seg" data-skin="classic" role="button" tabindex="0" aria-pressed="false">' +
              '<i class="fas fa-sun" aria-hidden="true"></i>经典</span>' +
            '<span class="cm-skin-seg" data-skin="cyber" role="button" tabindex="0" aria-pressed="false">' +
              '<i class="fas fa-bolt" aria-hidden="true"></i>赛博</span>';
          modeLink.addEventListener('click', function (ev) { ev.preventDefault(); });

          var segs = modeLink.querySelectorAll('.cm-skin-seg');
          Array.prototype.forEach.call(segs, function (seg) {
            var wantCyber = seg.getAttribute('data-skin') === 'cyber';
            var pick = function (ev) {
              ev.preventDefault();
              ev.stopPropagation();
              var isCyber = document.body.classList.contains('night');
              if (wantCyber === isCyber) return;
              switchItem.click();  /* → 主题 switchNightMode()，body/cookie 同步 */
              document.cookie = (wantCyber ? 'night=1' : 'night=0') +
                ';path=/;max-age=31536000';  /* 补持久化，覆盖主题的无过期 cookie */
            };
            seg.addEventListener('click', pick);
            seg.addEventListener('keydown', function (ev) {
              if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); }
            });
          });

          var syncSkin = function () {
            var isCyber = document.body.classList.contains('night');
            Array.prototype.forEach.call(segs, function (seg) {
              var on = (seg.getAttribute('data-skin') === 'cyber') === isCyber;
              seg.classList.toggle('is-active', on);
              seg.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
            modeLink.setAttribute('title', isCyber
              ? '当前：赛博模式 CYBER · 点击「经典」切换'
              : '当前：经典模式 CLASSIC · 点击「赛博」切换');
            modeLink.setAttribute('aria-label', '外观切换：经典模式 / 赛博模式');
          };
          syncSkin();
          if (window.MutationObserver) {
            new MutationObserver(syncSkin).observe(document.body,
              { attributes: true, attributeFilter: ['class'] });
          }
          /* 从 /daily/ 或 /rank/ 切完返回时，cookie 可能已变而本页未重新加载 */
          window.addEventListener('focus', function () {
            var shouldCyber = /(?:^|;\s*)night=1(?:;|$)/.test(document.cookie);
            if (shouldCyber !== document.body.classList.contains('night')) {
              document.body.classList.toggle('night', shouldCyber);
            }
            syncSkin();
          });
        }
      }
    }

    /* ---- 2. 侧栏访问量 / 访客数统计（busuanzi）标记 ----
       主题把这两条塞在 .main-menu 最末，结构上和「分组标题」一样是
       `li > a > span`，会继承分组标题的胶囊底色与粗体；同时主题用
       float:right 靠右放数字，在 flex 父级下会换行并压住下一条统计。
       这里给这两条 li 打上 cm-stat 标记，由 CSS 单独排版。 */
    Array.prototype.forEach.call(
      document.querySelectorAll('#busuanzi_container_site_pv, #busuanzi_container_site_uv'),
      function (box) {
        var li = box.closest ? box.closest('li') : null;
        if (li) li.classList.add('cm-stat');
        var link = box.closest ? box.closest('a') : null;
        if (link) link.classList.add('cm-stat-link');
      });

    /* ---- 3. 侧栏锚点跳转：替换主题写死的 -30 偏移 ----
       主题 footer.js 里是 `$("html,body").animate({scrollTop: target.offset().top - 30})`，
       偏移量写死，标题会被顶栏盖住；这里改成按顶栏实际高度留白。 */
    (function bindSmoothScroll() {
      if (!window.jQuery) return;
      var $ = window.jQuery;
      function navOffset() {
        var nav = document.querySelector('.navbar.user-info-navbar');
        var h = nav ? Math.round(nav.getBoundingClientRect().height) : 52;
        return h + 16;
      }
      $('a.smooth').off('click');
      $('a.smooth').on('click', function (ev) {
        var href = $(this).attr('href') || '';
        if (href.charAt(0) !== '#') return;
        var target = document.getElementById(href.slice(1));
        if (!target) return;
        ev.preventDefault();
        /* 移动端顺手收起抽屉，行为与主题保持一致 */
        try {
          if (window.public_vars && public_vars.$mainMenu) {
            public_vars.$mainMenu.add(public_vars.$sidebarProfile)
              .toggleClass('mobile-is-visible');
          }
          if (typeof window.ps_destroy === 'function') window.ps_destroy();
        } catch (e) {}
        var top = target.getBoundingClientRect().top + window.pageYOffset - navOffset();
        $('html, body').animate({ scrollTop: top }, { duration: 420, easing: 'swing' });
      });
    })();

    /* ---- 3.5 设计稿 01 顶部 HUD 状态条（仅赛博态显示） ----
       文案与 01 号板逐字一致；指标里的节点数取页面真实卡片数，
       日期取当天，时钟与 Hero 时钟同源。经典态由 .cm-design-only 隐藏。 */
    (function injectHudBar() {
      if (document.querySelector('.cm-hudbar')) return;
      var container = document.querySelector('.page-container') || document.body;
      var d0 = new Date();
      var syncDate = d0.getFullYear() + '-' + ('0' + (d0.getMonth() + 1)).slice(-2) +
        '-' + ('0' + d0.getDate()).slice(-2);
      var bar = el('div', 'cm-hudbar cm-design-only',
        '<span class="cm-hudbar-dot" aria-hidden="true"></span>' +
        '<span class="cm-hudbar-status">SYSTEM ONLINE</span>' +
        '<span class="cm-hudbar-version">CYBERMAP // NODE_CONSOLE v2.6.11</span>' +
        '<span class="cm-hudbar-metrics">LAT 27.4ms · NODES ' + cols.length + '/' + cols.length +
          ' · SYNC ' + syncDate + '</span>' +
        '<span class="cm-hudbar-clock">--:--:--</span>' +
        '<span class="cm-hudbar-tz">UTC+8</span>');
      container.insertBefore(bar, container.firstChild);
    })();

    /* ---- 4. Hero 品牌区 + 实时统计 + HUD 时钟 ----
       设计稿落地（仅赛博态）：控制台双栏（左 搜索/快捷词/LIVE，右 节点雷达）、
       四格统计条、Orbitron 数字。经典态由 CSS 把 .cm-console 还原为
       display:contents、隐藏 .cm-design-only，原浅色布局与文案零改动。 */
    var sousuo = main.querySelector('section.sousuo');
    if (sousuo && !main.querySelector('.cyber-hero')) {
      var hero = el('div', 'cyber-hero',
        '<div class="cyber-kicker"><span>&#10022;</span> CYBERMAP · AI NAVIGATION</div>' +
        '<h1>发现好用的 <span class="cyber-gradient">AI 工具</span></h1>' +
        '<div class="cm-design-kicker cm-design-only">// 01   DISCOVER THE NETWORK</div>' +
        '<div class="cm-design-title cm-design-only">' +
        '<span class="cm-design-line1">发现好用的</span>' +
        '<span class="cm-design-line2"><b>AI</b><em>工具</em></span></div>' +
        '<p>接入 AI 网络节点 · 每日扫描收录 · 每条链接真实访问验证</p>' +
        '<div class="cm-hud">' +
        '<span class="cm-hud-dot" aria-hidden="true"></span>' +
        '<span>SYSTEM ONLINE</span>' +
        '<span class="cm-hud-meta cm-design-only">NODES ' + cols.length + '/' + cols.length +
          ' · HTTP VERIFIED · SYNC DAILY</span>' +
        '<span class="cm-hud-clock" id="cm-hud-clock">--:--:--</span>' +
        '</div>');
      var stats = el('div', 'cyber-stats');
      [
        [String(cols.length), '收录站点'],
        [String(heads.length), '精选分类'],
        ['每日', '自动更新']
      ].forEach(function (pair) {
        stats.appendChild(el('div', 'cyber-stat',
          '<strong>' + pair[0] + '</strong><span>' + pair[1] + '</span>'));
      });
      hero.appendChild(stats);

      /* 设计稿四格统计：今日新增从页面真实「· YYYY-MM-DD 收录」尾注统计 */
      var now = new Date();
      var dateKey = now.getFullYear() + '-' + ('0' + (now.getMonth() + 1)).slice(-2) +
        '-' + ('0' + now.getDate()).slice(-2);
      var todayCount = 0;
      cols.forEach(function (c) {
        if (c.textContent.indexOf('· ' + dateKey + ' 收录') >= 0) todayCount++;
      });
      var designStats = el('div', 'cm-design-stats cm-design-only');
      [
        [String(cols.length), '收录站点 / NODES'],
        [String(heads.length), '导航分类 / SECTORS'],
        ['+' + todayCount, '今日新增 / TODAY'],
        ['100%', '逐条访问核验 / VERIFIED']
      ].forEach(function (pair) {
        designStats.appendChild(el('div', 'cm-design-stat',
          '<strong>' + pair[0] + '</strong><span>' + pair[1] + '</span>'));
      });

      /* 控制台容器：hero + 原搜索框 + 快捷词 + LIVE + 雷达 + 底部统计条 */
      var consoleBox = el('div', 'cm-console');
      consoleBox.appendChild(hero);
      /* LIVE 容器在 DOM 里紧跟 hero（经典态顺序与改造前一致），
         赛博态再由 grid-row 排到搜索框之后 */
      var liveTickerBox = el('div', 'cm-ticker', '');
      consoleBox.appendChild(liveTickerBox);
      var searchSection = sousuo.querySelector('.search');
      if (searchSection) consoleBox.appendChild(searchSection);

      var QUICK = [
        ['图像生成', ['图像', '设计', '生图', '绘画']],
        ['智能体框架', ['智能体', 'agent', '框架']],
        ['本地推理', ['本地', '推理', 'gguf', 'ollama', 'lm studio']],
        ['RAG 检索', ['rag', '知识库', '检索']],
        ['视频生成', ['视频', '剪辑', '动画']]
      ];
      var quick = el('div', 'cm-quick cm-design-only');
      quick.innerHTML =
        '<div class="cm-quick-label">QUICK ACCESS // 热门检索</div>' +
        '<div class="cm-quick-row">' + QUICK.map(function (q, i) {
          return '<button type="button" class="cm-quick-chip" data-qi="' + i +
            '"># ' + q[0] + '</button>';
        }).join('') + '</div>' +
        '<div class="cm-filter-status" aria-live="polite"></div>';
      consoleBox.appendChild(quick);
      /* 设计稿底部统计条：独立成行，横贯双栏（经典态隐藏） */
      consoleBox.appendChild(designStats);

      /* 节点拓扑雷达：静态 SVG，中心数字取真实站点数 */
      consoleBox.appendChild(el('div', 'cm-radar cm-design-only',
        '<div class="cm-radar-head"><span>NETWORK MAP / 节点拓扑</span>' +
        '<span class="cm-radar-live">SCANNING · LIVE</span></div>' +
        '<svg viewBox="0 0 480 440" role="img" aria-label="节点拓扑雷达">' +
        '<g stroke="#00e5ff" stroke-opacity="0.22" fill="none">' +
        '<circle cx="240" cy="220" r="205"/><circle cx="240" cy="220" r="154"/>' +
        '<circle cx="240" cy="220" r="103"/><circle cx="240" cy="220" r="52"/>' +
        '<path d="M15 220 H465 M240 15 V425"/></g>' +
        '<g class="cm-radar-sweep"><path d="M240 220 L240 15 A205 205 0 0 1 385 75 Z" ' +
        'fill="#00e5ff" fill-opacity="0.10"/></g>' +
        '<g stroke="#00e5ff" stroke-opacity="0.45" fill="none">' +
        '<path d="M240 220 L390 108 M240 220 L348 356 M240 220 L92 322 M240 220 L118 96"/></g>' +
        '<g fill="#00e5ff"><circle cx="390" cy="108" r="5"/><circle cx="348" cy="356" r="4"/>' +
        '<circle cx="92" cy="322" r="4"/><circle cx="118" cy="96" r="3"/>' +
        '<circle cx="240" cy="220" r="6"/></g>' +
        '<g fill="#ff2ea6"><circle cx="405" cy="280" r="4"/><circle cx="148" cy="380" r="3"/></g>' +
        '<text class="cm-radar-num" x="240" y="216" text-anchor="middle">' + cols.length + '</text>' +
        '<text class="cm-radar-num-label" x="240" y="240" text-anchor="middle">NODES ONLINE</text>' +
        '</svg>' +
        '<div class="cm-radar-foot">' + heads.length +
          ' 分类 · 4 分组 · 逐条 HTTP 核验 · 每日自动重扫</div>'));
      sousuo.insertBefore(consoleBox, sousuo.firstChild);

      /* 快捷词：本地筛选已渲染的站点卡，不劫持主题的外部搜索按钮 */
      (function bindQuickFilter() {
        var status = quick.querySelector('.cm-filter-status');
        var chips = quick.querySelectorAll('.cm-quick-chip');
        function rowOf(head) {
          var n = head.nextElementSibling;
          while (n && n.tagName === 'BR') n = n.nextElementSibling;
          return n && n.classList.contains('row') ? n : null;
        }
        Array.prototype.forEach.call(chips, function (chip) {
          chip.addEventListener('click', function () {
            var idx = Number(chip.getAttribute('data-qi'));
            var active = chip.classList.contains('is-active');
            Array.prototype.forEach.call(chips, function (c) { c.classList.remove('is-active'); });
            if (active) {
              cols.forEach(function (c) { c.style.display = ''; });
              heads.forEach(function (h) {
                h.style.display = '';
                var r = rowOf(h); if (r) r.style.display = '';
              });
              if (status) status.textContent = '';
              return;
            }
            chip.classList.add('is-active');
            var words = QUICK[idx][1];
            var hit = 0;
            cols.forEach(function (c) {
              var text = c.textContent.toLowerCase();
              var match = words.some(function (w) { return text.indexOf(w) >= 0; });
              c.style.display = match ? '' : 'none';
              if (match) hit++;
            });
            heads.forEach(function (h) {
              var r = rowOf(h);
              var shown = r ? Array.prototype.some.call(
                r.querySelectorAll('.col-sm-3'), function (c) { return c.style.display !== 'none'; }
              ) : false;
              h.style.display = shown ? '' : 'none';
              if (r) r.style.display = shown ? '' : 'none';
            });
            if (status) {
              status.textContent = '筛选：' + QUICK[idx][0] +
                ' · 命中 ' + hit + ' 个节点 · 再次点击取消';
            }
          });
        });
      })();

      /* 占位文案：赛博态强调站内节点，切回经典态恢复原文案 */
      var input = sousuo.querySelector('#txt');
      var originalPh = input ? input.getAttribute('placeholder') : '';
      var cyberPh = '搜索 ' + cols.length + ' 个节点，或描述你想完成的任务…';
      var searchBtn = sousuo.querySelector('#search-btn');
      var originalBtn = searchBtn ? searchBtn.innerHTML : '';
      function syncPlaceholder() {
        var cyber = document.body.classList.contains('night');
        if (input) input.setAttribute('placeholder', cyber ? cyberPh : originalPh);
        /* 设计稿按钮文案 SEARCH ↵；经典态严格还原主题原按钮 */
        if (searchBtn) searchBtn.innerHTML = cyber
          ? '<span class="cm-search-label">SEARCH ↵</span>' : originalBtn;
      }
      syncPlaceholder();
      if (window.MutationObserver) {
        new MutationObserver(syncPlaceholder).observe(document.body,
          { attributes: true, attributeFilter: ['class'] });
      }
      /* HUD 时钟：HH:MM:SS，每秒走字 */
      var clockEl = hero.querySelector('#cm-hud-clock');
      if (clockEl) {
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        var barClock = document.querySelector('.cm-hudbar-clock');
        var tick = function () {
          var d = new Date();
          var time = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
          clockEl.textContent = time;
          if (barClock) barClock.textContent = time;
        };
        tick();
        setInterval(tick, 1000);
      }
    }

    /* ---- 5. 分组标题加站点计数徽章 ---- */
    heads.forEach(function (h) {
      if (h.querySelector('.cyber-count')) return;
      var node = h.nextElementSibling;
      while (node && node.tagName === 'BR') node = node.nextElementSibling;
      if (!node || !node.classList.contains('row')) return;
      var n = node.querySelectorAll('.col-sm-3').length;
      h.appendChild(el('span', 'cyber-count', n + ' 个站点'));
    });

    /* ---- 6. 滚动时高亮侧栏当前分组 ---- */
    var links = Array.prototype.slice.call(
      document.querySelectorAll('#main-menu a.smooth, .cm-rail-link'));
    var currentId = null;
    function updateActive() {
      var found = null;
      for (var i = 0; i < heads.length; i++) {
        var icon = heads[i].querySelector('i.linecons-tag');
        if (!icon || !icon.id) continue;
        if (heads[i].getBoundingClientRect().top <= 118) found = icon.id;
      }
      if (found === currentId) return;
      currentId = found;
      links.forEach(function (a) {
        a.classList.toggle('cyber-active',
          !!found && a.getAttribute('href') === '#' + found);
      });
    }
    var ticking = false;
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () { updateActive(); ticking = false; });
    }, { passive: true });
    window.addEventListener('resize', updateActive, { passive: true });
    updateActive();

    /* ---- 7. 卡片入场动画（带兜底，绝不留下隐藏卡片） ---- */
    if (!reduceMotion && 'IntersectionObserver' in window && cols.length) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        });
      }, { rootMargin: '0px 0px 80px 0px', threshold: 0.02 });
      cols.forEach(function (c) { c.classList.add('cyber-reveal'); io.observe(c); });
      window.setTimeout(function () {
        cols.forEach(function (c) { c.classList.add('is-visible'); });
      }, 2200);
    }

    /* ---- 8. 站点功能入口 · AI 插件排行榜 ----
       刻意不写进 webstack.yml 的 menu:：那边全是「#锚点 + 网址卡片」，
       榜单是会跳到独立页面的站点级工具，混进去会被当成第 6 个父分类。
       这里放在分类树之外的三处，视觉上用强调色胶囊 / 卡片 + 显式标题隔离。 */
    (function injectRankEntries() {
      var RANK = '/rank/';
      var PLATFORMS = [
        ['codex', 'Codex 分榜', 'fas fa-terminal'],
        ['claude_code', 'Claude Code', 'fas fa-code'],
        ['dsh', 'dsh 分榜', 'fas fa-bolt'],
        ['workbuddy', 'WorkBuddy', 'fas fa-layer-group']
      ];

      /* 8.1 顶栏常驻主按钮：插在 GitHub 之前（GitHub 带 margin-left:auto 靠右） */
      var ul2 = document.querySelector('.user-info-navbar .user-info-menu');
      if (ul2 && !ul2.querySelector('.cm-rank-li')) {
        var li = el('li', 'cm-rank-li hover-line');
        li.appendChild(el('a', 'cm-rank-btn',
          '<i class="fas fa-trophy" aria-hidden="true"></i><span>AI 插件榜</span>' +
          '<span class="cm-rank-pill">Top 100</span>'));
        var rankLink = li.firstChild;
        rankLink.setAttribute('href', RANK);
        rankLink.setAttribute('title', 'AI 插件排行榜 · 每日 08:00 自动更新');
        rankLink.setAttribute('aria-label', '打开 AI 插件排行榜');
        var ghLi = ul2.querySelector('.cyber-top-gh-li');
        ul2.insertBefore(li, ghLi || ul2.querySelector('li.switch-mode') || null);
      }

      /* 8.1b 顶栏次按钮：每日 AI 速递（/daily/ 时间轴 + RSS） */
      if (ul2 && !ul2.querySelector('.cm-daily-li')) {
        var dLi = el('li', 'cm-daily-li hover-line');
        dLi.appendChild(el('a', 'cm-daily-btn',
          '<i class="fas fa-rss" aria-hidden="true"></i><span>AI 速递</span>'));
        var dLink = dLi.firstChild;
        dLink.setAttribute('href', '/daily/');
        dLink.setAttribute('title', '每日 AI 新发现 · 时间轴与 RSS 订阅');
        dLink.setAttribute('aria-label', '打开每日 AI 速递');
        var ghLi2 = ul2.querySelector('.cyber-top-gh-li');
        ul2.insertBefore(dLi, ghLi2 || ul2.querySelector('li.switch-mode') || null);
      }

      /* 8.2 侧栏：#main-menu 之前的独立面板，不参与锚点高亮 */
      var inner = document.querySelector('.sidebar-menu .sidebar-menu-inner');
      var menu = document.getElementById('main-menu');
      if (inner && menu && !inner.querySelector('.cm-features')) {
        var chips = PLATFORMS.map(function (p) {
          return '<a class="cm-feature-chip" href="' + RANK + '?platform=' + p[0] +
            '" title="' + p[1] + '"><i class="' + p[2] + '" aria-hidden="true"></i>' + p[1] + '</a>';
        }).join('') +
          '<a class="cm-feature-chip" href="' + RANK + 'marketplace.html" title="官方市场目录">' +
          '<i class="fas fa-store" aria-hidden="true"></i>官方市场</a>' +
          '<a class="cm-feature-chip" href="' + RANK + 'methodology.html" title="算法与数据口径">' +
          '<i class="fas fa-balance-scale" aria-hidden="true"></i>评分口径</a>' +
          '<a class="cm-feature-chip" href="/daily/" title="每日 AI 新发现时间轴">' +
          '<i class="fas fa-rss" aria-hidden="true"></i>每日速递</a>';
        var panel = el('div', 'cm-features',
          '<div class="cm-features-label"><span>站点功能</span>' +
          '<span class="cm-features-sep"></span><span class="cm-features-hint">非网址分类</span></div>' +
          '<a class="cm-feature-main" href="' + RANK + '" title="AI 插件排行榜总榜 Top 100">' +
          '<i class="fas fa-trophy" aria-hidden="true"></i>' +
          '<span class="cm-feature-main-txt">AI 插件排行榜<small>每日 08:00 自动更新</small></span>' +
          '<span class="cm-feature-arrow">›</span></a>' +
          '<div class="cm-feature-chips">' + chips + '</div>' +
          '<div class="cm-features-note">榜单是独立页面，不属于下方网址分类；' +
          '数据来自 GitHub / npm 公开 API，逐条可核验。</div>');
        inner.insertBefore(panel, menu);
      }

      /* 8.3 首页 CTA：搜索区之后、第一个分类卡片之前 */
      var sousuo2 = main.querySelector('section.sousuo');
      if (sousuo2 && !main.querySelector('.cm-feature-cta')) {
        var cta = el('div', 'cm-feature-cta',
          '<div class="cm-cta-icon"><i class="fas fa-trophy" aria-hidden="true"></i></div>' +
          '<div class="cm-cta-text">' +
          '<span class="cm-cta-tag">站点功能 · 非网址分类</span>' +
          '<strong>AI 插件排行榜</strong>' +
          '<span class="cm-cta-desc">Codex / Claude Code / dsh / WorkBuddy 生态 · ' +
          '总榜与各分榜各取前 100 · 每日 08:00 更新</span>' +
          '</div>' +
          '<div class="cm-cta-links">' +
          '<a class="cm-cta-link primary" href="' + RANK + '">查看总榜 →</a>' +
          '<a class="cm-cta-link" href="' + RANK + '?platform=codex">平台分榜</a>' +
          '<a class="cm-cta-link" href="' + RANK + 'marketplace.html">官方市场</a>' +
          '<a class="cm-cta-link" href="' + RANK + 'methodology.html">评分口径</a>' +
          '<a class="cm-cta-link" href="/daily/">每日 AI 速递</a>' +
          '</div>');
        sousuo2.parentNode.insertBefore(cta, sousuo2.nextSibling);
      }
    })();

    /* ---- 9. 站点新鲜度徽章：异步注入，失败不影响导航渲染 ---- */
    injectFreshnessBadges();

    /* ---- 10. LIVE 项目动态流：异步填充，失败静默隐藏 ---- */
    injectLiveTicker();

    /* ---- 11. 设计稿榜单前置条：异步读真实 Top 4，失败静默隐藏 ---- */
    injectRankPreview();

    /* ---- 12. 设计稿 02 号板：分类矩阵控制台（最后搬运，保留榜单前置条位置） ---- */
    injectNodeMatrix(main, heads, cols);
  }

  function start() {
    rebuildFooter(); /* 全站 footer，不依赖 .main-content */
    boot();          /* 首页专属增强，缺 .main-content 时自行返回 */
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
