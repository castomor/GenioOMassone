import os
import logging
from datetime import date

# Import per FastAPI
from fastapi import FastAPI, Request, HTTPException
import uvicorn

# Import per Telegram Bot
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode

# Import per SQLAlchemy (Database)
from sqlalchemy import create_engine, Column, Integer, String, Date
from sqlalchemy.orm import sessionmaker, declarative_base

# Per la lettura delle variabili d'ambiente (utile per test locali)
from dotenv import load_dotenv

# --- 0. CONFIGURAZIONE GENERALE ---
# Carica .env se presente (utile in locale, Render usa le sue variabili)
# load_dotenv() 

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Il nome host che Render assegna al tuo servizio (es. mybot.onrender.com)
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME") 

if not TELEGRAM_BOT_TOKEN or not RENDER_EXTERNAL_HOSTNAME:
    # Solleva un errore se le variabili cruciali non sono state impostate
    raise ValueError("Variabili d'ambiente TELEGRAM_BOT_TOKEN o RENDER_EXTERNAL_HOSTNAME mancanti.")

WEBHOOK_URL_BASE = f"https://{RENDER_EXTERNAL_HOSTNAME}"
WEBHOOK_PATH = "/webhook"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURAZIONE DATABASE (SQLAlchemy) ---

# Usa un file SQLite per semplicità. In produzione su Render, usa PostgreSQL!
# Esempio per PostgreSQL (Render): DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_URL = "sqlite:///./game_data.db" 

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modello dei dati
class Character(Base):
    """Definisce la tabella dei personaggi."""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    category = Column(String)  # 'GENIUS', 'MASON', 'BOTH', 'COMMON'
    last_proposed_date = Column(Date, nullable=True)

class GameStatus(Base):
    """Traccia lo stato attuale del gioco (personaggio del giorno)."""
    __tablename__ = "game_status"
    
    id = Column(Integer, primary_key=True)
    current_char_id = Column(Integer, unique=True, nullable=False)
    game_date = Column(Date, unique=True, nullable=False)

# Esempio di dati iniziali
INITIAL_CHARACTERS = [
    ("Leonardo da Vinci", "GENIUS"),
    ("Giuseppe Garibaldi", "MASON"),
    ("Wolfgang Amadeus Mozart", "BOTH"),
    ("Una Persona Qualunque", "COMMON"),
    ("Galileo Galilei", "GENIUS"),
    ("Lord Byron", "MASON"),
]

# --- 2. FUNZIONI DI GIOCO E DB ---

def init_db(session):
    """Crea le tabelle e inserisce i dati iniziali se non esistono."""
    Base.metadata.create_all(bind=engine)
    
    # Aggiungi personaggi se la tabella è vuota
    if session.query(Character).count() == 0:
        logger.info("Inizializzazione dei personaggi nel database.")
        for name, category in INITIAL_CHARACTERS:
            session.add(Character(name=name, category=category))
        session.commit()
    
    session.close()

def select_new_character(session):
    """Seleziona un nuovo personaggio da proporre, dando priorità ai meno recenti."""
    today = date.today()
    
    # 1. Controlla se il gioco è già iniziato oggi
    current_status = session.query(GameStatus).filter(GameStatus.game_date == today).first()
    
    if current_status:
        # Già proposto oggi, recupera il personaggio
        char = session.query(Character).filter(Character.id == current_status.current_char_id).first()
        return char

    # 2. Seleziona il personaggio (quello proposto meno di recente)
    # Ordina per data, con NULL (mai proposti) per primi
    char_to_propose = session.query(Character).order_by(Character.last_proposed_date.asc()).first()
    
    if char_to_propose:
        # 3. Aggiorna il DB
        char_to_propose.last_proposed_date = today
        
        # Aggiorna lo stato del gioco
        # Prima rimuovi il vecchio stato (per mantenere la tabella GameStatus pulita)
        session.query(GameStatus).delete() 
        session.add(GameStatus(current_char_id=char_to_propose.id, game_date=today))
        
        session.commit()
        return char_to_propose
        
    return None # Nessun personaggio disponibile

# --- 3. GESTORI TELEGRAM (HANDLERS) ---

# Helper per creare i pulsanti di risposta
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
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context):
    """Gestisce il comando /start e avvia il quiz giornaliero."""
    session = SessionLocal()
    try:
        current_char = select_new_character(session)
        
        if current_char:
            message = (
                f"🎉 **Benvenuto nel quiz del giorno!**\n\n"
                f"Il personaggio di oggi è: **{current_char.name}**\n\n"
                f"Indovina la sua vera identità:"
            )
            
            await update.message.reply_text(
                message, 
                reply_markup=get_quiz_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("Errore: Nessun personaggio disponibile nel database.")

    finally:
        session.close()

async def button_callback_handler(update: Update, context):
    """Gestisce la pressione dei pulsanti Inline (la risposta dell'utente)."""
    query = update.callback_query
    await query.answer()  # Risponde alla query per rimuovere lo stato di caricamento

    user_guess = query.data
    chat_id = query.message.chat_id
    
    session = SessionLocal()
    try:
        # Recupera lo stato del gioco odierno
        today = date.today()
        current_status = session.query(GameStatus).filter(GameStatus.game_date == today).first()
        
        if not current_status:
            await query.edit_message_text("Il quiz del giorno non è ancora iniziato!")
            return

        current_char = session.query(Character).filter(Character.id == current_status.current_char_id).first()
        
        if not current_char:
            await query.edit_message_text("Errore nel recupero del personaggio.")
            return

        # Verifica la risposta
        correct_answer = current_char.category
        
        if user_guess == correct_answer:
            result_message = (
                f"✅ **Corretto!**\n"
                f"Hai indovinato! **{current_char.name}** era effettivamente un **{correct_answer.capitalize()}**."
            )
        else:
            result_message = (
                f"❌ **Sbagliato!**\n"
                f"Hai risposto: _{user_guess.capitalize()}_\n"
                f"La risposta corretta era: **{correct_answer.capitalize()}**.\n\n"
                f"Il personaggio era: **{current_char.name}**."
            )
            
        # Modifica il messaggio con la risposta (e rimuove i pulsanti)
        await query.edit_message_text(
            result_message,
            parse_mode=ParseMode.MARKDOWN
        )

    finally:
        session.close()

# --- 4. CONFIGURAZIONE FASTAPI ---

app = FastAPI()
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = application.bot

# Aggiunge i gestori (handlers)
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CallbackQueryHandler(button_callback_handler))

# --- 5. ENDPOINT E LOGICA DI AVVIO ---

@app.on_event("startup")
async def startup_event():
    """Eseguito all'avvio del server: imposta il Webhook e il DB."""
    logger.info("Avvio del server...")
    
    # 1. Inizializza il database
    try:
        db = SessionLocal()
        init_db(db)
        logger.info("Database inizializzato o verificato.")
    except Exception as e:
        logger.error(f"Errore nell'inizializzazione del DB: {e}")

    # 2. Imposta il Webhook su Telegram
    full_webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"
    logger.info(f"Tentativo di impostare il Webhook su: {full_webhook_url}")
    
    await bot.delete_webhook() # Rimuove vecchi webhook
    
    success = await bot.set_webhook(url=full_webhook_url)
    
    if success:
        logger.info("Webhook impostato con successo!")
    else:
        logger.error("Impostazione del Webhook fallita.")


@app.get("/")
def read_root():
    """Endpoint di salute: controlla se il server è vivo."""
    return {"status": "ok", "message": "Bot Server is Running"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Endpoint principale che riceve gli aggiornamenti da Telegram."""
    try:
        # Ottieni i dati JSON e li passa all'Application PTB
        update_json = await request.json()
        update = Update.de_json(update_json, bot)
        await application.process_update(update)
        
        return {"message": "Update processed"}
        
    except Exception as e:
        logger.error(f"Errore nell'elaborazione dell'update: {e}")
        # Deve sempre restituire 200 a Telegram
        return {"message": "Internal Server Error, but acknowledged"}

# La parte finale per l'esecuzione diretta con uvicorn non è più necessaria
# perché Render/Gunicorn usa il comando di avvio esterno.
