"""
db.py : stockage de Mbouda City.

- SQLite par défaut (fichier data/mbouda.db) : parfait en local.
- PostgreSQL (Neon, Supabase, Railway…) dès que DATABASE_URL est défini, dans les
  variables d'environnement ou dans .streamlit/secrets.toml. À utiliser sur Streamlit
  Cloud, dont le disque est effacé à chaque redémarrage.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager


# ---------------------------------------------------------------- configuration
def secret(name, default=""):
    """Variable d'environnement, sinon .streamlit/secrets.toml."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def _url():
    url = secret("DATABASE_URL")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


URL = _url()
PG = URL.startswith("postgresql")
SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mbouda.db")
_lock = threading.Lock()
_ready = False
_pool = None

if PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    _INTEGRITY = (psycopg2.IntegrityError,)
    _STALE = (psycopg2.OperationalError, psycopg2.InterfaceError)
else:
    _INTEGRITY = (sqlite3.IntegrityError,)
    _STALE = ()


def backend():
    return "postgres" if PG else "sqlite"


# ---------------------------------------------------------------- connexions
@contextmanager
def _cx():
    global _pool
    if PG:
        if _pool is None:
            with _lock:
                if _pool is None:
                    _pool = psycopg2.pool.ThreadedConnectionPool(1, 8, URL, connect_timeout=15)
        c = _pool.getconn()
        try:
            yield c
            c.commit()
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            raise
        finally:
            _pool.putconn(c, close=bool(c.closed))
    else:
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        c = sqlite3.connect(SQLITE_PATH, timeout=20)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


def _exec(sql, args=(), fetch=False, new_id=False):
    """Exécute une requête. fetch=True -> liste de dict ; new_id=True -> id inséré."""
    _init()
    if PG:
        sql = sql.replace("?", "%s")
        if new_id:
            sql += " RETURNING id"
    for attempt in (0, 1):
        try:
            with _cx() as c:
                cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if PG else c.cursor()
                cur.execute(sql, tuple(args))
                if fetch:
                    return [dict(r) for r in cur.fetchall()]
                if new_id:
                    return cur.fetchone()["id"] if PG else cur.lastrowid
                return None
        except _STALE:
            if attempt:
                raise  # connexion morte (Neon en veille...) : on réessaie une fois


def _all(sql, args=()):
    return _exec(sql, args, fetch=True)


def _one(sql, args=()):
    r = _all(sql, args)
    return r[0] if r else None


def _marks(items):
    return ",".join("?" * len(items))


def _init():
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        pk = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        blob = "BYTEA" if PG else "BLOB"
        real = "DOUBLE PRECISION" if PG else "REAL"
        ddl = [
            f"""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, name TEXT NOT NULL, pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
                avatar_id INTEGER, about TEXT DEFAULT '', last_seen {real} DEFAULT 0, created {real} DEFAULT 0)""",
            f"CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires {real} NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS media (id {pk}, data {blob} NOT NULL, mime TEXT, name TEXT, size INTEGER)",
            f"CREATE TABLE IF NOT EXISTS chats (id {pk}, kind TEXT NOT NULL, name TEXT DEFAULT '', created_by TEXT, created {real})",
            f"CREATE TABLE IF NOT EXISTS members (chat_id INTEGER NOT NULL, username TEXT NOT NULL, last_read {real} DEFAULT 0, PRIMARY KEY (chat_id, username))",
            f"""CREATE TABLE IF NOT EXISTS messages (
                id {pk}, chat_id INTEGER NOT NULL, sender TEXT NOT NULL, kind TEXT NOT NULL,
                body TEXT DEFAULT '', media_id INTEGER, meta TEXT DEFAULT '', ts {real} NOT NULL)""",
            "CREATE TABLE IF NOT EXISTS reactions (message_id INTEGER NOT NULL, username TEXT NOT NULL, emoji TEXT NOT NULL, PRIMARY KEY (message_id, username))",
            f"CREATE TABLE IF NOT EXISTS stories (id {pk}, username TEXT NOT NULL, kind TEXT NOT NULL, body TEXT DEFAULT '', bg INTEGER DEFAULT 0, media_id INTEGER, ts {real} NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages (chat_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_story_ts ON stories (ts)",
            "CREATE INDEX IF NOT EXISTS idx_members_user ON members (username)",
        ]
        with _cx() as c:
            cur = c.cursor()
            if not PG:
                cur.execute("PRAGMA journal_mode=WAL")
            for s in ddl:
                cur.execute(s)
        _ready = True


# ---------------------------------------------------------------- comptes
USER_RE = re.compile(r"^[a-z0-9_.]{3,20}$")
_fails = {}


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150_000).hex()


def clean_username(u):
    return (u or "").strip().lower().lstrip("@")


def register(username, password, name):
    u = clean_username(username)
    if not USER_RE.match(u):
        return None, "Nom d’utilisateur invalide (3 à 20 caractères : a-z, 0-9, _ et .)"
    if len(password or "") < 6:
        return None, "Mot de passe : 6 caractères minimum"
    if _one("SELECT username FROM users WHERE username=?", (u,)):
        return None, "Ce nom d’utilisateur est déjà pris"
    salt = secrets.token_hex(16)
    now = time.time()
    try:
        _exec("INSERT INTO users (username,name,pw_hash,salt,about,last_seen,created) VALUES (?,?,?,?,?,?,?)",
              (u, (name or "").strip()[:40] or u, _hash(password, salt), salt, "Disponible sur Mbouda City", now, now))
    except _INTEGRITY:
        return None, "Ce nom d’utilisateur est déjà pris"
    return u, None


def login(username, password):
    u = clean_username(username)
    now = time.time()
    recent = [t for t in _fails.get(u, []) if now - t < 300]
    if len(recent) >= 8:
        return None, "Trop d’essais. Réessayez dans quelques minutes."
    r = _one("SELECT username,pw_hash,salt FROM users WHERE username=?", (u,))
    if not r or not hmac.compare_digest(r["pw_hash"], _hash(password or "", r["salt"])):
        _fails[u] = recent + [now]
        return None, "Identifiants incorrects"
    _fails.pop(u, None)
    return u, None


def new_session(username):
    tok = secrets.token_urlsafe(32)
    _exec("INSERT INTO sessions (token,username,expires) VALUES (?,?,?)", (tok, username, time.time() + 30 * 86400))
    return tok


def user_from_token(tok):
    r = _one("SELECT username,expires FROM sessions WHERE token=?", (tok or "",))
    return r["username"] if r and r["expires"] > time.time() else None


def end_session(tok):
    _exec("DELETE FROM sessions WHERE token=?", (tok or "",))


_PUB = "username,name,avatar_id,about,last_seen"


def get_user(username):
    return _one(f"SELECT {_PUB} FROM users WHERE username=?", (username,))


def users_map(names):
    names = list(set(names))
    if not names:
        return {}
    return {r["username"]: r for r in _all(f"SELECT {_PUB} FROM users WHERE username IN ({_marks(names)})", names)}


def touch(username):
    _exec("UPDATE users SET last_seen=? WHERE username=?", (time.time(), username))


def update_profile(username, name=None, about=None, avatar_id=None):
    if name is not None and name.strip():
        _exec("UPDATE users SET name=? WHERE username=?", (name.strip()[:40], username))
    if about is not None:
        _exec("UPDATE users SET about=? WHERE username=?", (about.strip()[:100], username))
    if avatar_id is not None:
        old = _one("SELECT avatar_id FROM users WHERE username=?", (username,))
        _exec("UPDATE users SET avatar_id=? WHERE username=?", (avatar_id, username))
        if old and old["avatar_id"]:
            delete_media(old["avatar_id"])


def search_users(q, me, limit=15):
    q = re.sub(r"[%_]", "", clean_username(q))
    if len(q) < 2:
        return []
    like = f"%{q}%"
    return _all(f"SELECT {_PUB} FROM users WHERE username<>? AND (username LIKE ? OR LOWER(name) LIKE ?) ORDER BY username LIMIT {int(limit)}",
                (me, like, like))


# ---------------------------------------------------------------- médias
def save_media(data, mime, name):
    return _exec("INSERT INTO media (data,mime,name,size) VALUES (?,?,?,?)",
                 (psycopg2.Binary(data) if PG else data, mime, (name or "")[:200], len(data)), new_id=True)


def get_media(mid):
    r = _one("SELECT data,mime,name FROM media WHERE id=?", (mid,))
    return (bytes(r["data"]), r["mime"], r["name"]) if r else None


def delete_media(mid):
    _exec("DELETE FROM media WHERE id=?", (mid,))


# ---------------------------------------------------------------- discussions
def is_member(chat_id, username):
    return bool(_one("SELECT 1 AS x FROM members WHERE chat_id=? AND username=?", (chat_id, username)))


def dm_with(me, other):
    other = clean_username(other)
    if not other or other == me or not get_user(other):
        return None
    r = _one("""SELECT c.id FROM chats c
                JOIN members a ON a.chat_id=c.id AND a.username=?
                JOIN members b ON b.chat_id=c.id AND b.username=?
                WHERE c.kind='dm'""", (me, other))
    if r:
        return r["id"]
    cid = _exec("INSERT INTO chats (kind,name,created_by,created) VALUES ('dm','',?,?)", (me, time.time()), new_id=True)
    for u in (me, other):
        _exec("INSERT INTO members (chat_id,username,last_read) VALUES (?,?,?)", (cid, u, time.time() if u == me else 0))
    return cid


def create_group(me, name, usernames):
    name = (name or "").strip()[:40]
    if not name:
        return None, "Donnez un nom au groupe"
    others = {clean_username(u) for u in usernames} - {me, ""}
    found = users_map(others)
    missing = sorted(others - set(found))
    if missing:
        return None, "Utilisateur introuvable : @" + ", @".join(missing)
    if len(others) < 2:
        return None, "Un groupe demande au moins 2 autres membres"
    cid = _exec("INSERT INTO chats (kind,name,created_by,created) VALUES ('group',?,?,?)", (name, me, time.time()), new_id=True)
    for u in [me, *sorted(others)]:
        _exec("INSERT INTO members (chat_id,username,last_read) VALUES (?,?,?)", (cid, u, time.time() if u == me else 0))
    send(cid, me, "text", f"Groupe « {name} » créé")
    return cid, None


def contacts_of(me):
    """Utilisateurs avec qui je partage au moins une discussion."""
    rows = _all("""SELECT DISTINCT m2.username FROM members m1
                   JOIN members m2 ON m2.chat_id=m1.chat_id AND m2.username<>m1.username
                   WHERE m1.username=?""", (me,))
    return users_map([r["username"] for r in rows])


def chat_info(chat_id, me):
    c = _one("SELECT id,kind,name FROM chats WHERE id=?", (chat_id,))
    if not c:
        return None
    ms = _all("SELECT username,last_read FROM members WHERE chat_id=?", (chat_id,))
    if me not in [m["username"] for m in ms]:
        return None
    c["members"] = [m["username"] for m in ms]
    c["reads"] = {m["username"]: m["last_read"] or 0 for m in ms}
    return c


def my_chats(me):
    cs = _all("""SELECT c.id,c.kind,c.name FROM chats c
                 JOIN members m ON m.chat_id=c.id WHERE m.username=?""", (me,))
    if not cs:
        return []
    ids = [c["id"] for c in cs]
    mk = _marks(ids)
    mem = {}
    for r in _all(f"SELECT chat_id,username FROM members WHERE chat_id IN ({mk})", ids):
        mem.setdefault(r["chat_id"], []).append(r["username"])
    last = {r["chat_id"]: r for r in _all(
        f"SELECT * FROM messages WHERE id IN (SELECT MAX(id) FROM messages WHERE chat_id IN ({mk}) GROUP BY chat_id)", ids)}
    unread = {r["chat_id"]: r["n"] for r in _all(
        """SELECT ms.chat_id, COUNT(*) AS n FROM messages ms
           JOIN members m ON m.chat_id=ms.chat_id AND m.username=?
           WHERE ms.sender<>? AND ms.ts>COALESCE(m.last_read,0) GROUP BY ms.chat_id""", (me, me))}
    for c in cs:
        c["members"] = mem.get(c["id"], [])
        c["last"] = last.get(c["id"])
        c["unread"] = unread.get(c["id"], 0)
    cs.sort(key=lambda c: (c["last"] or {}).get("ts", 0), reverse=True)
    return cs


def mark_read(chat_id, username):
    _exec("UPDATE members SET last_read=? WHERE chat_id=? AND username=?", (time.time(), chat_id, username))


# ---------------------------------------------------------------- messages
KINDS = {"text", "image", "file", "voice", "sticker", "call"}


def send(chat_id, sender, kind, body="", media_id=None, meta=""):
    if kind not in KINDS or not is_member(chat_id, sender):
        return None
    return _exec("INSERT INTO messages (chat_id,sender,kind,body,media_id,meta,ts) VALUES (?,?,?,?,?,?,?)",
                 (chat_id, sender, kind, (body or "")[:4000], media_id, (meta or "")[:200], time.time()), new_id=True)


def chat_messages(chat_id, limit=50):
    rows = _all(f"SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT {int(limit)}", (chat_id,))
    return rows[::-1]


def reactions_for(message_ids):
    if not message_ids:
        return {}
    out = {}
    for r in _all(f"SELECT message_id,username,emoji FROM reactions WHERE message_id IN ({_marks(message_ids)})", list(message_ids)):
        out.setdefault(r["message_id"], {}).setdefault(r["emoji"], []).append(r["username"])
    return out


def toggle_reaction(message_id, username, emoji):
    emoji = (emoji or "")[:8]
    m = _one("SELECT chat_id FROM messages WHERE id=?", (message_id,))
    if not emoji or not m or not is_member(m["chat_id"], username):
        return
    cur = _one("SELECT emoji FROM reactions WHERE message_id=? AND username=?", (message_id, username))
    if cur and cur["emoji"] == emoji:
        _exec("DELETE FROM reactions WHERE message_id=? AND username=?", (message_id, username))
    elif cur:
        _exec("UPDATE reactions SET emoji=? WHERE message_id=? AND username=?", (emoji, message_id, username))
    else:
        _exec("INSERT INTO reactions (message_id,username,emoji) VALUES (?,?,?)", (message_id, username, emoji))


# ---------------------------------------------------------------- stories (24 h)
def add_story(username, kind, body="", bg=0, media_id=None):
    return _exec("INSERT INTO stories (username,kind,body,bg,media_id,ts) VALUES (?,?,?,?,?,?)",
                 (username, kind, (body or "")[:300], int(bg or 0), media_id, time.time()), new_id=True)


def visible_stories(me):
    return _all("""SELECT * FROM stories WHERE ts>? AND (username=? OR username IN
                     (SELECT m2.username FROM members m1 JOIN members m2 ON m2.chat_id=m1.chat_id
                      WHERE m1.username=?)) ORDER BY ts""", (time.time() - 86400, me, me))


def purge_stories():
    old = _all("SELECT id,media_id FROM stories WHERE ts<?", (time.time() - 86400,))
    for r in old:
        if r["media_id"]:
            delete_media(r["media_id"])
        _exec("DELETE FROM stories WHERE id=?", (r["id"],))
    _exec("DELETE FROM sessions WHERE expires<?", (time.time(),))
