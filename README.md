# Mbouda City

Messagerie type WhatsApp, **sans numéro de téléphone** : on crée un compte et on partage son `@nom_utilisateur`.
Écrite en Python avec Streamlit, prête pour GitHub et Streamlit Community Cloud.

## Fonctions

- Comptes (nom d'utilisateur + mot de passe), photo de profil, statut
- Discussions privées et groupes, avec nom des membres
- Envoi de photos et de fichiers (8 Mo max, les photos sont compressées)
- Messages vocaux, stickers (emojis géants et mots colorés), réactions (👍 ❤️ 😂 😮 😢 🙏)
- Accusés de lecture : ✓ envoyé, ✓✓ bleu lu (dans un groupe : lu par tous)
- Stories de 24 h (texte coloré ou photo), visibles par vos contacts
- Appels audio et vidéo (via Jitsi, voir « Limites »)
- Thème sombre premium, utilisable sur téléphone

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Les données sont alors dans `data/mbouda.db` (SQLite). Rien d'autre à configurer.

## Déployer (GitHub → Streamlit Cloud)

1. Créez un dépôt GitHub et poussez ce dossier (le `.gitignore` exclut `data/` et les secrets).
2. Créez une base PostgreSQL gratuite (par exemple sur Neon ou Supabase) et copiez son URL de connexion.
3. Sur [share.streamlit.io](https://share.streamlit.io) : **New app** → votre dépôt → fichier principal `app.py`.
4. Dans **Settings → Secrets**, collez :
   ```toml
   DATABASE_URL = "postgresql://utilisateur:motdepasse@hote/base?sslmode=require"
   ```
5. Déployez. Partagez le lien de l'application et votre `@nom_utilisateur`.

> Sans `DATABASE_URL`, l'application fonctionne en SQLite, mais Streamlit Cloud efface le disque à chaque
> redémarrage : comptes et messages disparaissent. C'est acceptable pour une démo, pas pour de vrais utilisateurs.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | Interface Streamlit, en 6 parties numérotées |
| `db.py` | Stockage SQLite / PostgreSQL (comptes, messages, médias, stories) |
| `helpers.py` | Fonctions pures : formats, HTML des bulles, compression d'images |
| `assets/style.css` | Thème |
| `static/` | Icônes et manifeste (installation sur l'écran d'accueil) |
| `.streamlit/config.toml` | Thème et options du serveur |

## Limites à connaître

- **Temps réel par rafraîchissement** : Streamlit n'a pas de WebSocket applicatif. La discussion ouverte se
  met à jour toutes les 3 secondes, la liste des discussions toutes les 4 secondes. Convient à quelques dizaines
  d'utilisateurs ; au-delà, il faut un vrai serveur de messagerie.
- **Appels** : un appel audio ou vidéo ouvre une salle Jitsi dans un nouvel onglet, et l'invitation arrive dans
  la discussion et dans la barre latérale. Il n'y a pas d'appel intégré à la page (Streamlit ne sait pas faire
  de WebRTC entre deux utilisateurs). Selon la politique de `meet.jit.si`, la première personne peut devoir se
  connecter ; pour éviter cela, hébergez votre propre Jitsi et renseignez `CALL_BASE_URL`.
- **Pas de notifications** quand l'onglet est fermé.
- **Pas de chiffrement de bout en bout** : les messages sont lisibles par l'administrateur de la base.
- **Connexion mémorisée dans l'adresse** : le lien contient un jeton de session (`?s=…`) valable 30 jours.
  Ne partagez pas le lien de votre session ; « Se déconnecter » l'annule.
- **Installation sur l'écran d'accueil** : le manifeste et les icônes sont injectés au chargement. Streamlit
  n'autorise pas de service worker, donc pas de mode hors ligne ; sur Streamlit Cloud, l'application est
  encapsulée dans une page par la plateforme, et l'installation peut se limiter à un raccourci.
