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

    /* ---- 4. Hero 品牌区 + 实时统计 ---- */
    var sousuo = main.querySelector('section.sousuo');
    if (sousuo && !main.querySelector('.cyber-hero')) {
      var hero = el('div', 'cyber-hero',
        '<div class="cyber-kicker"><span>&#10022;</span> CYBERMAP · AI NAVIGATION</div>' +
        '<h1>发现好用的 <span class="cyber-gradient">AI 工具</span></h1>' +
        '<p>精选 AI 网站、开源项目与模型资源，每个链接都经过真实访问验证 · 每日自动收录</p>');
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
      sousuo.insertBefore(hero, sousuo.firstChild);
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
