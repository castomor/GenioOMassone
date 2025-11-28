import os
import logging
import csv
import random

# Import per FastAPI
from fastapi import FastAPI, Request
# Import per Telegram Bot
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
# Per la lettura delle variabili d'ambiente
from dotenv import load_dotenv

# --- CONFIGURAZIONE GENERALE ---
# load_dotenv() # Decommenta per test locale

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# RENDER_EXTERNAL_HOSTNAME è ancora necessario per l'impostazione del webhook
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME") 

if not TELEGRAM_BOT_TOKEN or not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("Variabili d'ambiente TELEGRAM_BOT_TOKEN o RENDER_EXTERNAL_HOSTNAME mancanti.")

WEBHOOK_URL_BASE = f"https://{RENDER_EXTERNAL_HOSTNAME}"
WEBHOOK_PATH = "/webhook"
CSV_FILE = "characters.csv" 
# Chiave per memorizzare il personaggio corrente nello stato del bot (context.user_data)
CURRENT_CHAR_KEY = 'current_char'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FUNZIONI DI GIOCO E GESTIONE CSV ---

def read_characters():
    """Legge tutti i personaggi dal file CSV."""
    characters = []
    try:
        with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                characters.append(row)
    except FileNotFoundError:
        logger.error(f"File {CSV_FILE} non trovato. Assicurati che esista!")
        return []
    return characters

def select_random_character(context):
    """Seleziona un personaggio casuale dalla lista e lo salva nel contesto utente."""
    characters = read_characters()
    if not characters:
        return None
    
    # Sceglie un personaggio a caso
    char = random.choice(characters)
    
    # Salva il personaggio corrente nel contesto dell'utente (utile se l'utente risponde
    # con un messaggio invece che con un pulsante, ma lo usiamo per tracciare la risposta corretta)
    context.user_data[CURRENT_CHAR_KEY] = char
    return char

# --- GESTORI TELEGRAM (HANDLERS) ---

def get_quiz_keyboard():
    """Restituisce la tastiera inline con le opzioni di risposta."""
    keyboard = [
        [
            InlineKeyboardButton("Genio 🧠", callback_data="GENIUS"),
            InlineKeyboardButton("Massone 📐", callback_data="MASON")
        ],
        [
            InlineKeyboardButton("Entrambi 👑", callback_data="BOTH"),
            InlineKeyboardButton("Persona Comune 🚶", callback_data="COMMON")
        ]
    ]
    # Usiamo un callback per distinguere le risposte di gioco dagli altri pulsanti
    return InlineKeyboardMarkup(keyboard)

def get_post_guess_keyboard():
    """Restituisce la tastiera inline per continuare o chiudere il gioco."""
    keyboard = [
        [
            InlineKeyboardButton("Un altro personaggio! 👉", callback_data="PLAY_AGAIN"),
        ],
        [
            InlineKeyboardButton("Mi fermo qui 👋", callback_data="STOP_GAME")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_and_play(update: Update, context):
    """Funzione unificata per /start e per il pulsante 'Gioca Ancora'."""
    current_char = select_random_character(context)
    
    if current_char:
        message = (
            f"Il personaggio scelto a caso è: **{current_char['Nome']}**\n\n"
            f"Indovina la sua vera identità:"
        )
        
        # Se viene da un callback, usiamo edit_message_text, altrimenti reply_text
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message, 
                reply_markup=get_quiz_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"🎉 **Benvenuto nel quiz randomico!**\n\n{message}", 
                reply_markup=get_quiz_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        # Se viene da un callback o un messaggio, rispondiamo in modo appropriato
        responder = update.callback_query if update.callback_query else update.message
        await responder.reply_text("Errore: Nessun personaggio disponibile nel file CSV.")


async def button_callback_handler(update: Update, context):
    """Gestisce la pressione di tutti i pulsanti Inline."""
    query = update.callback_query
    await query.answer()

    action = query.data
    
    if action == "PLAY_AGAIN":
        await start_and_play(update, context)
        return
    
    if action == "STOP_GAME":
        await query.edit_message_text("Grazie per aver giocato! Ciao! 👋")
        return
        
    # --- Gestione della Risposta al Quiz (GENIUS, MASON, BOTH, COMMON) ---
    user_guess = action
    
    current_char = context.user_data.get(CURRENT_CHAR_KEY)
    
    if not current_char:
        await query.edit_message_text("Errore: Impossibile recuperare il personaggio corrente. Riprova con /start.")
        return
        
    # Verifica la risposta
    correct_answer = current_char['Categoria']
    char_name = current_char['Nome']
    
    if user_guess == correct_answer:
        result_message = (
            f"✅ **Corretto!**\n"
            f"Hai indovinato! **{char_name}** era effettivamente un **{correct_answer.capitalize()}**."
        )
    else:
        result_message = (
            f"❌ **Sbagliato!**\n"
            f"Hai risposto: _{user_guess.capitalize()}_\n"
            f"La risposta corretta era: **{correct_answer.capitalize()}**.\n\n"
            f"Il personaggio era: **{char_name}**."
        )
        
    # Risposta finale e opzione per continuare
    await query.edit_message_text(
        result_message,
        reply_markup=get_post_guess_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    # Rimuovi il personaggio dal contesto dopo la risposta
    context.user_data.pop(CURRENT_CHAR_KEY, None)


# --- CONFIGURAZIONE FASTAPI E WEBHOOK ---

app = FastAPI()
# Aggiungiamo 'context_types' per usare context.user_data
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = application.bot

# Aggiunge i gestori (handlers)
application.add_handler(CommandHandler("start", start_and_play))
application.add_handler(CallbackQueryHandler(button_callback_handler))

@app.on_event("startup")
async def startup_event():
    """Eseguito all'avvio del server: imposta il Webhook."""
    logger.info("Avvio del server...")
    
    full_webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"
    logger.info(f"Tentativo di impostare il Webhook su: {full_webhook_url}")
    
    await bot.delete_webhook()
    
    success = await bot.set_webhook(url=full_webhook_url)
    
    if success:
        logger.info("Webhook impostato con successo!")
    else:
        logger.error("Impostazione del Webhook fallita.")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Bot Server is Running"}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Endpoint principale che riceve gli aggiornamenti da Telegram."""
    try:
        update_json = await request.json()
        update = Update.de_json(update_json, bot)
        await application.process_update(update)
        
        return {"message": "Update processed"}
        
    except Exception as e:
        logger.error(f"Errore nell'elaborazione dell'update: {e}")
        return {"message": "Internal Server Error, but acknowledged"}
