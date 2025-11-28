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
# load_dotenv() # Decommenta questa riga se testi in locale usando un file .env

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME") 

if not TELEGRAM_BOT_TOKEN or not RENDER_EXTERNAL_HOSTNAME:
    raise ValueError("Variabili d'ambiente TELEGRAM_BOT_TOKEN o RENDER_EXTERNAL_HOSTNAME mancanti.")

WEBHOOK_URL_BASE = f"https://{RENDER_EXTERNAL_HOSTNAME}"
WEBHOOK_PATH = "/webhook"
CSV_FILE = "characters.csv" 
CURRENT_CHAR_KEY = 'current_char'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FUNZIONI DI GIOCO E GESTIONE CSV ---

def read_characters():
    """Legge tutti i personaggi dal file CSV."""
    characters = []
    try:
        # csv.DictReader leggerà le colonne Nome, Categoria, Bio
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
    
    char = random.choice(characters)
    context.user_data[CURRENT_CHAR_KEY] = char
    return char

def format_category_name(category_key):
    """Formatta la chiave interna italiana per la visualizzazione nei messaggi di errore."""
    mapping = {
        "GENIO": "Genio",
        "MASSONE": "Massone",
        "ENTRAMBI": "Genio e Massone",
        "COMUNE": "Persona Comune"
    }
    # Restituisce il valore formattato, o la chiave se non trovata
    return mapping.get(category_key, category_key)

# FUNZIONE AGGIORNATA: Legge direttamente il campo Bio completo dal CSV
def get_bio_explanation(current_char):
    """Restituisce il contenuto del campo 'Bio' che contiene già la spiegazione completa e formattata."""
    return current_char.get('Bio', '**Errore**: Informazioni biografiche non disponibili.')


# --- GESTORI TELEGRAM (HANDLERS) ---

def get_quiz_keyboard():
    """Restituisce la tastiera inline con le opzioni di risposta."""
    keyboard = [
        [
            InlineKeyboardButton("Genio 🧠", callback_data="GENIO"),
            InlineKeyboardButton("Massone 📐", callback_data="MASSONE")
        ],
        [
            InlineKeyboardButton("Entrambi 👑", callback_data="ENTRAMBI"),
            InlineKeyboardButton("Persona Comune 🚶", callback_data="COMUNE")
        ]
    ]
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
        responder = update.callback_query.message if update.callback_query else update.message
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
        context.user_data.pop(CURRENT_CHAR_KEY, None)
        return
        
    # --- Gestione della Risposta al Quiz ---
    user_guess = action
    
    current_char = context.user_data.get(CURRENT_CHAR_KEY)
    
    if not current_char:
        await query.edit_message_text("Sessione scaduta. Riprova con /start.")
        return
        
    # Verifica la risposta
    correct_answer = current_char['Categoria']
    user_guess_it = format_category_name(user_guess)
    
    # 1. Ottiene la spiegazione biografica completa DALLA COLONNA UNICA "Bio"
    bio_explanation_full = get_bio_explanation(current_char)

    # 2. Messaggio di ESITO (Corretto/Sbagliato)
    if user_guess == correct_answer:
        result_message = (
            f"✅ **Corretto!** Hai indovinato!\n\n"
            f"{bio_explanation_full}"
        )
    else:
        result_message = (
            f"❌ **Sbagliato!** Hai risposto: _{user_guess_it}_\n\n"
            f"La risposta corretta ({format_category_name(correct_answer)}) è:\n"
            f"{bio_explanation_full}"
        )
        
    # Risposta finale e opzione per continuare
    await query.edit_message_text(
        result_message,
        reply_markup=get_post_guess_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data.pop(CURRENT_CHAR_KEY, None)


# --- CONFIGURAZIONE FASTAPI E PTB ---

app = FastAPI()
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = application.bot

application.add_handler(CommandHandler("start", start_and_play))
application.add_handler(CallbackQueryHandler(button_callback_handler))

# --- GESTIONE DEGLI EVENTI DI AVVIO/SPEGNIMENTO ---

@app.on_event("startup")
async def startup_event():
    logger.info("Avvio del server...")
    
    await application.initialize()
    await application.start()
    
    full_webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"
    logger.info(f"Tentativo di impostare il Webhook su: {full_webhook_url}")
    
    await bot.delete_webhook()
    
    success = await bot.set_webhook(url=full_webhook_url)
    
    if success:
        logger.info("Webhook impostato con successo!")
    else:
        logger.error("Impostazione del Webhook fallita.")

@app.on_event("shutdown")
async def shutdown_event():
    """Eseguito alla chiusura del server: spegne l'Application PTB."""
    logger.info("Spegnimento dell'Application PTB.")
    await application.stop()


# --- ENDPOINT FASTAPI ---

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Bot Server is Running"}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Endpoint principale che riceve gli aggiornamenti da Telegram."""
    try:
        update_json = await request.json()
        await application.update_queue.put(
            Update.de_json(data=update_json, bot=bot)
        )
        
        return {"message": "Update processed"}
        
    except Exception as e:
        logger.error(f"Errore nell'elaborazione dell'update: {e}")
        return {"message": "Internal Server Error, but acknowledged"}
