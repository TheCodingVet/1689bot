import os, json, re, logging
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
)

# ---------- Logs ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("1689bot")

# ---------- Fichier de données ----------
DATA_FILE = os.getenv("CONF_JSON", "confession_1689_fr_clean.json")
if not os.path.exists(DATA_FILE):
    raise RuntimeError(
        f"Fichier de données introuvable: {DATA_FILE}.\n"
        "Place 'confession_1689_fr_clean.json' dans ce dossier, "
        "ou définis CONF_JSON=/chemin/vers/ton_fichier.json"
    )

with open(DATA_FILE, "r", encoding="utf-8") as f:
    CONF = json.load(f)

INDEX = CONF.get("index", {})          # ex: "1.2" -> texte
CHAPTERS = CONF.get("chapters", {})    # ex: "1" -> {"title": "...", "paragraphs": {...}}

# ---------- Outils ----------
TELEGRAM_LIMIT = 4096
ARTICLE_RE = re.compile(r"^/(\d{1,2})\.(\d{1,2})\s*$")

def split_chunks(text: str, max_len: int = 4000):
    """Coupe sur double sauts de ligne de préférence pour rester lisible."""
    parts, current = [], []
    for para in text.split("\n\n"):
        bloc = (("\n\n").join(current) + (("\n\n") if current else "") + para)
        if len(bloc) <= max_len:
            current.append(para)
        else:
            if current:
                parts.append(("\n\n").join(current))
            if len(para) <= max_len:
                current = [para]
            else:
                s = para
                while len(s) > max_len:
                    parts.append(s[:max_len])
                    s = s[max_len:]
                current = [s] if s else []
    if current:
        parts.append(("\n\n").join(current))
    return parts

# ---------- Styles ----------
def render_message(ch: str, para: str, header: str, body: str, style: str = "scroll") -> str:
    """
    Styles: "scroll" | "clean" | "box"
    """
    if style == "scroll":
        return "\n".join([f"📜 {ch}.{para} — {header}", "", body])

    if style == "clean":
        return "\n".join([f"{ch}.{para} — {header}", "", body])

    if style == "box":
        title = f"{ch}.{para} — {header}"
        bar = "─" * min(max(len(title), 12), 60)
        return "\n".join([f"┌{bar}┐", f"│ {title}", f"└{bar}┘", "", body])

    return f"{ch}.{para} — {header}\n\n{body}"

DEFAULT_STYLE = "scroll"
STYLE_CHOICES = {"scroll", "clean", "box"}
STYLE_BY_CHAT = defaultdict(lambda: DEFAULT_STYLE)

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bienvenue !\n"
        "Exemples : /1.2  → Chapitre 1, §2\n"
        "Commandes : /chapitres, /help, /style"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage :\n"
        "• /N.M  → Chapitre N, paragraphe M (ex: /1.2)\n"
        "• /chapitres → liste des titres\n"
        "• /style [scroll|clean|box] → choisir l'apparence"
    )

async def chapitres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    for num in sorted(CHAPTERS, key=lambda x: int(x)):
        title = CHAPTERS[num]["title"]
        lines.append(f"{num}. {title}")
    text = "\n".join(lines) if lines else "Aucun chapitre."
    for part in split_chunks(text):
        await update.message.reply_text(part)

async def set_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        cur = STYLE_BY_CHAT[chat_id]
        await update.message.reply_text(
            f"Style actuel: {cur}\n"
            "Utilise: /style scroll | /style clean | /style box"
        )
        return
    choice = context.args[0].strip().lower()
    if choice not in STYLE_CHOICES:
        await update.message.reply_text("Style inconnu. Choisis: scroll, clean, box.")
        return
    STYLE_BY_CHAT[chat_id] = choice
    await update.message.reply_text(f"✅ Style défini sur: {choice}")

async def article_by_slash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    m = ARTICLE_RE.match(text)
    if not m:
        return
    ch, para = m.group(1), m.group(2)
    key = f"{int(ch)}.{int(para)}"
    if key not in INDEX:
        await update.message.reply_text("Introuvable. Vérifie le numéro (ex: /1.2).")
        return
    body = INDEX[key].strip()
    header = CHAPTERS.get(str(int(ch)), {}).get("title", f"Chapitre {ch}")
    style = STYLE_BY_CHAT[update.effective_chat.id]
    full = render_message(ch, para, header, body, style=style)
    for part in split_chunks(full):
        await update.message.reply_text(part)

async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permet d'écrire aussi '1.2' sans le slash."""
    txt = (update.message.text or "").strip()
    if ARTICLE_RE.match("/" + txt):
        update.message.text = "/" + txt
        return await article_by_slash(update, context)
    await update.message.reply_text("Je comprends les requêtes de type /N.M (ex: /1.2). Essaie !")

async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Une erreur est survenue", exc_info=context.error)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Définis la variable d'env BOT_TOKEN avec le token de @BotFather.")

    app = ApplicationBuilder().token(token).build()

    # Error handler
    app.add_error_handler(on_error)

    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("chapitres", chapitres))
    app.add_handler(CommandHandler("style", set_style))

    # Messages /N.M
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(ARTICLE_RE), article_by_slash))

    # Attrape-tout
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_all))

    # Lancement polling (drop les updates en attente au besoin)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

