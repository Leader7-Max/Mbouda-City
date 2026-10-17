"""
Mbouda City : messagerie sans numéro de téléphone, en Streamlit.
Lancer : streamlit run app.py

Fichiers du projet : app.py (ce fichier), bridge_assets.py, db.py, helpers.py, assets/style.css

app.py est organisé en 6 parties :
  1/6  Configuration, thème et utilitaires
  2/6  Connexion / création de compte
  3/6  Barre latérale : menu, liste des discussions, nouvelles discussions
  4/6  Affichage des messages
  5/6  Écran de discussion : envoi, réponses, transferts, vocaux, stickers, réactions, appels
  6/6  Stories, profil et routeur principal
"""
# ============================================================================
# PARTIE 1/6 : Configuration, thème et utilitaires
# ============================================================================
import base64
import inspect
import os
import secrets
import time
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

import db
import helpers as H

try:
    import bridge_assets
except Exception:  # fichier absent : l'application démarre quand même, sans les gestes
    bridge_assets = None

VIDEO_EXT = {"mp4", "mov", "m4v", "webm", "3gp", "mkv", "avi"}
ROOT = os.path.dirname(os.path.abspath(__file__))


def _bridge_dir():
    """Dossier du composant invisible, écrit au démarrage par bridge_assets (rien à créer dans GitHub)."""
    if bridge_assets is None:
        return None
    try:
        return bridge_assets.ensure_dir()
    except Exception:
        return None


BRIDGE_DIR = _bridge_dir()
_ICON = os.path.join(BRIDGE_DIR, "icon-192.png") if BRIDGE_DIR else ""
st.set_page_config(page_title="Mbouda City", page_icon=_ICON if os.path.exists(_ICON) else "💬",
                   layout="centered", initial_sidebar_state="collapsed")

CALL_BASE = (db.secret("CALL_BASE_URL") or "https://meet.jit.si").rstrip("/")


def _params(fn):
    try:
        return inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}


# Selon la version de Streamlit, la barre d'envoi reçoit fichiers et micro ; sinon ils passent par le bouton ＋.
HAS_FILE_INPUT = "accept_file" in _params(st.chat_input)
HAS_AUDIO_INPUT = "accept_audio" in _params(st.chat_input)
HAS_KEY = "key" in _params(st.container)

# Composant invisible : gestes, menu, visionneuse, défilement, barre fixe. Absent = l'appli marche sans.
bridge = None
if BRIDGE_DIR:
    try:
        bridge = components.declare_component("mc_bridge", path=BRIDGE_DIR)
    except Exception:
        bridge = None


def call_bridge(**args):
    """Monte le composant. Retourne la dernière action envoyée par le navigateur (ou None)."""
    if bridge is None:
        return None
    try:
        return bridge(key="mc_bridge", default=None, **args)
    except Exception:
        return None


def sw(fn):
    """Largeur pleine, compatible avec toutes les versions de Streamlit."""
    p = _params(fn)
    if "width" in p:
        return {"width": "stretch"}
    return {"use_container_width": True} if "use_container_width" in p else {}


@st.cache_resource
def _css():
    try:
        with open(os.path.join(ROOT, "assets", "style.css"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=300)
def media_uri(mid):
    m = db.get_media(mid)
    return f"data:{m[1]};base64,{base64.b64encode(m[0]).decode()}" if m else ""


@st.cache_data(show_spinner=False, max_entries=6, ttl=300)
def media_blob(mid):
    return db.get_media(mid)


def browser_tz():
    try:
        return H.tzinfo(st.context.timezone)
    except Exception:
        return H.tzinfo(None)


def avatar(user, size=40, ring=False):
    uri = media_uri(user["avatar_id"]) if user and user.get("avatar_id") else ""
    return H.avatar_html(user, size, uri, ring)


def html(s):
    st.markdown(s, unsafe_allow_html=True)


def chat_title(chat, me, umap):
    if chat["kind"] == "group":
        return chat["name"]
    other = next((u for u in chat["members"] if u != me), me)
    return (umap.get(other) or {}).get("name", other)


# ============================================================================
# PARTIE 2/6 : Connexion / création de compte
# ============================================================================
def current_user():
    if st.session_state.get("user"):
        return st.session_state.user
    tok = st.query_params.get("s")
    if tok:
        u = db.user_from_token(tok)
        if u:
            st.session_state.update(user=u, token=tok, view="chats", chat=None)
            return u
        st.query_params.clear()
    return None


def start_session(user):
    tok = db.new_session(user)
    st.query_params["s"] = tok
    st.session_state.update(user=user, token=tok, view="chats", chat=None)
    db.purge_stories()
    st.rerun()


def logout():
    db.end_session(st.session_state.get("token", ""))
    st.query_params.clear()
    st.session_state.clear()
    st.rerun()


def auth_screen():
    html('<div class="mc-hero"><div class="mc-logo">M</div><h1>Mbouda City</h1>'
         '<p>Discutez, appelez, partagez. Sans numéro de téléphone.</p></div>')
    t_login, t_new = st.tabs(["Connexion", "Créer un compte"])
    with t_login:
        with st.form("f_login"):
            u = st.text_input("Nom d’utilisateur", placeholder="jean.237")
            p = st.text_input("Mot de passe", type="password")
            ok = st.form_submit_button("Se connecter", type="primary", **sw(st.form_submit_button))
        if ok:
            user, err = db.login(u, p)
            st.error(err) if err else start_session(user)
    with t_new:
        with st.form("f_new"):
            n = st.text_input("Nom affiché", placeholder="Jean")
            u = st.text_input("Nom d’utilisateur", placeholder="jean.237", help="C’est ce que vos amis utiliseront pour vous trouver.")
            p = st.text_input("Mot de passe (6 caractères minimum)", type="password")
            ok = st.form_submit_button("Créer mon compte", type="primary", **sw(st.form_submit_button))
        if ok:
            user, err = db.register(u, p, n)
            st.error(err) if err else start_session(user)


# ============================================================================
# PARTIE 3/6 : Barre latérale
# ============================================================================
def open_chat(chat_id):
    st.session_state.update(view="chats", chat=chat_id)
    st.rerun()


@st.dialog("Nouvelle discussion")
def new_chat_dialog():
    me = st.session_state.user
    q = st.text_input("Rechercher un @utilisateur", placeholder="jean.237", key="nc_q")
    if len(db.clean_username(q)) >= 2:
        res = db.search_users(q, me)
        if not res:
            st.caption("Aucun utilisateur trouvé.")
        for r in res:
            if st.button(f'{r["name"]}  ·  @{r["username"]}', key=f'nc_{r["username"]}', **sw(st.button)):
                open_chat(db.dm_with(me, r["username"]))


@st.dialog("Nouveau groupe")
def new_group_dialog():
    me = st.session_state.user
    name = st.text_input("Nom du groupe", max_chars=40)
    contacts = db.contacts_of(me)
    pick = st.multiselect("Membres", options=list(contacts), format_func=lambda u: f'{contacts[u]["name"]} (@{u})')
    extra = st.text_input("Ou ajoutez des @utilisateurs", placeholder="ana, ben.237")
    if st.button("Créer le groupe", type="primary", **sw(st.button)):
        cid, err = db.create_group(me, name, list(pick) + extra.split(","))
        st.error(err) if err else open_chat(cid)


def call_url(room, video, display_name):
    p = ["config.prejoinPageEnabled=false", "userInfo.displayName=" + quote(f'"{display_name}"')]
    if not video:
        p.append("config.startAudioOnly=true")
    return f"{CALL_BASE}/{room}#" + "&".join(p)


@st.fragment(run_every=4)
def chat_list(me):
    db.touch(me)
    chats = db.my_chats(me)
    umap = db.users_map({u for c in chats for u in c["members"]})
    my_name = (umap.get(me) or {}).get("name", me)
    now = time.time()
    for c in chats:  # appel entrant : dernier message = appel récent d'un autre membre
        m = c["last"]
        if m and m["kind"] == "call" and m["sender"] != me and now - m["ts"] < 90:
            st.success(f'📞 {chat_title(c, me, umap)} vous appelle')
            st.link_button("Rejoindre l’appel", call_url(m["body"], m["meta"] == "video", my_name), **sw(st.link_button))
    if not chats:
        html('<div class="mc-empty">Aucune discussion pour le moment.<br>Touchez « Nouvelle discussion » pour écrire à un @utilisateur.</div>')
    box = st.container(key="mc-list") if HAS_KEY else st.container()
    with box:
        for c in chats:
            label = chat_title(c, me, umap)
            if c["unread"]:
                label += f'   🟢 {c["unread"]}'
            if c["last"]:
                label += "\n" + H.preview_text(c["last"], me)[:46]
            if st.button(label, key=f'chat_{c["id"]}', **sw(st.button)):
                open_chat(c["id"])


def top_bar(me, title=None):
    u = db.get_user(me)
    html(f'<div class="mc-top"><div class="mc-brand">{H.esc(title or "Mbouda City")}</div>{avatar(u, 38, True)}</div>')


def bottom_nav():
    """Navigation fixe en bas (remplace le menu latéral de Streamlit)."""
    view = st.session_state.get("view", "chats")
    box = st.container(key="mc-nav") if HAS_KEY else st.container()
    with box:
        for key, label in (("chats", "💬 Discussions"), ("stories", "◎ Stories"), ("profile", "👤 Profil")):
            if st.button(label, key=f"nav_{key}", type="primary" if view == key else "secondary", **sw(st.button)):
                st.session_state.update(view=key, chat=None)
                st.rerun()


def home_view(me):
    top_bar(me)
    box = st.container(key="mc-actions") if HAS_KEY else st.container()
    with box:
        if st.button("＋ Nouvelle discussion", key="b_new", type="primary", **sw(st.button)):
            new_chat_dialog()
        if st.button("👥 Nouveau groupe", key="b_grp", **sw(st.button)):
            new_group_dialog()
    chat_list(me)


# ============================================================================
# PARTIE 4/6 : Affichage des messages
# ============================================================================
def render_widget(w, my_name):
    """Composants natifs sous la bulle : vocal, vidéo, fichier, appel."""
    if w["type"] == "voice":
        blob = media_blob(w["media_id"])
        if blob:
            st.audio(blob[0], format=blob[1] or "audio/wav")
    elif w["type"] == "video":
        blob = media_blob(w["media_id"])
        if blob:
            st.video(blob[0], format=blob[1] or "video/mp4")
    elif w["type"] == "file":
        blob = media_blob(w["media_id"])
        if blob:
            kw = dict(label=f'⬇ Télécharger {w["name"]}', data=blob[0], file_name=w["name"],
                      mime=blob[1] or "application/octet-stream", key=f'dl_{w["id"]}', **sw(st.download_button))
            try:
                st.download_button(on_click="ignore", **kw)
            except Exception:
                st.download_button(**kw)
    elif w["type"] == "call":
        if time.time() - w["ts"] < 1800:
            st.link_button("Rejoindre l’appel", call_url(w["room"], w["video"], my_name), **sw(st.link_button))
        else:
            st.caption("Appel terminé")


def render_messages(msgs, me, chat, umap, reacts):
    tz = browser_tz()
    others = [u for u in chat["members"] if u != me]
    name_of = lambda u: (umap.get(u) or {}).get("name", u)
    my_name = name_of(me)
    originals = db.messages_by_ids([m.get("reply_to") for m in msgs], chat["id"])
    quotes = {i: H.quote_info(o, name_of) for i, o in originals.items()}
    buf, last_day = [], None

    def flush():
        if buf:
            html("".join(buf))
            buf.clear()

    for m in msgs:
        day = H.fmt_day(m["ts"], tz)
        if day != last_day:
            buf.append(f'<div class="mc-day"><span>{day}</span></div>')
            last_day = day
        bub, widget = H.bubble(m, me, chat["kind"] == "group", name_of, chat["reads"], others,
                               reacts.get(m["id"], {}), media_uri, tz, quotes)
        buf.append(bub)
        if widget:
            flush()
            render_widget(widget, my_name)
    flush()


def bump_limit(chat_id):
    st.session_state[f"lim_{chat_id}"] = st.session_state.get(f"lim_{chat_id}", 50) + 50


# ============================================================================
# PARTIE 5/6 : Écran de discussion
# ============================================================================
@st.fragment(run_every=3)
def messages_fragment(me, chat_id):
    """Rafraîchi toutes les 3 s : en-tête, messages, accusés de lecture, réactions.
    Le défilement vers le bas est assuré par le composant (il repère data-chat et les data-mid)."""
    db.touch(me)
    db.mark_read(chat_id, me)
    chat = db.chat_info(chat_id, me)
    if not chat:
        return
    limit = st.session_state.get(f"lim_{chat_id}", 50)
    msgs = db.chat_messages(chat_id, limit)
    umap = db.users_map(chat["members"])
    reacts = db.reactions_for([m["id"] for m in msgs])

    title = H.esc(chat_title(chat, me, umap))
    if chat["kind"] == "dm":
        other = umap.get(next((u for u in chat["members"] if u != me), me)) or {}
        online = time.time() - (other.get("last_seen") or 0) < 12
        sub = '<span class="mc-on">● en ligne</span>' if online else f'@{H.esc(other.get("username", ""))}'
        head_user = other
    else:
        sub = H.esc(", ".join((umap.get(u) or {}).get("name", u) for u in chat["members"]))
        head_user = {"name": chat["name"]}
    html(f'<div class="mc-head" data-chat="{int(chat_id)}">{avatar(head_user, 46)}<div><b>{title}</b><br><small>{sub}</small></div></div>')

    if len(msgs) >= limit:
        st.button("↑ Messages précédents", key=f"more_{chat_id}", on_click=bump_limit, args=(chat_id,))
    if msgs:
        render_messages(msgs, me, chat, umap, reacts)
    else:
        st.caption("Aucun message. Dites bonjour 👋")

    call = st.session_state.get("my_call")
    if call and call["chat"] == chat_id and time.time() - call["ts"] < 1800:
        st.info("Appel lancé. Ouvrez-le pour rejoindre la salle ; l’autre personne reçoit l’invitation.")
        st.link_button("Rejoindre mon appel", call["url"], **sw(st.link_button))


def send_upload(me, chat_id, f, reply_to=None):
    """Photo, vidéo ou document. Retourne True si envoyé."""
    data, name, mime = f.getvalue(), f.name, f.type or "application/octet-stream"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not mime.startswith("video/") and ext in VIDEO_EXT:  # certains téléphones n'indiquent pas le type
        mime = "video/quicktime" if ext == "mov" else "video/webm" if ext == "webm" else "video/mp4"
    limit = H.MAX_VIDEO if mime.startswith("video/") else H.MAX_FILE
    if len(data) > limit:
        st.error(f"« {name} » est trop lourd ({H.fmt_size(len(data))}). Maximum : {H.fmt_size(limit)}.")
        return False
    if mime.startswith("image/"):
        try:
            data, mime = H.shrink(data), "image/jpeg"
            db.send(chat_id, me, "image", "", db.save_media(data, mime, name), name, reply_to)
            return True
        except Exception:
            data = f.getvalue()  # image illisible : envoyée comme fichier
            mime = f.type or "application/octet-stream"
    kind = "video" if mime.startswith("video/") else "file"
    db.send(chat_id, me, kind, "", db.save_media(data, mime, name), name, reply_to)
    return True


def send_voice(me, chat_id, data, reply_to=None):
    if len(data) > H.MAX_VOICE:
        st.error("Vocal trop long.")
        return False
    mid = db.save_media(data, "audio/wav", "vocal.wav")
    db.send(chat_id, me, "voice", "", mid, str(round(H.wav_duration(data))), reply_to)
    return True


def start_call(me, chat, video):
    room = f"MboudaCity-{chat['id']}-{secrets.token_hex(4)}"
    db.send(chat["id"], me, "call", room, meta="video" if video else "audio")
    name = (db.get_user(me) or {}).get("name", me)
    st.session_state.my_call = {"chat": chat["id"], "ts": time.time(), "url": call_url(room, video, name)}


@st.dialog("Transférer le message")
def forward_dialog(mid):
    me = st.session_state.user
    m = db.get_message(mid)
    if not m or not db.is_member(m["chat_id"], me):
        st.error("Message introuvable.")
        return
    chats = db.my_chats(me)
    umap = db.users_map({u for c in chats for u in c["members"]})
    titles = {c["id"]: chat_title(c, me, umap) for c in chats}
    html(f'<div class="mc-replybar"><div>{H.esc(H.preview_text(m, ""))}</div></div>')
    dest = st.multiselect("Envoyer à", list(titles), format_func=lambda i: titles[i])
    if st.button("Transférer", type="primary", **sw(st.button)):
        if not dest:
            st.warning("Choisissez au moins une discussion.")
        else:
            n = db.forward(mid, me, dest)
            st.session_state.toast = f"Message transféré à {n} discussion{'s' if n > 1 else ''}"
            st.rerun()


def handle_event(me, chat, ev):
    """Actions envoyées par le composant : répondre, transférer, réagir."""
    if not isinstance(ev, dict) or not ev.get("n") or ev["n"] == st.session_state.get("last_ev"):
        return
    st.session_state.last_ev = ev["n"]
    try:
        mid = int(ev.get("id"))
    except (TypeError, ValueError):
        return
    m = db.get_message(mid)
    if not m or m["chat_id"] != chat["id"]:
        return
    kind = ev.get("type")
    if kind == "reply":
        st.session_state.reply = {"chat": chat["id"], "mid": mid}
    elif kind == "react":
        idx = ev.get("idx")
        if isinstance(idx, int) and 0 <= idx < len(H.REACTIONS):
            db.toggle_reaction(mid, me, H.REACTIONS[idx])
    elif kind == "forward" and m["kind"] != "call":
        forward_dialog(mid)


def unpack_input(v):
    """Valeur de la barre d'envoi -> (texte, fichiers, audio). Compatible avec toutes les versions."""
    if v is None:
        return "", [], None
    if isinstance(v, str):
        return v, [], None
    g = v.get if hasattr(v, "get") else (lambda k: getattr(v, k, None))
    return (g("text") or ""), list(g("files") or []), g("audio")


def handle_input(me, chat_id, value):
    text, files, audio = unpack_input(value)
    if not (text.strip() or files or audio):
        return
    r = st.session_state.pop("reply", None)
    reply = r["mid"] if r and r["chat"] == chat_id else None
    for f in files:
        if send_upload(me, chat_id, f, reply):
            reply = None
    if audio is not None:
        if send_voice(me, chat_id, audio.getvalue(), reply):
            reply = None
    if text.strip():
        db.send(chat_id, me, "text", text.strip(), reply_to=reply)


@st.dialog("Envoyer un fichier")
def attach_dialog(me, chat_id):
    k = st.session_state.setdefault("k", 0)
    st.caption(f"Photos, vidéos (jusqu’à {H.fmt_size(H.MAX_VIDEO)}), documents (jusqu’à {H.fmt_size(H.MAX_FILE)}).")
    files = st.file_uploader("Choisir des fichiers", accept_multiple_files=True, key=f"up_{k}")
    if files and st.button("Envoyer", key=f"upb_{k}", type="primary", **sw(st.button)):
        r = st.session_state.pop("reply", None)
        reply = r["mid"] if r and r["chat"] == chat_id else None
        ok = False
        for f in files:
            if send_upload(me, chat_id, f, reply):
                ok, reply = True, None
        if ok:
            st.session_state.k = k + 1
            st.rerun()


@st.dialog("Stickers")
def sticker_dialog(me, chat_id):
    k = st.session_state.setdefault("k", 0)
    st.caption("Emojis géants")
    e = st.pills("Emojis", H.STICKER_EMOJIS, key=f"stk_e_{k}", label_visibility="collapsed")
    st.caption("Mots")
    w = st.pills("Mots", H.STICKER_WORDS, key=f"stk_w_{k}", label_visibility="collapsed")
    if e or w:
        v = e or w
        body = "e:" + v if e else f"t:{H.STICKER_WORDS.index(v) % len(H.BGS)}:{v}"
        db.send(chat_id, me, "sticker", body)
        st.session_state.k = k + 1
        st.rerun()


@st.dialog("Appeler")
def call_dialog(me, chat):
    st.caption("L’appel s’ouvre dans un nouvel onglet (Jitsi). Les autres reçoivent l’invitation ici.")
    if st.button("📞 Appel audio", key="call_a", **sw(st.button)):
        start_call(me, chat, video=False)
        st.rerun()
    if st.button("🎥 Appel vidéo", key="call_v", type="primary", **sw(st.button)):
        start_call(me, chat, video=True)
        st.rerun()


@st.dialog("Actions sur un message")
def actions_dialog(me, chat):
    chat_id = chat["id"]
    recent = [m for m in db.chat_messages(chat_id, 15) if m["kind"] != "call"][::-1]
    if not recent:
        st.caption("Aucun message.")
        return
    st.caption("Astuce : glissez un message vers la droite pour répondre, appui long pour le menu.")
    umap = db.users_map(chat["members"])
    by_id = {m["id"]: m for m in recent}
    label = lambda i: f'{(umap.get(by_id[i]["sender"]) or {}).get("name", by_id[i]["sender"])} : {H.preview_text(by_id[i], "")[:34]}'
    sel = st.selectbox("Message", list(by_id), format_func=label, key="react_msg")
    if st.button("↩ Répondre", key="act_reply", **sw(st.button)):
        st.session_state.reply = {"chat": chat_id, "mid": sel}
        st.rerun()
    if st.button("↪ Transférer", key="act_fwd", **sw(st.button)):
        st.session_state.fwd_mid = sel
        st.rerun()
    pick = st.pills("Réaction", H.REACTIONS, key="react_pick")
    if pick:
        db.toggle_reaction(sel, me, pick)
        st.session_state["react_pick"] = None
        st.rerun()


def tools_strip(me, chat):
    """Barre fixe au-dessus de la barre d'envoi : réponse en cours + boutons ronds (le CSS la fixe en bas)."""
    chat_id = chat["id"]
    box = st.container(key="mc-tools") if HAS_KEY else st.container()
    with box:
        r = st.session_state.get("reply")
        if r and r["chat"] == chat_id:
            o = db.get_message(r["mid"])
            if o and o["chat_id"] == chat_id:
                umap = db.users_map(chat["members"])
                q = H.quote_info(o, lambda u: (umap.get(u) or {}).get("name", u))
                html(f'<div class="mc-replybar"><b>↩ Réponse à {H.esc(q["name"])}</b><div>{H.esc(q["text"])}</div></div>')
                if st.button("✕ Annuler la réponse", key="reply_x"):
                    st.session_state.pop("reply", None)
                    st.rerun()
        row = st.container(key="mc-btns") if HAS_KEY else st.container()
        with row:
            if st.button("📎", key="t_att", help="Photo, vidéo, document"):
                attach_dialog(me, chat_id)
            if st.button("😊", key="t_stk", help="Stickers"):
                sticker_dialog(me, chat_id)
            if st.button("📞", key="t_call", help="Appel audio ou vidéo"):
                call_dialog(me, chat)
            if st.button("⋯", key="t_act", help="Répondre, transférer, réagir"):
                actions_dialog(me, chat)


def chat_view(me, chat_id, ev=None):
    chat = db.chat_info(chat_id, me)
    if not chat:
        st.session_state.chat = None
        st.rerun()
    handle_event(me, chat, ev)
    fwd = st.session_state.pop("fwd_mid", None)  # demandé depuis le menu ＋ (le dialogue s'ouvre ici, hors popover)
    if fwd:
        forward_dialog(fwd)
    back = st.container(key="mc-back") if HAS_KEY else st.container()
    with back:
        if st.button("←", key="back"):
            st.session_state.chat = None
            st.rerun()
    kw = {"max_chars": 4000}
    if HAS_AUDIO_INPUT:
        kw["accept_audio"] = True       # micro dans la barre d'envoi
    handle_input(me, chat_id, st.chat_input("Écrire un message", **kw))
    messages_fragment(me, chat_id)
    tools_strip(me, chat)


# ============================================================================
# PARTIE 6/6 : Stories, profil et routeur principal
# ============================================================================
def stories_view(me):
    k = st.session_state.setdefault("ks", 0)
    with st.popover("＋ Ajouter une story", **sw(st.popover)):
        t_txt, t_img = st.tabs(["✍️ Texte", "📷 Photo"])
        with t_txt:
            txt = st.text_area("Votre texte", max_chars=200, key=f"st_t_{k}")
            bg = st.pills("Couleur", list(range(len(H.BGS))), format_func=lambda i: H.BG_DOTS[i], default=0, key=f"st_bg_{k}")
            if st.button("Publier", key=f"st_pub_{k}", type="primary") and txt.strip():
                db.add_story(me, "text", txt.strip(), bg or 0)
                st.session_state.ks = k + 1
                st.rerun()
        with t_img:
            img = st.file_uploader("Photo", type=["png", "jpg", "jpeg", "webp"], key=f"st_i_{k}")
            cap = st.text_input("Légende (facultatif)", max_chars=100, key=f"st_c_{k}")
            if img and st.button("Publier la photo", key=f"st_pubi_{k}", type="primary"):
                try:
                    mid = db.save_media(H.shrink(img.getvalue(), 1080), "image/jpeg", img.name)
                    db.add_story(me, "image", cap, 0, mid)
                    st.session_state.ks = k + 1
                    st.rerun()
                except Exception:
                    st.error("Image illisible.")

    stories = db.visible_stories(me)
    if not stories:
        st.info("Aucune story pour le moment. Les stories durent 24 h et sont visibles par vos contacts.")
        return
    umap = db.users_map({s["username"] for s in stories})
    last = {}
    for s in stories:
        last[s["username"]] = s["ts"]
    order = sorted(last, key=lambda u: (u != me, -last[u]))
    who = st.pills("Contacts", order, default=order[0], key="story_user", label_visibility="collapsed",
                   format_func=lambda u: "Ma story" if u == me else umap[u]["name"])
    who = who or order[0]
    tz = browser_tz()
    html(f'<div class="mc-me">{avatar(umap[who], 40, True)}<div><b>{H.esc(umap[who]["name"])}</b></div></div>')
    for s in [s for s in stories if s["username"] == who]:
        when = f'<div class="mc-time">{H.fmt_day(s["ts"], tz)} à {H.fmt_time(s["ts"], tz)}</div>'
        if s["kind"] == "image":
            cap = f'<p>{H.esc(s["body"])}</p>' if s["body"] else ""
            html(f'<div class="mc-story-img"><img src="{media_uri(s["media_id"])}"/>{cap}</div>{when}')
        else:
            html(f'<div class="mc-story" style="background:{H.BGS[s["bg"] % len(H.BGS)]}">{H.esc(s["body"])}</div>{when}')


def profile_view(me):
    u = db.get_user(me)
    k = st.session_state.setdefault("kp", 0)
    html(f'<div style="text-align:center">{avatar(u, 96)}</div>')
    photo = st.file_uploader("Photo de profil", type=["png", "jpg", "jpeg", "webp"], key=f"av_{k}")
    name = st.text_input("Nom affiché", u["name"], max_chars=40)
    about = st.text_input("Statut", u["about"] or "", max_chars=100)
    if st.button("Enregistrer", type="primary", **sw(st.button)):
        avatar_id = None
        if photo:
            try:
                avatar_id = db.save_media(H.shrink(photo.getvalue(), square=256), "image/jpeg", "avatar.jpg")
            except Exception:
                st.error("Image illisible.")
        db.update_profile(me, name, about, avatar_id)
        st.session_state.kp = k + 1
        st.rerun()
    st.divider()
    st.markdown("**Partagez votre nom d’utilisateur** pour qu’on vous ajoute :")
    st.code(f"@{me}", language=None)
    with st.expander("📲 Installer l’application sur le téléphone"):
        st.markdown("- **Android (Chrome)** : menu ⋮ → *Installer l’application* ou *Ajouter à l’écran d’accueil*.\n"
                    "- **iPhone (Safari)** : bouton Partager → *Sur l’écran d’accueil*.\n"
                    "- **Ordinateur (Chrome/Edge)** : icône d’installation dans la barre d’adresse.")
    if db.backend() == "sqlite":
        st.caption("⚠️ Mode démo (SQLite) : sur Streamlit Cloud les données sont effacées à chaque redémarrage. "
                   "Définissez DATABASE_URL (PostgreSQL) pour les conserver.")
    st.caption(f"Diagnostic : Streamlit {getattr(st, '__version__', '?')} · base {db.backend()} · "
               f"gestes {'actifs' if bridge is not None else 'désactivés (bridge_assets.py absent ou illisible)'}")
    if st.button("Se déconnecter", **sw(st.button)):
        logout()


def main():
    me = current_user()
    if not me:
        auth_screen()
        return
    ev = call_bridge(pwa=True)
    view = st.session_state.get("view", "chats")
    if view == "stories":
        top_bar(me, "Stories")
        stories_view(me)
        bottom_nav()
    elif view == "profile":
        top_bar(me, "Profil")
        profile_view(me)
        bottom_nav()
    elif st.session_state.get("chat"):
        chat_view(me, st.session_state.chat, ev)
    else:
        home_view(me)
        bottom_nav()
    toast = st.session_state.pop("toast", None)
    if toast:
        st.toast(toast)


main()
