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

# --- CONFIGURAZIONE GENERALE ---

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
    """Mappa le chiavi interne (COMUNE, GENIO) in testo formattato in italiano per l'utente."""
    mapping = {
        "GENIO": "Genio",
        "MASSONE": "Massone",
        "ENTRAMBI": "Genio e Massone",
        "COMUNE": "Persona Comune",
        "PERSONA COMUNE": "Persona Comune" # Tolleranza per il vecchio errore CSV
    }
    # Assicura che la chiave sia in maiuscolo prima della traduzione
    return mapping.get(category_key.strip().upper(), category_key)

# FUNZIONE AGGIORNATA: Estrae e normalizza la Bio per il messaggio di spiegazione
def get_bio_explanation(current_char):
    """Restituisce il contenuto del campo 'Bio' pulito, che contiene la spiegazione completa e formattata."""
    # Rimuoviamo la Categoria ripetuta e puliamo il testo per la presentazione.
    
    # Prende la categoria corretta pulita (es. 'MASSONE')
    correct_answer = str(current_char.get('Categoria', '')).strip().upper()
    
    # Prende il contenuto completo della Bio
    full_bio_text = current_char.get('Bio', '**Errore**: Informazioni biografiche non disponibili nel CSV.')

    # 1. Trova la parte della categoria che si ripete all'inizio del campo Bio (es. 'È un **Massone**. Precisamente: ')
    # Usiamo una logica generica basata sulla frase che abbiamo costruito precedentemente.
    
    # Mappiamo la categoria per trovare la parte che si ripete e la rimuoviamo, lasciando solo la spiegazione.
    if full_bio_text.startswith("È un **Genio e Massone**."):
        # Per ENTRAMBI, vogliamo tutta la spiegazione biografica complessa
        return full_bio_text.replace(f"È un **Genio e Massone**.\n", "")
    elif full_bio_text.startswith(f"**{current_char['Nome']}** è un **{format_category_name(correct_answer)}**."):
        # Se la bio inizia con il nome completo, manteniamo solo la spiegazione (caso COMUNE non gestito)
        return full_bio_text.replace(f"**{current_char['Nome']}** è una **{format_category_name('COMUNE')}**, proprio come te. (Non ha particolari meriti noti come genio o affiliazioni massoniche).", "proprio come te. (Non ha particolari meriti noti come genio o affiliazioni massoniche).")

    # PATCH DEFINITIVA: cerca la frase iniziale generica e la rimuove
    generic_start = f"È un **{format_category_name(correct_answer)}**."
    
    # Se la Bio inizia con la frase "È un [Categoria]..." la rimuoviamo per evitare la ripetizione
    if full_bio_text.strip().startswith(generic_start):
        # Rimuove la parte iniziale (es. "È un **Massone**.") lasciando solo "Precisamente: ..."
        return full_bio_text.strip().replace(generic_start, "").strip()
    
    # Rimuove il nome del personaggio dalla bio per renderla riutilizzabile:
    if full_bio_text.startswith(f"**{current_char['Nome']}**"):
        # Cerca la fine della frase di introduzione, es. trova il punto dopo il nome
        # Manteniamo la bio come è stata costruita nell'ultimo blocco CSV.
        return full_bio_text
        
    return full_bio_text # In caso di fallimento della pulizia, restituisce il testo intero

# --- GESTORI TELEGRAM (HANDLERS) ---
# ... (omessi per brevità, sono identici al codice precedente) ...
# [La logica di start_and_play, get_quiz_keyboard, get_post_guess_keyboard, startup/shutdown rimane invariata]


async def button_callback_handler(update: Update, context):
    """Gestisce la pressione di tutti i pulsanti Inline e verifica la risposta."""
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
    
    current_char = context.user_data.get(CURRENT_CHAR_KEY)
    
    if not current_char:
        await query.edit_message_text("Sessione scaduta. Riprova con /start.")
        return
        
    # LOGICA DI CONFRONTO ROBUSTA: Normalizzazione per risolvere i bug del CSV/spazi
    user_guess = action.strip().upper() 
    correct_answer = str(current_char['Categoria']).strip().upper()
    
    # Patch per allineare il vecchio "PERSONA COMUNE" a "COMUNE" se necessario
    if correct_answer == "PERSONA COMUNE":
        correct_answer = "COMUNE" 
    
    esito_corretto = (user_guess == correct_answer)

    # Variabili per i messaggi di output
    user_guess_it = format_category_name(user_guess)
    correct_answer_it = format_category_name(correct_answer)
    
    # CHIAMATA AGGIORNATA: Estrae la bio corretta e formattata dal CSV
    bio_explanation_full = get_bio_explanation(current_char)

    # 4. Costruzione del messaggio di ESITO
    if esito_corretto:
        # CASO 1: RISPOSTA CORRETTA
        # Il messaggio è solo "Corretto! [Bio]"
        result_message = (
            f"✅ **Corretto!** Hai indovinato!\n\n"
            f"{bio_explanation_full}"
        )
    else:
        # CASO 2: RISPOSTA SBAGLIATA
        # Il messaggio mostra la risposta corretta e poi la spiegazione SENZA ripetere la categoria
        result_message = (
            f"❌ **Sbagliato!** Hai risposto: _{user_guess_it}_\n\n"
            f"La risposta corretta è: **{correct_answer_it}**.\n\n" # FIX: Categoria corretta
            f"Spiegazione:\n"
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
