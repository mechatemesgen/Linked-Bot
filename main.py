import logging
import sqlite3
from functools import wraps
from telegram import (
    InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, ParseMode
)
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, Filters, CallbackContext
)
from telegram.error import BadRequest
from datetime import datetime
import os
from dotenv import load_dotenv
from flask import Flask, request
from telegram import Bot
from telegram.ext import Dispatcher

load_dotenv()

# ------------------------- CONFIGURATION -------------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = 'applications.db'

# Replace with your admin's numeric chat id (retrieved via /getid command)
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

# ------------------------- CONVERSATION STATES -------------------------

(
    HOME, 
    RENT_LINKEDIN_EXIST, 
    RENT_CONNECTIONS, 
    RENT_EARNING_CONFIRM,
    RENT_PHONE, 
    RENT_LINKEDIN, 
    RENT_PASSWORD, 
    APPLICATION_REVIEW,
    HELP_SCREEN, 
    CONTACT_ADMIN,
    TESTIMONIALS, 
    RECEIVE_TESTIMONIAL, 
    REFERRAL, 
    INVITE_FRIEND,
    AWAITING_USER_ID,
    AWAITING_MESSAGE,
    ADMIN_MESSAGE_INPUT,
    AWAITING_ADMIN_MESSAGE
) = range(18)

EARNING_MAPPING = {
    '>100': 7,
    '>200': 10,
    '>300': 12.5,
    '>400': 15,
    '>500': 17.5,
    '>600': 20,
    '700-1000': 25,
}

# Add to conversation states
USER_LIST_PAGE = range(18, 19)[0]  # Add this at the end of state definitions

USERS_PER_PAGE = 5  # Number of users to display per page

# ------------------------- DATABASE FUNCTIONS -------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    full_name TEXT,
                    phone TEXT,
                    linkedin_account TEXT,
                    password TEXT,
                    connections TEXT,
                    weekly_earning REAL,
                    status TEXT DEFAULT 'pending'
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    referral_code TEXT,
                    invited_count INTEGER DEFAULT 0
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
                    user_id INTEGER PRIMARY KEY,
                    admin_id INTEGER,
                    last_contact DATETIME DEFAULT CURRENT_TIMESTAMP
                 )''')  
    c.execute('''CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    action TEXT,
                    details TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

def log_action(telegram_id: int, action: str, details: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO actions (telegram_id, action, details) VALUES (?, ?, ?)''',
              (telegram_id, action, details))
    conn.commit()
    conn.close()

def save_application(data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO applications (
                    telegram_id, full_name, phone, linkedin_account,
                    password, connections, weekly_earning, status
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (
                  data.get('telegram_id'),
                  data.get('full_name'),
                  data.get('phone'),
                  data.get('linkedin_account'),
                  data.get('password'),
                  data.get('connections'),
                  data.get('weekly_earning'),
                  'pending'
              ))
    conn.commit()
    conn.close()
    


# ***********************************************************
def update_application_status(telegram_id: int, new_status: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE applications
        SET status = ?
        WHERE telegram_id = ?
        AND id = (
            SELECT MAX(id)
            FROM applications
            WHERE telegram_id = ?
        )
    ''', (new_status, telegram_id, telegram_id))
    conn.commit()
    conn.close()

def get_application_status(telegram_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT status
        FROM applications
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 1
    ''', (telegram_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None



# Add new database function
def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT telegram_id, full_name 
        FROM applications
        ORDER BY id DESC  -- Newest first (correct SQL comment syntax)
    ''')
    users = c.fetchall()
    conn.close()
    return users




# ------------------------- HELPER FUNCTIONS -------------------------

from telegram import ParseMode

def safe_edit_caption(query, text, reply_markup=None):
    """
    Tries to edit either text or caption, always using Markdown parsing,
    so your **bold** and *italic* will render correctly.
    """
    try:
        if query.message.text:  # If it's a text message
            query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        elif query.message.caption:  # If it's a media message with a caption
            query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # fallback or log warning
            print("⚠️ Message has neither text nor caption.")
    except Exception as e:
        print(f"❌ Failed to edit message: {e}")



def go_home(update: Update, context: CallbackContext) -> int:
    return main_menu(update, context)

# Temporary command to get chat id for admin
def get_id(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    update.message.reply_text(f"Your chat id is: {chat_id}")

# ------------------------- HANDLER FUNCTIONS -------------------------

def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    context.user_data['full_name'] = user.first_name
    status = get_application_status(user.id)
    status_text = f"\n\nYour current application status: \n {status.capitalize()}" if status else "\n\nYou have no active applications."
    caption = (f"Hello {user.first_name}, welcome to LINKEDIN ACCOUNT RENTERS.\n\n"
               "Your LinkedIn account == Your Personal ATM! 🏧\n\n"
               "@linkedIn_BussinessET lets you rent out your LinkedIn account for legitimate business and networking, "
               "and we pay you generously for access. It's simple, safe, and profitable!\n\n"
               "------------------------------------" + status_text)
    keyboard = [
        [InlineKeyboardButton("Rent", callback_data="rent"),
         InlineKeyboardButton("Help", callback_data="help")],
        [InlineKeyboardButton("Testimonials", callback_data="testimonials"),
         InlineKeyboardButton("Referral", callback_data="referral")]
    ]
    with open("./assets/Linked Banner.jpg", "rb") as banner:
        photo_message = context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=banner,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    context.user_data['menu_message_id'] = photo_message.message_id
    return HOME


def main_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    query.delete_message()
    user_id = update.effective_user.id
    status = get_application_status(user_id)
    status_text = f"\n\nYour current application status: {status.capitalize()}" if status else "\n\nYou have no active applications."
    caption = (f"Welcome back to LINKEDIN ACCOUNT RENTERS!\n\n"
               "Your LinkedIn account == Your Personal ATM! 🏧\n\n"
               "@linkedIn_BussinessET lets you rent out your LinkedIn account for legitimate business and networking, "
               "and we pay you generously for access. It's simple, safe, and profitable!\n\n"
               "------------------------------------" + status_text)
    keyboard = [
        [InlineKeyboardButton("Rent", callback_data="rent"),
         InlineKeyboardButton("Help", callback_data="help")],
        [InlineKeyboardButton("Testimonials", callback_data="testimonials"),
         InlineKeyboardButton("Referral", callback_data="referral")]
    ]
    with open("./assets/Linked Banner.jpg", "rb") as banner:
        photo_message = context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=banner,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    context.user_data['menu_message_id'] = photo_message.message_id
    return HOME
# *************************************

def admin_approve_reject(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data
    action, user_id = data.split('_', 1)
    user_id = int(user_id)

    if action == 'approve':
        new_status = 'accepted ✅'
        status_text = "✅ Approved"
    elif action == 'reject':
        new_status = 'rejected ❌'
        status_text = "❌ Rejected"
    else:
        return

    update_application_status(user_id, new_status)

    try:
        context.bot.send_message(
            chat_id=user_id,
            text=f"Your application has been {new_status}!"
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

    try:
        original_text = query.message.text
        
        # Preserve both status and message button
        new_keyboard = [
            [
                InlineKeyboardButton(status_text, callback_data="status"),
                InlineKeyboardButton("💬 Send Message", callback_data=f"message_{user_id}")
            ]
        ]
        
        query.edit_message_text(
            text=original_text,
            reply_markup=InlineKeyboardMarkup(new_keyboard)
        )
    except BadRequest as e:
        logger.error(f"Failed to edit message: {e}")

    return

def get_users_page(users, page):
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    return users[start:end]


# Add admin message handlers
def list_users(update: Update, context: CallbackContext, page=0):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'list_users', f'Page {page+1}')
    return USER_LIST_PAGE

def handle_user_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    page = int(query.data.split('_')[-1])
    query.answer()
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'paginate_users', f'Page {page+1}')
    return USER_LIST_PAGE

def admin_approve_reject(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith('approve_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'approved')
        log_action(update.effective_user.id, 'approve_user', f'User {telegram_id}')
        query.answer("User approved.")
        query.edit_message_text(f"User {telegram_id} approved.")
    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'rejected')
        log_action(update.effective_user.id, 'reject_user', f'User {telegram_id}')
        query.answer("User rejected.")
        query.edit_message_text(f"User {telegram_id} rejected.")
    return USER_LIST_PAGE

def get_users_page(users, page):
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    return users[start:end]


# Add admin message handlers
def list_users(update: Update, context: CallbackContext, page=0):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'list_users', f'Page {page+1}')
    return USER_LIST_PAGE

def handle_user_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    page = int(query.data.split('_')[-1])
    query.answer()
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'paginate_users', f'Page {page+1}')
    return USER_LIST_PAGE

def admin_approve_reject(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith('approve_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'approved')
        log_action(update.effective_user.id, 'approve_user', f'User {telegram_id}')
        query.answer("User approved.")
        query.edit_message_text(f"User {telegram_id} approved.")
    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'rejected')
        log_action(update.effective_user.id, 'reject_user', f'User {telegram_id}')
        query.answer("User rejected.")
        query.edit_message_text(f"User {telegram_id} rejected.")
    return USER_LIST_PAGE

def get_users_page(users, page):
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    return users[start:end]


# Add admin message handlers
def list_users(update: Update, context: CallbackContext, page=0):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'list_users', f'Page {page+1}')
    return USER_LIST_PAGE

def handle_user_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    page = int(query.data.split('_')[-1])
    query.answer()
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'paginate_users', f'Page {page+1}')
    return USER_LIST_PAGE

def admin_approve_reject(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith('approve_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'approved')
        log_action(update.effective_user.id, 'approve_user', f'User {telegram_id}')
        query.answer("User approved.")
        query.edit_message_text(f"User {telegram_id} approved.")
    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'rejected')
        log_action(update.effective_user.id, 'reject_user', f'User {telegram_id}')
        query.answer("User rejected.")
        query.edit_message_text(f"User {telegram_id} rejected.")
    return USER_LIST_PAGE

def get_users_page(users, page):
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    return users[start:end]


# Add admin message handlers
def list_users(update: Update, context: CallbackContext, page=0):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'list_users', f'Page {page+1}')
    return USER_LIST_PAGE

def handle_user_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    page = int(query.data.split('_')[-1])
    query.answer()
    users = get_all_users()
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    text = f"Users (page {page+1}/{total_pages}):\n"
    for idx, (telegram_id, full_name) in enumerate(page_users, start=1):
        text += f"{idx}. {full_name} (ID: {telegram_id})\n"
    keyboard = []
    if page > 0:
        keyboard.append([InlineKeyboardButton("Previous", callback_data=f"users_page_{page-1}")])
    if end < len(users):
        keyboard.append([InlineKeyboardButton("Next", callback_data=f"users_page_{page+1}")])
    for telegram_id, full_name in page_users:
        keyboard.append([
            InlineKeyboardButton(f"Approve {full_name}", callback_data=f"approve_{telegram_id}"),
            InlineKeyboardButton(f"Reject {full_name}", callback_data=f"reject_{telegram_id}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)
    log_action(update.effective_user.id, 'paginate_users', f'Page {page+1}')
    return USER_LIST_PAGE

def admin_approve_reject(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith('approve_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'approved')
        log_action(update.effective_user.id, 'approve_user', f'User {telegram_id}')
        query.answer("User approved.")
        query.edit_message_text(f"User {telegram_id} approved.")
    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        update_application_status(telegram_id, 'rejected')
        log_action(update.effective_user.id, 'reject_user', f'User {telegram_id}')
        query.answer("User rejected.")
        query.edit_message_text(f"User {telegram_id} rejected.")
    return USER_LIST_PAGE

def send_user_message(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return
    try:
        args = context.args
        if len(args) < 2:
            update.message.reply_text("Usage: /send <user_id> <message>")
            return
        user_id = int(args[0])
        message = ' '.join(args[1:])
        context.bot.send_message(chat_id=user_id, text=message)
        log_action(update.effective_user.id, 'send_message', f'To {user_id}: {message}')
        update.message.reply_text(f"Message sent to {user_id}.")
    except Exception as e:
        update.message.reply_text(f"Failed to send message: {e}")