/* ==========================================================================
   AI 插件排行榜 · 中英双语切换
   --------------------------------------------------------------------------
   1) 语言偏好存 localStorage（键 rank_lang），默认中文；
   2) 在 <head> 同步执行，尽早写入 <html lang>，避免语言闪烁（FOUC）；
   3) 文本显隐由 CSS 按 html[lang] 控制（.i18n-zh / .i18n-en）；
   4) 动态渲染的列表页/市场页通过 window.RANK_I18N.on(cb) 在切换时重绘；
   5) 顶栏有 #cm-rank-lang 按钮则绑定；独立站无顶栏时自动注入浮动按钮。
   不依赖 jQuery；与主题（night cookie）互不干扰。
   ========================================================================== */
(function () {
  'use strict';

  var KEY = 'rank_lang';

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return v === 'en' ? 'en' : 'zh';
    } catch (e) { return 'zh'; }
  }

  function write(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) { /* file:// 或隐私模式忽略 */ }
  }

  function apply(lang) {
    var en = lang === 'en';
    var root = document.documentElement;
    root.lang = en ? 'en' : 'zh-CN';
    root.setAttribute('data-lang', en ? 'en' : 'zh');

    // <title data-zh data-en> 动态切换
    var t = document.querySelector('title[data-zh]');
    if (t) t.textContent = t.getAttribute(en ? 'data-en' : 'data-zh') || t.textContent;

    // meta description 同样支持双语
    var metas = document.querySelectorAll('meta[data-zh][data-en]');
    for (var i = 0; i < metas.length; i++) {
      var m = metas[i];
      m.setAttribute('content', m.getAttribute(en ? 'data-en' : 'data-zh') || m.getAttribute('content'));
    }

    if (window.RANK_I18N) {
      window.RANK_I18N.lang = lang;
      var cbs = window.RANK_I18N._cb || [];
      for (var j = 0; j < cbs.length; j++) {
        try { cbs[j](lang); } catch (e) { /* 单个回调失败不影响其它 */ }
      }
    }
  }

  var lang = read();
  apply(lang); // 同步执行，防闪烁；此时 RANK_I18N 尚未赋值，回调由 on() 补偿

  window.RANK_I18N = {
    lang: lang,
    _cb: [],
    on: function (cb) {
      this._cb.push(cb);
      try { cb(this.lang); } catch (e) { /* 忽略 */ }
    },
    set: function (l) {
      l = (l === 'en') ? 'en' : 'zh';
      write(l);
      apply(l);
    },
    toggle: function () { this.set(this.lang === 'en' ? 'zh' : 'en'); }
  };

  var BTN_HTML = '<span data-l="zh">中</span><span data-l="en">EN</span>';

  function bindBtn(btn) {
    if (btn.getAttribute('data-i18n-bound')) return;
    btn.setAttribute('data-i18n-bound', '1');
    if (!btn.innerHTML.trim()) btn.innerHTML = BTN_HTML;
    if (btn.tagName === 'BUTTON' && !btn.type) btn.type = 'button';

    function update() {
      var l = window.RANK_I18N.lang;
      var spans = btn.querySelectorAll('[data-l]');
      for (var i = 0; i < spans.length; i++) {
        spans[i].classList.toggle('active', spans[i].getAttribute('data-l') === l);
      }
      btn.setAttribute('title', l === 'en' ? 'Switch to Chinese' : '切换到英文');
      btn.setAttribute('aria-label', btn.getAttribute('title'));
    }
    window.RANK_I18N.on(update);
    btn.addEventListener('click', function () { window.RANK_I18N.toggle(); });
  }

  function boot() {
    var btn = document.getElementById('cm-rank-lang');
    if (btn) {
      bindBtn(btn);
    } else {
      // 独立站没有顶栏：注入一个浮动切换器，保证两处体验一致
      var b = document.createElement('button');
      b.id = 'cm-rank-lang';
      b.className = 'cm-lang-float';
      b.innerHTML = BTN_HTML;
      document.body.appendChild(b);
      bindBtn(b);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

/* ==========================================================================
   cyberMap 设计稿 04 号板 · 排行榜详情页赛博增强
   --------------------------------------------------------------------------
   详情页 /rank/p/*、/rank/harness/p/* 只加载 i18n.js + rank-frame.js，
   不加载 app.js —— app.js 里的 04 号板 HUD 注入在详情页从来不会执行。
   本模块放在两页都加载的 i18n.js 末尾，仅对详情页、仅 body.night 注入
   SECTION 04 HUD；05 token 由稳定的 style.css 提供（body.night.rank-embedded
   覆盖 rank-frame.css 的旧靛蓝紫）。经典态全部不生效，零改动。
   ========================================================================== */
(function () {
  'use strict';
  if (!/\/[ph]\/[^/]+\.html$/.test(location.pathname)) return; // 只处理详情页
  var STYLE_ID = 'cm-rank-detail-cyber-style';
  if (document.getElementById(STYLE_ID)) return;                // 幂等

  var css = '' +
    '.cm-rank-detail-hud{display:none}' +
    'body.night .cm-rank-detail-hud{' +
      'display:flex!important;position:sticky;top:0;z-index:90;align-items:center;gap:12px;' +
      'height:28px;padding:0 24px;background:#07121c;border-bottom:1px solid var(--cm-border);' +
      'font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.1em;color:var(--cm-text-faint)}' +
    'body.night .cm-rank-detail-hud::before{' +
      'content:"";width:6px;height:6px;border-radius:50%;background:var(--cm-accent);box-shadow:0 0 8px var(--cm-accent)}' +
    'body.night .cm-rank-detail-hud b{color:var(--cm-accent);font-weight:700}' +
    'body.night .cm-rank-detail-hud .cm-rd-right{margin-left:auto}' +
    'body.night .cm-rank-detail-hud .cm-rd-clock{' +
      'font-family:"CM Orbitron",sans-serif;font-weight:900;color:var(--cm-accent)}' +
    'body.night.rank-embedded .cm-rank-bar{top:28px}';

  function injectStyle() {
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }
  function node(html) {
    var box = document.createElement('div');
    box.innerHTML = html;
    return box.firstChild;
  }
  function tick() {
    var c = document.querySelector('.cm-rd-clock');
    if (!c) return;
    var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
    c.textContent = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function inject() {
    if (!document.body || document.querySelector('.cm-rank-detail-hud')) return;
    var isH = location.pathname.indexOf('/harness/') >= 0;
    var hud = node('<div class="cm-rank-detail-hud">' +
      '<b>SECTION 04 // ' + (isH ? 'HARNESS LEADERBOARD' : 'PLUGIN LEADERBOARD') + '</b>' +
      '<span class="cm-rd-right">DATA DETAIL · LIVE <span class="cm-rd-clock">--:--:--</span></span></div>');
    document.body.insertBefore(hud, document.body.firstChild);
    tick();
    setInterval(tick, 1000);
  }
  injectStyle();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
