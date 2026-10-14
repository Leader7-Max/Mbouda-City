"""
Mbouda City : messagerie sans numéro de téléphone, en Streamlit.
Lancer : streamlit run app.py

app.py est organisé en 6 parties :
  1/6  Configuration, thème et utilitaires
  2/6  Connexion / création de compte
  3/6  Barre latérale : menu, liste des discussions, nouvelles discussions
  4/6  Affichage des messages
  5/6  Écran de discussion : envoi, vocaux, stickers, réactions, appels
  6/6  Stories, profil, PWA et routeur principal
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

ROOT = os.path.dirname(os.path.abspath(__file__))
_ICON = os.path.join(ROOT, "static", "icon-192.png")
st.set_page_config(page_title="Mbouda City", page_icon=_ICON if os.path.exists(_ICON) else "💬",
                   layout="centered", initial_sidebar_state="auto")

CALL_BASE = (db.secret("CALL_BASE_URL") or "https://meet.jit.si").rstrip("/")


def sw(fn):
    """Largeur pleine, compatible avec toutes les versions de Streamlit."""
    p = inspect.signature(fn).parameters
    if "width" in p:
        return {"width": "stretch"}
    return {"use_container_width": True} if "use_container_width" in p else {}


@st.cache_resource
def _css():
    with open(os.path.join(ROOT, "assets", "style.css"), encoding="utf-8") as f:
        return f.read()


st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=300)
def media_uri(mid):
    m = db.get_media(mid)
    return f"data:{m[1]};base64,{base64.b64encode(m[0]).decode()}" if m else ""


@st.cache_data(show_spinner=False, max_entries=24, ttl=600)
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


def run_js(js):
    components.html(f"<script>{js}</script>", height=0)


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
    st.session_state.update(view="chats", chat=chat_id, close_sb=True)
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
        st.caption("Aucune discussion. Touchez « ＋ Discussion » pour commencer.")
    for c in chats:
        label = chat_title(c, me, umap)
        if c["unread"]:
            label += f'  🟢 {c["unread"]}'
        if c["last"]:
            label += "  —  " + H.preview_text(c["last"], me)[:28]
        active = st.session_state.get("chat") == c["id"] and st.session_state.get("view") == "chats"
        if st.button(label, key=f'chat_{c["id"]}', type="primary" if active else "secondary", **sw(st.button)):
            open_chat(c["id"])


def sidebar(me):
    u = db.get_user(me)
    with st.sidebar:
        html('<div class="mc-brand">Mbouda City</div>')
        html(f'<div class="mc-me">{avatar(u, 44)}<div><b>{H.esc(u["name"])}</b><br><small>@{H.esc(me)}</small></div></div>')
        view = st.session_state.get("view", "chats")
        for key, label in (("chats", "💬 Discussions"), ("stories", "◎ Stories"), ("profile", "👤 Mon profil")):
            if st.button(label, key=f"nav_{key}", type="primary" if view == key else "secondary", **sw(st.button)):
                st.session_state.update(view=key, close_sb=key != "chats")
                st.rerun()
        if st.button("＋ Discussion", key="b_new", **sw(st.button)):
            new_chat_dialog()
        if st.button("＋ Groupe", key="b_grp", **sw(st.button)):
            new_group_dialog()
        st.divider()
        chat_list(me)


# ============================================================================
# PARTIE 4/6 : Affichage des messages
# ============================================================================
def render_widget(w, my_name):
    """Composants natifs sous la bulle : vocal, fichier, appel."""
    if w["type"] == "voice":
        blob = media_blob(w["media_id"])
        if blob:
            st.audio(blob[0], format=blob[1] or "audio/wav")
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
                               reacts.get(m["id"], {}), media_uri, tz)
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
SCROLL_JS = """(function(){ /*__ID__*/
  const go=()=>{const p=window.parent,d=p.document;
    const m=d.querySelector('[data-testid="stMain"]')||d.querySelector('section.main');
    if(m) m.scrollTo({top:m.scrollHeight,behavior:'smooth'}); p.scrollTo(0,d.body.scrollHeight);};
  setTimeout(go,150); setTimeout(go,700);})();"""


@st.fragment(run_every=3)
def messages_fragment(me, chat_id):
    """Rafraîchi toutes les 3 s : en-tête, messages, accusés de lecture, réactions."""
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
    html(f'<div class="mc-head">{avatar(head_user, 46)}<div><b>{title}</b><br><small>{sub}</small></div></div>')

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

    last_id = msgs[-1]["id"] if msgs else 0
    if st.session_state.get(f"seen_{chat_id}") != last_id:
        st.session_state[f"seen_{chat_id}"] = last_id
        run_js(SCROLL_JS.replace("__ID__", str(last_id)))


def send_upload(me, chat_id, f):
    data, name, mime = f.getvalue(), f.name, f.type or "application/octet-stream"
    if len(data) > H.MAX_FILE:
        st.error(f"Fichier trop lourd ({H.fmt_size(len(data))}). Maximum : {H.fmt_size(H.MAX_FILE)}.")
        return False
    if mime.startswith("image/"):
        try:
            data, mime = H.shrink(data), "image/jpeg"
            db.send(chat_id, me, "image", "", db.save_media(data, mime, name), name)
            return True
        except Exception:
            data = f.getvalue()  # image illisible : envoyée comme fichier
            mime = f.type or "application/octet-stream"
    db.send(chat_id, me, "file", "", db.save_media(data, mime, name), name)
    return True


def cb_sticker(key, kind, me, chat_id):
    v = st.session_state.get(key)
    if not v:
        return
    body = "e:" + v if kind == "e" else f"t:{H.STICKER_WORDS.index(v) % len(H.BGS)}:{v}"
    db.send(chat_id, me, "sticker", body)
    st.session_state[key] = None


def cb_react(me):
    v, mid = st.session_state.get("react_pick"), st.session_state.get("react_msg")
    if v and mid:
        db.toggle_reaction(mid, me, v)
    st.session_state["react_pick"] = None


def start_call(me, chat, video):
    room = f"MboudaCity-{chat['id']}-{secrets.token_hex(4)}"
    db.send(chat["id"], me, "call", room, meta="video" if video else "audio")
    name = (db.get_user(me) or {}).get("name", me)
    st.session_state.my_call = {"chat": chat["id"], "ts": time.time(), "url": call_url(room, video, name)}


def tools_popover(me, chat):
    chat_id = chat["id"]
    k = st.session_state.setdefault("k", 0)  # change après chaque envoi pour vider les widgets
    with st.popover("＋  Joindre · Vocal · Stickers · Appel", **sw(st.popover)):
        t_file, t_voice, t_stk, t_react, t_call = st.tabs(["📎", "🎤", "😊", "😀", "📞"])
        with t_file:
            st.caption("Photo, document, vidéo (8 Mo max)")
            f = st.file_uploader("Fichier", key=f"up_{k}", label_visibility="collapsed")
            if f and st.button("Envoyer le fichier", key=f"upb_{k}", type="primary"):
                if send_upload(me, chat_id, f):
                    st.session_state.k = k + 1
                    st.rerun()
        with t_voice:
            st.caption("Appuyez sur le micro, parlez, puis envoyez.")
            a = st.audio_input("Message vocal", key=f"au_{k}", label_visibility="collapsed")
            if a and st.button("Envoyer le vocal", key=f"aub_{k}", type="primary"):
                data = a.getvalue()
                if len(data) > H.MAX_VOICE:
                    st.error("Vocal trop long.")
                else:
                    mid = db.save_media(data, "audio/wav", "vocal.wav")
                    db.send(chat_id, me, "voice", "", mid, str(round(H.wav_duration(data))))
                    st.session_state.k = k + 1
                    st.rerun()
        with t_stk:
            st.caption("Emojis géants")
            st.pills("Emojis", H.STICKER_EMOJIS, key="stk_e", label_visibility="collapsed",
                     on_change=cb_sticker, args=("stk_e", "e", me, chat_id))
            st.caption("Mots")
            st.pills("Mots", H.STICKER_WORDS, key="stk_w", label_visibility="collapsed",
                     on_change=cb_sticker, args=("stk_w", "t", me, chat_id))
        with t_react:
            recent = [m for m in db.chat_messages(chat_id, 15) if m["kind"] != "call"][::-1]
            if not recent:
                st.caption("Aucun message.")
            else:
                umap = db.users_map(chat["members"])
                label = lambda i: next(
                    f'{(umap.get(m["sender"]) or {}).get("name", m["sender"])} : {H.preview_text(m, "")[:34]}'
                    for m in recent if m["id"] == i)
                st.selectbox("Message", [m["id"] for m in recent], format_func=label, key="react_msg")
                st.pills("Réaction", H.REACTIONS, key="react_pick", on_change=cb_react, args=(me,))
        with t_call:
            if chat["kind"] == "dm" or len(chat["members"]) > 1:
                st.caption("L’appel s’ouvre dans un nouvel onglet (Jitsi). Les autres reçoivent l’invitation ici.")
                c1 = st.button("📞 Appel audio", key="call_a", **sw(st.button))
                c2 = st.button("🎥 Appel vidéo", key="call_v", **sw(st.button))
                if c1 or c2:
                    start_call(me, chat, video=c2)
                    st.rerun()


def chat_view(me, chat_id):
    chat = db.chat_info(chat_id, me)
    if not chat:
        st.session_state.chat = None
        st.rerun()
    text = st.chat_input("Écrire un message", max_chars=4000)
    if text and text.strip():
        db.send(chat_id, me, "text", text.strip())
    messages_fragment(me, chat_id)
    tools_popover(me, chat)


# ============================================================================
# PARTIE 6/6 : Stories, profil, PWA et routeur principal
# ============================================================================
def stories_view(me):
    st.markdown("### Stories")
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
    st.markdown("### Mon profil")
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
    if st.button("Se déconnecter", **sw(st.button)):
        logout()


PWA_JS = """(function(){
  for (const w of [window.parent, window.top]) { try {
    const d = w.document; if (d.querySelector('link[rel="manifest"]')) continue;
    const add = (tag, attrs) => { const e = d.createElement(tag); Object.assign(e, attrs); d.head.appendChild(e); };
    add('link', {rel: 'manifest', href: '/app/static/manifest.webmanifest'});
    add('link', {rel: 'apple-touch-icon', href: '/app/static/apple-touch-icon.png'});
    add('meta', {name: 'theme-color', content: '#0a0e13'});
    add('meta', {name: 'apple-mobile-web-app-capable', content: 'yes'});
    add('meta', {name: 'mobile-web-app-capable', content: 'yes'});
    add('meta', {name: 'apple-mobile-web-app-title', content: 'Mbouda City'});
  } catch (e) {} }
})();"""

CLOSE_SIDEBAR_JS = """(function(){const p=window.parent; if(p.innerWidth>640) return;
  const d=p.document, b=d.querySelector('[data-testid="stSidebarCollapseButton"] button')
    ||d.querySelector('[data-testid="stSidebarHeader"] button'); if(b) b.click();})();"""


def main():
    me = current_user()
    if not me:
        auth_screen()
        return
    sidebar(me)
    view = st.session_state.get("view", "chats")
    if view == "stories":
        stories_view(me)
    elif view == "profile":
        profile_view(me)
    elif st.session_state.get("chat"):
        chat_view(me, st.session_state.chat)
    else:
        html('<div class="mc-hero"><div class="mc-logo">M</div><h1>Mbouda City</h1>'
             '<p>Choisissez une discussion dans le menu ☰, ou touchez « ＋ Discussion ».</p></div>')
    if st.session_state.pop("close_sb", False):
        run_js(CLOSE_SIDEBAR_JS)
    if not st.session_state.get("pwa"):
        st.session_state.pwa = True
        run_js(PWA_JS)


main()
