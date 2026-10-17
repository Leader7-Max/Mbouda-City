"""helpers.py : fonctions pures de Mbouda City (aucune dépendance à Streamlit)."""
import html
import io
import wave
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

esc = html.escape

COLORS = ["#19c37d", "#f5c542", "#4da3ff", "#ff6b8b", "#a78bfa", "#ff9f43"]
BGS = [
    "linear-gradient(135deg,#19c37d,#0b6e4a)",
    "linear-gradient(135deg,#f5c542,#e0661a)",
    "linear-gradient(135deg,#4da3ff,#6a4cff)",
    "linear-gradient(135deg,#ff6b8b,#c2185b)",
    "linear-gradient(135deg,#a78bfa,#4f46e5)",
    "linear-gradient(135deg,#1f2937,#0b0f14)",
]
BG_DOTS = ["🟩", "🟧", "🟦", "🟥", "🟪", "⬛"]
REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"]
STICKER_EMOJIS = ["😀", "😂", "🥰", "😎", "🤩", "😭", "😡", "🤯", "🥳", "🙏",
                  "👏", "🔥", "💯", "❤️", "💪", "🎉", "👍", "🤝", "😴", "🤔"]
STICKER_WORDS = ["Merci !", "Salut 👋", "OK ✅", "Bravo 👏", "Bonne nuit 🌙", "Ça va ?",
                 "À bientôt", "Félicitations 🎉", "Je t’aime ❤️", "Pas de souci", "Bon appétit 🍽️", "Courage 💪"]
MAX_FILE = 25 * 1024 * 1024
MAX_VIDEO = 60 * 1024 * 1024
MAX_VOICE = 4 * 1024 * 1024


def color_for(name):
    return COLORS[sum(map(ord, str(name))) % len(COLORS)]


# ---------------------------------------------------------------- temps
def tzinfo(name):
    try:
        return ZoneInfo(name) if name else timezone.utc
    except Exception:
        return timezone.utc


def fmt_time(ts, tz=timezone.utc):
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def fmt_day(ts, tz=timezone.utc):
    d = datetime.fromtimestamp(ts, tz).date()
    delta = (datetime.now(tz).date() - d).days
    return "Aujourd’hui" if delta == 0 else "Hier" if delta == 1 else d.strftime("%d/%m/%Y")


def fmt_dur(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_size(n):
    return f"{n / 1e6:.1f} Mo" if n > 1e6 else f"{max(1, round(n / 1e3))} Ko"


# ---------------------------------------------------------------- médias
def shrink(data, max_side=1280, quality=80, square=None):
    """Réduit une image (JPEG) pour garder l'application légère."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if square:
        img = ImageOps.fit(img, (square, square))
    else:
        img.thumbnail((max_side, max_side))
    if img.mode != "RGB":
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def wav_duration(data):
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


# ---------------------------------------------------------------- HTML
def avatar_html(user, size=40, uri="", ring=False):
    name = (user or {}).get("name") or "?"
    base = f"width:{size}px;height:{size}px;font-size:{int(size * .42)}px"
    cls = "mc-av ring" if ring else "mc-av"
    if uri:
        return f'<span class="{cls}" style="{base};background-image:url({uri})"></span>'
    return f'<span class="{cls}" style="{base};background:{color_for(name)}">{esc(name[:1].upper())}</span>'


def preview_text(m, me):
    k = m["kind"]
    p = {"text": m["body"], "image": "📷 Photo", "video": "🎥 Vidéo", "file": "📎 " + (m["meta"] or "Fichier"),
         "voice": "🎤 Vocal", "sticker": "Sticker", "call": "📞 Appel"}.get(k, "")
    return ("Vous : " if m["sender"] == me else "") + p


def quote_info(orig, name_of):
    """Résumé d'un message cité (réponse) : {id, name, text}."""
    return {"id": orig["id"], "name": name_of(orig["sender"]), "text": preview_text(orig, "")[:90]}


def quote_html(q):
    return (f'<div class="mc-quote" data-goto="{q["id"]}"><b>{esc(q["name"])}</b>'
            f'<div>{esc(q["text"])}</div></div>')


def reaction_chips(reacts, me):
    if not reacts:
        return ""
    chips = "".join(
        f'<span class="{"mine" if me in users else ""}">{esc(e)}{" " + str(len(users)) if len(users) > 1 else ""}</span>'
        for e, users in reacts.items())
    return f'<div class="mc-rx">{chips}</div>'


def sticker_html(body):
    kind, _, rest = (body or "").partition(":")
    if kind == "e":
        return f'<div class="mc-stk-e">{esc(rest)}</div>'
    idx, _, word = rest.partition(":")
    try:
        bg = BGS[int(idx) % len(BGS)]
    except ValueError:
        bg = BGS[0]
    return f'<div class="mc-stk-t" style="background:{bg}">{esc(word)}</div>'


def bubble(m, me, group, name_of, reads, others, reacts, uri_of, tz=timezone.utc, quotes=None):
    """Retourne (html, widget). widget = None ou un dict pour les messages qui demandent un composant natif.
    quotes : {id du message cité: quote_info(...)} pour afficher les réponses."""
    mine = m["sender"] == me
    kind = m["kind"]
    who = ""
    if group and not mine:
        who = f'<div class="mc-who" style="color:{color_for(m["sender"])}">{esc(name_of(m["sender"]))}</div>'
    if m.get("forwarded"):
        who += '<div class="mc-fwd">↪ Transféré</div>'
    q = (quotes or {}).get(m.get("reply_to"))
    if q:
        who += quote_html(q)
    meta = fmt_time(m["ts"], tz)
    if mine:
        read = bool(others) and all(reads.get(u, 0) >= m["ts"] for u in others)
        meta += f' <span class="mc-tick{" rd" if read else ""}">{"✓✓" if read else "✓"}</span>'
    widget, cls = None, ""
    if kind == "text":
        inner = f'<div class="mc-text">{esc(m["body"])}</div>'
    elif kind == "image":
        uri = uri_of(m["media_id"])
        inner = f'<img class="mc-img" src="{uri}" alt="photo"/>' if uri else '<div class="mc-text">📷 Photo indisponible</div>'
        if m["body"]:
            inner += f'<div class="mc-text">{esc(m["body"])}</div>'
    elif kind == "sticker":
        inner, cls = sticker_html(m["body"]), " stk"
    elif kind == "voice":
        try:
            dur = float(m["meta"] or 0)
        except ValueError:
            dur = 0
        inner = f'<div class="mc-text">🎤 Message vocal · {fmt_dur(dur)}</div>'
        widget = {"type": "voice", "media_id": m["media_id"]}
    elif kind == "video":
        inner = f'<div class="mc-text">🎥 <b>{esc(m["meta"] or "Vidéo")}</b></div>'
        widget = {"type": "video", "media_id": m["media_id"], "id": m["id"]}
    elif kind == "file":
        inner = f'<div class="mc-text">📄 <b>{esc(m["meta"] or "Fichier")}</b></div>'
        widget = {"type": "file", "media_id": m["media_id"], "name": m["meta"] or "fichier", "id": m["id"]}
    elif kind == "call":
        video = m["meta"] == "video"
        inner = f'<div class="mc-text">{"🎥 Appel vidéo" if video else "📞 Appel audio"}</div>'
        widget = {"type": "call", "room": m["body"], "video": video, "ts": m["ts"], "id": m["id"]}
    else:
        inner = f'<div class="mc-text">{esc(m["body"])}</div>'
    side = "me" if mine else "them"
    more = '' if kind == "call" else ' <span class="mc-more" title="Répondre, transférer, réagir">⋯</span>'
    out = (f'<div class="mc-row {side}" data-mid="{m["id"]}"><div class="mc-bub{cls}">{who}{inner}'
           f'<div class="mc-meta">{meta}{more}</div>{reaction_chips(reacts, me)}</div></div>')
    return out, widget
