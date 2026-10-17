"""
bridge_assets.py : le « composant invisible » de Mbouda City.

Il apporte, côté navigateur :
  - glisser un message vers la droite = répondre
  - appui long / clic droit / bouton ⋯ = menu (répondre, transférer, copier, réagir)
  - toucher une photo ou une vidéo = ouverture en grand
  - défilement automatique vers le dernier message
  - barre d'outils alignée sur la barre d'envoi
  - fermeture du menu latéral sur téléphone, et fichiers d'installation (PWA)

Rien à créer à la main dans GitHub : au démarrage, ensure_dir() écrit les fichiers du composant
(page HTML, manifeste, icônes) dans un dossier temporaire, puis app.py le déclare à Streamlit.
"""
import hashlib
import json
import os
import tempfile

VERSION = "3.1"

INDEX_HTML = r'''<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>mc_bridge</title></head>
<body>
<script>
/* Mbouda City : composant invisible (protocole Streamlit v1).
 * Le code important (hostCode) est injecté dans la page Streamlit elle-même : il survit si Streamlit
 * recrée le cadre du composant. Les actions sont renvoyées à Python avec setComponentValue ;
 * les consignes de Python (fermer le menu, installer la PWA) arrivent par les arguments de rendu. */
(function () {
  var HOST = window.parent;
  function send(type, data) {
    HOST.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data || {}), "*");
  }
  function emit(ev) {
    send("streamlit:setComponentValue",
         { value: Object.assign({ n: Date.now() + Math.random() }, ev), dataType: "json" });
  }
  var D = null;
  try { D = HOST.document; } catch (e) { D = null; }
  var BASE = new URL("./", location.href).href;       // dossier du composant : manifeste et icônes

  function boot() {
    if (!D) return;
    var G = HOST.__mcGest || (HOST.__mcGest = {});
    G.emit = emit;                                    // toujours le cadre le plus récent
    if (G.installed) return;
    G.installed = true;
    try {
      var sc = D.createElement("script");
      sc.textContent = "(" + hostCode.toString() + ")(window);";
      D.head.appendChild(sc);
      sc.remove();
    } catch (e) { /* injection refusée : repli ci-dessous */ }
    if (!G.hostReady) { try { hostCode(HOST); } catch (e2) {} }
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || d.type !== "streamlit:render") return;
    boot();
    var G = D && HOST.__mcGest;
    if (G && G.run) G.run(Object.assign({ base: BASE }, d.args || {}));
  });
  boot();
  send("streamlit:componentReady", { apiVersion: 1 });
  send("streamlit:setFrameHeight", { height: 0 });

  /* ---- Tout ce qui suit s'exécute dans la page Streamlit (HOST). Aucune variable extérieure. ---- */
  function hostCode(HOST) {
    var D = HOST.document, G = HOST.__mcGest;
    G.hostReady = true;
    var REACTS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];
    var $ = function (sel) { return D.querySelector(sel); };
    var closest = function (t, sel) { return t && t.closest ? t.closest(sel) : null; };
    function el(tag, cls, html) {
      var x = D.createElement(tag);
      if (cls) x.className = cls;
      if (html != null) x.innerHTML = html;
      return x;
    }

    /* ---------- menu d'actions ---------- */
    function closeMenu() { var m = $(".mc-menu"); if (m) m.remove(); }
    function openMenu(row, x, y) {
      closeMenu();
      var mid = row.getAttribute("data-mid");
      var m = el("div", "mc-menu");
      var rx = el("div", "mc-menu-rx");
      REACTS.forEach(function (r, i) {
        var b = el("button", null, r);
        b.onclick = function () { closeMenu(); G.emit({ type: "react", id: mid, idx: i }); };
        rx.appendChild(b);
      });
      m.appendChild(rx);
      function add(label, fn) {
        var b = el("button", "mc-menu-it", label);
        b.onclick = function () { closeMenu(); fn(); };
        m.appendChild(b);
      }
      add("↩ Répondre", function () { G.emit({ type: "reply", id: mid }); });
      add("↪ Transférer", function () { G.emit({ type: "forward", id: mid }); });
      var t = row.querySelector(".mc-text");
      if (t) add("📋 Copier", function () {
        try { HOST.navigator.clipboard.writeText(t.innerText); } catch (e) {}
      });
      D.body.appendChild(m);
      var w = m.offsetWidth, h = m.offsetHeight, W = HOST.innerWidth, H = HOST.innerHeight;
      var top = y - h - 8;
      if (top < 8) top = Math.min(y + 12, H - h - 8);
      m.style.left = Math.max(8, Math.min(x - w / 2, W - w - 8)) + "px";
      m.style.top = Math.max(8, top) + "px";
    }
    D.addEventListener("pointerdown", function (e) { if (!closest(e.target, ".mc-menu")) closeMenu(); }, true);
    D.addEventListener("contextmenu", function (e) {
      var row = closest(e.target, ".mc-row[data-mid]");
      if (row) { e.preventDefault(); openMenu(row, e.clientX, e.clientY); }
    });

    /* ---------- glisser pour répondre + appui long ---------- */
    var row = null, bub = null, sx = 0, sy = 0, dx = 0, active = false, moved = false, lp = null, ic = null;
    function resetSwipe() {
      clearTimeout(lp);
      if (bub) { bub.style.transition = "transform .18s ease"; bub.style.transform = ""; }
      if (ic) { ic.remove(); ic = null; }
      active = false; row = null; bub = null; dx = 0;
    }
    D.addEventListener("touchstart", function (e) {
      var r = closest(e.target, ".mc-row[data-mid]");
      if (!r || e.touches.length !== 1 || closest(e.target, ".mc-more")) return;
      row = r; bub = r.querySelector(".mc-bub");
      sx = e.touches[0].clientX; sy = e.touches[0].clientY; dx = 0; moved = false; active = true;
      clearTimeout(lp);
      lp = setTimeout(function () {
        if (active && !moved) { var rr = row; active = false; openMenu(rr, sx, sy); if (navigator.vibrate) navigator.vibrate(20); }
      }, 480);
    }, { passive: true });
    D.addEventListener("touchmove", function (e) {
      if (!active) return;
      var t = e.touches[0], mx = t.clientX - sx, my = t.clientY - sy;
      if (!moved && Math.abs(my) > 10 && Math.abs(my) > Math.abs(mx)) { resetSwipe(); return; }  // défilement vertical
      if (Math.abs(mx) > 8) { moved = true; clearTimeout(lp); }
      dx = Math.max(0, Math.min(mx, 90));
      if (bub && moved) {
        bub.style.transition = "none";
        bub.style.transform = "translateX(" + dx + "px)";
        if (!ic) { ic = el("span", "mc-swipe-ic", "↩"); row.appendChild(ic); }
        ic.style.opacity = Math.min(1, dx / 60);
      }
    }, { passive: true });
    D.addEventListener("touchend", function () {
      if (!active) { resetSwipe(); return; }
      var fire = dx >= 60, id = row && row.getAttribute("data-mid");
      resetSwipe();
      if (fire && id) { if (navigator.vibrate) navigator.vibrate(15); G.emit({ type: "reply", id: id }); }
    }, { passive: true });
    D.addEventListener("touchcancel", resetSwipe, { passive: true });

    /* ---------- visionneuse photo / vidéo ---------- */
    function closeLb() {
      var lb = $(".mc-lb");
      if (lb) { var v = lb.querySelector("video"); if (v) v.pause(); lb.remove(); }
    }
    function lightbox(kind, src, t) {
      closeLb();
      var lb = el("div", "mc-lb"), media;
      if (kind === "img") { media = el("img"); media.src = src; }
      else {
        media = el("video"); media.controls = true; media.autoplay = true; media.playsInline = true; media.src = src;
        if (t) media.addEventListener("loadedmetadata", function () { try { media.currentTime = t; } catch (e) {} });
      }
      var x = el("button", "mc-lb-x", "✕");
      lb.appendChild(media); lb.appendChild(x);
      if (kind === "img") { var a = el("a", "mc-lb-dl", "⬇"); a.href = src; a.download = "photo.jpg"; lb.appendChild(a); }
      lb.addEventListener("click", function (e) { if (e.target === lb || e.target === x) closeLb(); });
      D.body.appendChild(lb);
    }
    D.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeLb(); closeMenu(); } });

    function gotoMsg(id) {
      var t = $('.mc-row[data-mid="' + id + '"]');
      if (!t) return;
      t.scrollIntoView({ block: "center", behavior: "smooth" });
      t.classList.add("flash");
      setTimeout(function () { t.classList.remove("flash"); }, 1400);
    }

    D.addEventListener("click", function (e) {
      if (closest(e.target, ".mc-lb") || closest(e.target, ".mc-menu")) return;
      var v = closest(e.target, 'video[data-testid="stVideo"], [data-testid="stVideo"] video');
      if (v) {                                           // clic sur l'image de la vidéo = ouvrir (barre de contrôle = lecture)
        var r = v.getBoundingClientRect();
        if (e.clientY < r.bottom - 48) {
          e.preventDefault(); e.stopPropagation();
          v.pause();
          lightbox("video", v.currentSrc || v.src, v.currentTime);
        }
        return;
      }
      var img = closest(e.target, ".mc-img, .mc-story-img img");
      if (img) { lightbox("img", img.src); return; }
      var more = closest(e.target, ".mc-more");
      if (more) {
        var rw = closest(more, ".mc-row[data-mid]"), b = more.getBoundingClientRect();
        if (rw) openMenu(rw, b.left + b.width / 2, b.top);
        return;
      }
      var q = closest(e.target, ".mc-quote[data-goto]");
      if (q) gotoMsg(q.getAttribute("data-goto"));
    }, true);

    /* ---------- défilement automatique vers le dernier message ---------- */
    var near = true, lastChat = null, lastMid = null;
    function scrollerEl() {
      var c = [$('[data-testid="stMain"]'), $("section.main"), $('[data-testid="stAppViewContainer"]')];
      for (var i = 0; i < c.length; i++) if (c[i] && c[i].scrollHeight > c[i].clientHeight + 4) return c[i];
      return D.scrollingElement || D.documentElement;
    }
    function bottomGap() { var s = scrollerEl(); return s.scrollHeight - s.scrollTop - s.clientHeight; }
    function scrollBottom() {
      [120, 650].forEach(function (ms) {
        HOST.setTimeout(function () {
          var s = scrollerEl();
          if (s.scrollTo) s.scrollTo({ top: s.scrollHeight, behavior: "smooth" });
          HOST.scrollTo(0, D.body.scrollHeight);
        }, ms);
      });
    }
    D.addEventListener("scroll", function () { near = bottomGap() < 320; }, true);
    function followMessages() {
      var head = $(".mc-head[data-chat]");
      if (!head) { lastChat = null; lastMid = null; return; }
      var chat = head.getAttribute("data-chat"), rows = D.querySelectorAll(".mc-row[data-mid]");
      var last = rows.length ? rows[rows.length - 1] : null, mid = last ? last.getAttribute("data-mid") : "0";
      if (chat !== lastChat) { lastChat = chat; lastMid = mid; near = true; scrollBottom(); return; }   // discussion ouverte
      if (mid !== lastMid) {                                                                           // nouveau message
        lastMid = mid;
        if (near || (last && last.classList.contains("me"))) scrollBottom();                           // sans bousculer qui relit l'historique
      }
    }

    /* ---------- barre d'outils alignée sur la barre d'envoi ---------- */
    function placeTools() {
      var box = $(".st-key-mc-tools"), ci = $('[data-testid="stChatInput"]');
      if (!box || !ci) return;
      var r = ci.getBoundingClientRect();
      if (!r.width) return;
      box.style.transform = "none";
      box.style.left = r.left + "px";
      box.style.width = r.width + "px";
      box.style.bottom = (HOST.innerHeight - r.top + 6) + "px";
    }
    var pending = false;
    function schedule() {
      if (pending) return;
      pending = true;
      HOST.requestAnimationFrame(function () { pending = false; placeTools(); followMessages(); });
    }
    HOST.addEventListener("resize", schedule);
    new HOST.MutationObserver(schedule).observe(D.body, { childList: true, subtree: true });
    schedule();

    /* ---------- consignes de Python ---------- */
    function closeSidebar() {
      if (HOST.innerWidth > 640) return;
      var b = $('[data-testid="stSidebarCollapseButton"] button') || $('[data-testid="stSidebarHeader"] button')
           || $('[data-testid="stSidebarCollapseButton"]');
      if (b) b.click();
    }
    function addPwa(base) {
      var h = D.head, old = $('link[rel="manifest"]');
      if (!h || (old && old.getAttribute("data-mc"))) return;
      if (old) old.remove();
      function add(tag, attrs) {
        var e = D.createElement(tag);
        for (var k in attrs) e.setAttribute(k, attrs[k]);
        e.setAttribute("data-mc", "1");
        h.appendChild(e);
      }
      add("link", { rel: "manifest", href: base + "manifest.json" });
      add("link", { rel: "apple-touch-icon", href: base + "apple-touch-icon.png" });
      add("meta", { name: "theme-color", content: "#0a0e13" });
      add("meta", { name: "apple-mobile-web-app-capable", content: "yes" });
      add("meta", { name: "mobile-web-app-capable", content: "yes" });
      add("meta", { name: "apple-mobile-web-app-title", content: "Mbouda City" });
    }
    G.run = function (a) {
      if (a.close_sb && a.close_sb !== G.lastClose) { G.lastClose = a.close_sb; closeSidebar(); }
      if (a.pwa && !G.pwaDone) { G.pwaDone = true; addPwa(a.base); }
    };
  }
})();
</script>
</body>
</html>
'''

MANIFEST = {
    "name": "Mbouda City",
    "short_name": "Mbouda City",
    "description": "Discutez, appelez et partagez, sans numéro de téléphone.",
    "lang": "fr",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#0a0e13",
    "theme_color": "#0a0e13",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# (nom du fichier, taille, échelle du « M », coins arrondis)
ICONS = [("icon-192.png", 192, 1.15, True), ("icon-512.png", 512, 1.15, True),
         ("maskable-512.png", 512, 0.85, False), ("apple-touch-icon.png", 180, 0.95, False)]
_M = [(22, 76), (22, 24), (33, 24), (50, 48), (67, 24), (78, 24), (78, 76), (67, 76), (67, 42), (50, 66), (33, 42), (33, 76)]


def _icon_png(size, scale, rounded):
    """Dessine l'icône (dégradé vert → or, lettre M) et retourne les octets PNG."""
    import io
    from PIL import Image, ImageDraw
    res = getattr(Image, "Resampling", Image)
    a, b = (25, 195, 125), (245, 197, 66)
    g = Image.new("RGB", (64, 64))
    px = g.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    img = g.resize((size, size), res.BILINEAR)
    k = 3
    big = size * k
    mask = Image.new("L", (big, big), 0)
    pts = [((50 + (x - 50) * scale) / 100 * big, (50 + (y - 50) * scale) / 100 * big) for x, y in _M]
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    mask = mask.resize((size, size), res.LANCZOS)
    img.paste(Image.new("RGB", (size, size), (4, 19, 12)), (0, 0), mask)
    if rounded:
        rm = Image.new("L", (big, big), 0)
        ImageDraw.Draw(rm).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * .22), fill=255)
        rm = rm.resize((size, size), res.LANCZOS)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), rm)
        img = out
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


_DIR = None


def ensure_dir():
    """Écrit (si besoin) les fichiers du composant et retourne le dossier à donner à Streamlit."""
    global _DIR
    if _DIR and os.path.isfile(os.path.join(_DIR, "index.html")):
        return _DIR
    d = os.path.join(tempfile.gettempdir(), "mbouda_city_bridge")
    os.makedirs(d, exist_ok=True)
    stamp = hashlib.sha1((VERSION + INDEX_HTML + json.dumps(MANIFEST)).encode("utf-8")).hexdigest()
    marker = os.path.join(d, ".stamp")
    names = ["index.html", "manifest.json"] + [n for n, *_ in ICONS]
    try:
        with open(marker, encoding="utf-8") as f:
            fresh = f.read() == stamp
    except OSError:
        fresh = False
    if not fresh or not all(os.path.isfile(os.path.join(d, n)) for n in names):
        _write(os.path.join(d, "index.html"), INDEX_HTML.encode("utf-8"))
        _write(os.path.join(d, "manifest.json"), json.dumps(MANIFEST, ensure_ascii=False, indent=2).encode("utf-8"))
        for name, size, scale, rounded in ICONS:
            try:
                _write(os.path.join(d, name), _icon_png(size, scale, rounded))
            except Exception:       # Pillow absent : l'application marche, sans icônes d'installation
                pass
        _write(marker, stamp.encode("utf-8"))
    _DIR = d
    return d
