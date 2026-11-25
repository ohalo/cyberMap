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

  /* ---- LIVE 动态流：读 /daily/updates.json.recent 前 3 条项目动态 ----
     借鉴竞品（AIbase「AI今日要闻」/ ai-bot「最新收录」）把时效内容提到首屏。
     recent[i] 形如 { name, url, date, ... }（日期为发现日期）；网络失败静默隐藏，
     不影响导航。 */
  function injectLiveTicker() {
    var ticker = document.querySelector('.cyber-hero .cm-ticker');
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
        var items = recent.slice(0, 3).map(function (rec) {
          var what = rec.has_push ? '有新提交'
            : (rec.star_delta ? '+' + rec.star_delta + ' 星' : '纳入雷达追踪');
          return '<a href="' + esc(rec.url) + '" target="_blank" rel="noopener" ' +
            'title="项目动态 · 发现于 ' + esc(rec.date || '—') + '">' +
            '<b>' + esc(rec.name) + '</b> · ' + esc(what) + '</a>';
        }).join('');
        ticker.innerHTML =
          '<span class="cm-ticker-label"><i class="fas fa-satellite-dish" aria-hidden="true"></i>LIVE</span>' +
          '<div class="cm-ticker-items">' + items + '</div>';
      })
      .catch(function () {
        if (ticker) ticker.style.display = 'none';
      });
  }

  function boot() {
    var main = document.querySelector('.main-content');
    if (!main) return;

    var heads = Array.prototype.slice.call(main.querySelectorAll('h4.text-gray'));
    var cols = Array.prototype.slice.call(main.querySelectorAll('.row > .col-sm-3'));

    /* ---- 1. 顶栏工具：侧栏收起/展开 + GitHub 按钮 + 主题切换文案 ---- */
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
      if (switchItem) {
        var modeLink = switchItem.querySelector('a');
        if (modeLink) {
          modeLink.addEventListener('click', function (ev) { ev.preventDefault(); });
          var lastDark = null;
          var syncMode = function () {
            var dark = document.body.classList.contains('night');
            if (dark === lastDark) return;
            lastDark = dark;
            modeLink.innerHTML = '<i class="' + (dark ? 'fas fa-sun' : 'fas fa-moon') +
              '" aria-hidden="true"></i><span class="cyber-mode-label">' +
              (dark ? '浅色' : '深色') + '</span>';
            modeLink.setAttribute('title', dark ? '切换到浅色模式' : '切换到深色模式');
          };
          syncMode();
          if (window.MutationObserver) {
            new MutationObserver(syncMode).observe(document.body,
              { attributes: true, attributeFilter: ['class'] });
          }
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

    /* ---- 4. Hero 品牌区 + 实时统计 + HUD 时钟 ---- */
    var sousuo = main.querySelector('section.sousuo');
    if (sousuo && !main.querySelector('.cyber-hero')) {
      var hero = el('div', 'cyber-hero',
        '<div class="cyber-kicker"><span>&#10022;</span> CYBERMAP · AI NAVIGATION</div>' +
        '<h1>发现好用的 <span class="cyber-gradient">AI 工具</span></h1>' +
        '<p>接入 AI 网络节点 · 每日扫描收录 · 每条链接真实访问验证</p>' +
        '<div class="cm-hud">' +
        '<span class="cm-hud-dot" aria-hidden="true"></span>' +
        '<span>SYSTEM ONLINE</span>' +
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
      /* LIVE 动态流容器：由 injectLiveTicker 异步填充（竞品借鉴：时效内容前置） */
      hero.appendChild(el('div', 'cm-ticker', ''));
      sousuo.insertBefore(hero, sousuo.firstChild);
      /* HUD 时钟：HH:MM:SS，每秒走字 */
      var clockEl = hero.querySelector('#cm-hud-clock');
      if (clockEl) {
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        var tick = function () {
          var d = new Date();
          clockEl.textContent = pad(d.getHours()) + ':' +
            pad(d.getMinutes()) + ':' + pad(d.getSeconds());
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
      document.querySelectorAll('#main-menu a.smooth'));
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
