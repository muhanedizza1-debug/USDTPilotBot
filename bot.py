import telebot
import sqlite3
import os
import threading
import time
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# ========== CONFIG ==========
BOT_TOKEN = "8626470350:AAFxJ3S5FjEjgBK-ySNAaKAZHvuOGRhLQ3A"
ADMIN_ID = 7076265514
ADMIN_PIN = "1234"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        referred_by INTEGER DEFAULT 0,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        status TEXT,
        network TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        type TEXT,
        read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    default_settings = {
        'bonus_amount': '1.0',
        'min_deposit': '10',
        'max_deposit': '10000',
        'min_withdraw': '10',
        'max_withdraw': '10000',
        'referral_bonus': '0.5',
        'maintenance_mode': 'false',
        'welcome_message': 'Welcome to USDTPilotBot! 🚀',
        'currency': 'USDT'
    }
    
    for key, value in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    conn.close()

init_db()

# ========== TOGGLE KEYBOARD ==========
keyboard_visible = {}

def toggle_keyboard(user_id):
    if user_id in keyboard_visible:
        keyboard_visible[user_id] = not keyboard_visible[user_id]
    else:
        keyboard_visible[user_id] = True
    return keyboard_visible[user_id]

def is_keyboard_visible(user_id):
    return keyboard_visible.get(user_id, True)

def get_keyboard_menu(user_id):
    if is_keyboard_visible(user_id):
        return profile_menu()
    else:
        return back_button()

# ========== DATABASE FUNCTIONS ==========
def get_setting(key):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def update_setting(key, value):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    conn.commit()
    conn.close()

def add_user(user_id, username, referred_by=0):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (id, username, referred_by) VALUES (?, ?, ?)", 
                  (user_id, username, referred_by))
        if referred_by > 0:
            bonus = float(get_setting('referral_bonus') or 0.5)
            update_balance(referred_by, bonus)
            add_notification(referred_by, f"🎉 New referral! You earned {bonus} USDT", "SUCCESS")
        conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    data = c.fetchone()
    conn.close()
    return data

def get_all_users():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT id, username, balance FROM users ORDER BY balance DESC")
    data = c.fetchall()
    conn.close()
    return data

def get_top_users(limit=10):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    data = c.fetchall()
    conn.close()
    return data

def search_user(query):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT id, username, balance FROM users WHERE id LIKE ? OR username LIKE ?", 
              (f"%{query}%", f"%{query}%"))
    data = c.fetchall()
    conn.close()
    return data

def delete_user(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    c.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_total_balance():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT SUM(balance) FROM users")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_total_users():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    conn.close()
    return total

def get_today_users():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(registered_at) = DATE('now')")
    total = c.fetchone()[0]
    conn.close()
    return total

def get_referral_count(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    return total

def add_request(user_id, req_type, amount, network):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, network) VALUES (?, ?, ?, ?, ?)",
              (user_id, req_type, amount, "PENDING", network))
    conn.commit()
    conn.close()
    add_notification(user_id, f"📝 {req_type} request of {amount} USDT submitted. Waiting for admin approval.", "INFO")

def get_pending():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE status='PENDING' ORDER BY created_at DESC")
    return c.fetchall()

def get_pending_with_users():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("""
    SELECT t.id, t.user_id, u.username, t.type, t.amount, t.network, t.created_at
    FROM transactions t
    JOIN users u ON t.user_id = u.id
    WHERE t.status='PENDING'
    ORDER BY t.created_at DESC
    """)
    data = c.fetchall()
    conn.close()
    return data

def update_transaction(tx_id, status):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE transactions SET status=? WHERE id=?", (status, tx_id))
    conn.commit()
    conn.close()
    if status == "APPROVED":
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount, type FROM transactions WHERE id=?", (tx_id,))
        tx = c.fetchone()
        if tx:
            if tx[2] == "DEPOSIT":
                update_balance(tx[0], tx[1])
                add_notification(tx[0], f"✅ Deposit of {tx[1]} USDT approved! Balance updated.", "SUCCESS")
            elif tx[2] == "WITHDRAW":
                add_notification(tx[0], f"✅ Withdraw of {tx[1]} USDT approved!", "SUCCESS")
        conn.close()
    elif status == "REJECTED":
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount, type FROM transactions WHERE id=?", (tx_id,))
        tx = c.fetchone()
        if tx:
            add_notification(tx[0], f"❌ {tx[2]} of {tx[1]} USDT rejected.", "WARNING")
        conn.close()

def get_transaction_history(user_id, limit=20):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("""
    SELECT type, amount, status, network, created_at
    FROM transactions
    WHERE user_id=?
    ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit))
    data = c.fetchall()
    conn.close()
    return data

def get_all_transactions(limit=50):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("""
    SELECT t.*, u.username 
    FROM transactions t
    JOIN users u ON t.user_id = u.id
    ORDER BY t.created_at DESC LIMIT ?
    """, (limit,))
    data = c.fetchall()
    conn.close()
    return data

def get_deposit_total():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM transactions WHERE type='DEPOSIT' AND status='APPROVED'")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_withdraw_total():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM transactions WHERE type='WITHDRAW' AND status='APPROVED'")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_transactions_by_status(status):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM transactions WHERE status=?", (status,))
    total = c.fetchone()[0]
    conn.close()
    return total

def add_notification(user_id, message, type="INFO"):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)", 
              (user_id, message, type))
    conn.commit()
    conn.close()

def get_notifications(user_id, unread_only=True):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    query = "SELECT id, message, type, created_at FROM notifications WHERE user_id=?"
    if unread_only:
        query += " AND read=0"
    query += " ORDER BY created_at DESC LIMIT 20"
    c.execute(query, (user_id,))
    data = c.fetchall()
    conn.close()
    return data

def mark_notification_read(notif_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE notifications SET read=1 WHERE id=?", (notif_id,))
    conn.commit()
    conn.close()

def mark_all_notifications_read(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_unread_count(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

admin_sessions = {}

def is_admin_logged_in(user_id):
    return user_id == ADMIN_ID and admin_sessions.get(user_id, False)

def admin_login(user_id):
    admin_sessions[user_id] = True

def admin_logout(user_id):
    if user_id in admin_sessions:
        del admin_sessions[user_id]

def get_daily_report(date=None):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    if not date:
        date = "DATE('now')"
    
    c.execute(f"SELECT COUNT(*) FROM users WHERE DATE(registered_at) = {date}")
    new_users = c.fetchone()[0]
    
    c.execute(f"SELECT SUM(amount) FROM transactions WHERE type='DEPOSIT' AND status='APPROVED' AND DATE(created_at) = {date}")
    total_deposits = c.fetchone()[0] or 0
    
    c.execute(f"SELECT SUM(amount) FROM transactions WHERE type='WITHDRAW' AND status='APPROVED' AND DATE(created_at) = {date}")
    total_withdraws = c.fetchone()[0] or 0
    
    c.execute(f"SELECT COUNT(*) FROM transactions WHERE status='PENDING' AND DATE(created_at) = {date}")
    pending = c.fetchone()[0]
    
    c.execute(f"SELECT COUNT(*) FROM transactions WHERE status='APPROVED' AND DATE(created_at) = {date}")
    approved = c.fetchone()[0]
    
    c.execute(f"SELECT COUNT(*) FROM transactions WHERE status='REJECTED' AND DATE(created_at) = {date}")
    rejected = c.fetchone()[0]
    
    conn.close()
    
    return {
        'new_users': new_users,
        'total_deposits': total_deposits,
        'total_withdraws': total_withdraws,
        'pending': pending,
        'approved': approved,
        'rejected': rejected
    }

def get_weekly_report():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(registered_at) >= DATE('now', '-7 days')")
    new_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM transactions WHERE type='DEPOSIT' AND status='APPROVED' AND DATE(created_at) >= DATE('now', '-7 days')")
    total_deposits = c.fetchone()[0] or 0
    
    c.execute("SELECT SUM(amount) FROM transactions WHERE type='WITHDRAW' AND status='APPROVED' AND DATE(created_at) >= DATE('now', '-7 days')")
    total_withdraws = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM transactions WHERE status='PENDING' AND DATE(created_at) >= DATE('now', '-7 days')")
    pending = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM transactions WHERE status='APPROVED' AND DATE(created_at) >= DATE('now', '-7 days')")
    approved = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM transactions WHERE status='REJECTED' AND DATE(created_at) >= DATE('now', '-7 days')")
    rejected = c.fetchone()[0]
    
    conn.close()
    
    return {
        'new_users': new_users,
        'total_deposits': total_deposits,
        'total_withdraws': total_withdraws,
        'pending': pending,
        'approved': approved,
        'rejected': rejected
    }

def get_admin_stats():
    return {
        'total_users': get_total_users(),
        'today_users': get_today_users(),
        'total_balance': get_total_balance(),
        'total_deposits': int(get_deposit_total()),
        'total_withdraws': int(get_withdraw_total()),
        'total_pending': len(get_pending()),
        'total_approved': get_transactions_by_status('APPROVED'),
        'total_rejected': get_transactions_by_status('REJECTED')
    }

# ========== KEYBOARDS ==========
def main_menu():
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👤 My Profile", callback_data="profile"),
        InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
        InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
        InlineKeyboardButton("📜 History", callback_data="history"),
        InlineKeyboardButton("👥 Referral", callback_data="referral"),
        InlineKeyboardButton("⌨️ Toggle Keyboard", callback_data="toggle_keyboard")
    )
    return markup

def profile_menu():
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👤 My Profile", callback_data="profile"),
        InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
        InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
        InlineKeyboardButton("📜 History", callback_data="history"),
        InlineKeyboardButton("👥 Referral", callback_data="referral"),
        InlineKeyboardButton("⌨️ Toggle Keyboard", callback_data="toggle_keyboard")
    )
    return markup

def deposit_networks():
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💵 TRC20 (USDT)", callback_data="deposit_trc20"),
        InlineKeyboardButton("💵 BEP20 (USDT)", callback_data="deposit_bep20"),
        InlineKeyboardButton("💵 ERC20 (USDT)", callback_data="deposit_erc20"),
        InlineKeyboardButton("💵 TON (USDT)", callback_data="deposit_ton"),
        InlineKeyboardButton("🔙 Back", callback_data="back")
    )
    return markup

def admin_menu():
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Dashboard", callback_data="admin_dashboard"),
        InlineKeyboardButton("📋 Pending", callback_data="admin_pending"),
        InlineKeyboardButton("📈 Reports", callback_data="admin_reports"),
        InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
        InlineKeyboardButton("🔒 Logout", callback_data="admin_logout")
    )
    return markup

def back_button():
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back")
    )
    return markup

# ========== BOT COMMANDS ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    
    if get_setting('maintenance_mode') == 'true' and user_id != ADMIN_ID:
        bot.reply_to(message, "🔧 Bot is under maintenance. Please try again later.")
        return
    
    referred_by = 0
    if message.text and ' ' in message.text:
        try:
            referred_by = int(message.text.split()[1])
            if referred_by == user_id:
                referred_by = 0
        except:
            pass
    
    add_user(user_id, username, referred_by)
    
    bot.reply_to(
        message,
        f"""
👤 **PROFILE**

🆔 ID: `{user_id}`
👤 Name: @{username}
💰 Balance: $0.00
📊 Active Deposit: $0.00
📈 Total Profit: $0.00
📌 Status: No Deposit
🔒 Withdrawal Lock: Unlocked

{datetime.now().strftime('%I:%M %p')}

━━━━━━━━━━━━━━━━━━━

⌨️ **Keyboard: Visible**

📱 **Menu**
""",
        reply_markup=profile_menu(),
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['admin'])
def admin_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    if is_admin_logged_in(user_id):
        show_admin_dashboard(message)
    else:
        bot.reply_to(message, "🔐 Please login first:\n/adminpin 1234")

@bot.message_handler(commands=['adminpin'])
def admin_pin(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "🔐 Use: /adminpin 1234")
        return
    
    if args[1] == ADMIN_PIN:
        admin_login(user_id)
        bot.reply_to(message, "✅ Admin access granted!")
        show_admin_dashboard(message)
    else:
        bot.reply_to(message, "❌ Wrong PIN!")

@bot.message_handler(commands=['adminlogout'])
def admin_logout_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    admin_logout(user_id)
    bot.reply_to(message, "🔒 Logged out from admin")

@bot.message_handler(commands=['deposit_amount'])
def deposit_amount(message):
    user_id = message.from_user.id
    if get_setting('maintenance_mode') == 'true':
        bot.reply_to(message, "🔧 Bot is under maintenance.")
        return
    
    try:
        amount = float(message.text.split()[1])
        if amount <= 0:
            raise ValueError
        min_deposit = float(get_setting('min_deposit') or 10)
        max_deposit = float(get_setting('max_deposit') or 10000)
        if amount < min_deposit:
            bot.reply_to(message, f"❌ Minimum deposit is {min_deposit} USDT")
            return
        if amount > max_deposit:
            bot.reply_to(message, f"❌ Maximum deposit is {max_deposit} USDT")
            return
    except:
        bot.reply_to(message, "❌ Use: /deposit_amount 100")
        return
    
    add_request(user_id, "DEPOSIT", amount, "TRC20")
    bot.reply_to(
        message,
        f"""
✅ **Deposit request submitted!**

📌 Amount: `{amount:.2f}` USDT
⏳ Status: PENDING

Admin will approve.
""",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['withdraw'])
def withdraw_command(message):
    user_id = message.from_user.id
    if get_setting('maintenance_mode') == 'true':
        bot.reply_to(message, "🔧 Bot is under maintenance.")
        return
    
    try:
        amount = float(message.text.split()[1])
        if amount <= 0:
            raise ValueError
        min_withdraw = float(get_setting('min_withdraw') or 10)
        max_withdraw = float(get_setting('max_withdraw') or 10000)
        if amount < min_withdraw:
            bot.reply_to(message, f"❌ Minimum withdraw is {min_withdraw} USDT")
            return
        if amount > max_withdraw:
            bot.reply_to(message, f"❌ Maximum withdraw is {max_withdraw} USDT")
            return
    except:
        bot.reply_to(message, "❌ Use: /withdraw 50")
        return
    
    user = get_user(user_id)
    if not user or (user[2] or 0) < amount:
        bot.reply_to(
            message,
            f"❌ Insufficient balance. Balance: `{user[2]:.2f}` USDT",
            parse_mode='Markdown'
        )
        return
    
    add_request(user_id, "WITHDRAW", amount, "USDT")
    bot.reply_to(
        message,
        f"""
✅ **Withdraw request submitted!**

📌 Amount: `{amount:.2f}` USDT
⏳ Status: PENDING

Admin will approve.
""",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    msg = message.text.replace('/broadcast', '').strip()
    if not msg:
        bot.reply_to(message, "📢 Use: /broadcast message")
        return
    
    users = get_all_users()
    sent = 0
    for u in users:
        try:
            bot.send_message(u[0], f"📢 {msg}")
            sent += 1
            time.sleep(0.05)
        except:
            pass
    
    bot.reply_to(message, f"✅ Broadcast sent to {sent} users")

@bot.message_handler(commands=['top'])
def top_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    top = get_top_users(10)
    if not top:
        bot.reply_to(message, "📊 No users yet")
        return
    
    text = "🏆 **Top 10 Users**\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} @{u[1] or u[0]} - ${u[2]:.2f}\n"
    
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['search'])
def search_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    query = message.text.replace('/search', '').strip()
    if not query:
        bot.reply_to(message, "🔍 Use: /search username or ID")
        return
    
    results = search_user(query)
    if not results:
        bot.reply_to(message, "❌ No users found")
        return
    
    text = f"🔍 **Search Results:** {len(results)} found\n\n"
    for u in results[:10]:
        text += f"🆔 `{u[0]}` | @{u[1] or 'No username'} | ${u[2]:.2f}\n"
    
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['deleteuser'])
def delete_user_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    try:
        target_id = int(message.text.split()[1])
    except:
        bot.reply_to(message, "❌ Use: /deleteuser 123456789")
        return
    
    if target_id == ADMIN_ID:
        bot.reply_to(message, "❌ Cannot delete admin")
        return
    
    delete_user(target_id)
    bot.reply_to(message, f"✅ User {target_id} deleted")

@bot.message_handler(commands=['daily'])
def daily_report_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    stats = get_daily_report()
    text = f"""
📊 **Daily Report**
📅 {datetime.now().strftime('%Y-%m-%d')}

👥 New Users: {stats['new_users']}
💰 Total Deposits: ${stats['total_deposits']:.2f}
💸 Total Withdraws: ${stats['total_withdraws']:.2f}
⏳ Pending: {stats['pending']}
✅ Approved: {stats['approved']}
❌ Rejected: {stats['rejected']}
"""
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['weekly'])
def weekly_report_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    stats = get_weekly_report()
    end = datetime.now()
    start = end - timedelta(days=7)
    text = f"""
📊 **Weekly Report**
📅 {start.strftime('%Y-%m-%d')} - {end.strftime('%Y-%m-%d')}

👥 New Users: {stats['new_users']}
💰 Total Deposits: ${stats['total_deposits']:.2f}
💸 Total Withdraws: ${stats['total_withdraws']:.2f}
⏳ Pending: {stats['pending']}
✅ Approved: {stats['approved']}
❌ Rejected: {stats['rejected']}
"""
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['settings'])
def settings_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    settings = {}
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    for row in c.fetchall():
        settings[row[0]] = row[1]
    conn.close()
    
    text = "⚙️ **System Settings**\n\n"
    for key, value in settings.items():
        text += f"• {key}: `{value}`\n"
    text += "\nTo update: `/set key value`"
    
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['set'])
def set_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ Use: /set key value")
        return
    
    key = args[1]
    value = " ".join(args[2:])
    update_setting(key, value)
    bot.reply_to(message, f"✅ {key} updated to: {value}")

@bot.message_handler(commands=['backup'])
def backup_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    try:
        import shutil
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy('bot.db', backup_name)
        bot.reply_to(message, f"✅ Database backed up: `{backup_name}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Backup failed: {e}")

@bot.message_handler(commands=['maintenance'])
def maintenance_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Use: /maintenance on/off")
        return
    
    status = args[1].lower()
    if status in ['on', 'true', '1']:
        update_setting('maintenance_mode', 'true')
        bot.reply_to(message, "🔧 Maintenance mode: **ON**\n\nOnly admins can use bot.")
    elif status in ['off', 'false', '0']:
        update_setting('maintenance_mode', 'false')
        bot.reply_to(message, "✅ Maintenance mode: **OFF**\n\nBot is fully operational.")
    else:
        bot.reply_to(message, "❌ Use: /maintenance on/off")

@bot.message_handler(commands=['info'])
def info_command(message):
    user_id = message.from_user.id
    stats = get_admin_stats()
    text = f"""
🤖 **USDTPilotBot**
📌 Version: `2.0.0`

📊 **Statistics:**
👥 Users: `{stats['total_users']}`
💰 Balance: `${stats['total_balance']:.2f}`

📈 **Transactions:**
📥 Deposits: `{stats['total_deposits']}`
📤 Withdraws: `{stats['total_withdraws']}`

🌍 **Languages:** English
🛡️ **Security:** PIN + Anti-Spam

💡 **Commands:** /help
"""
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    user_id = message.from_user.id
    is_admin = (user_id == ADMIN_ID and is_admin_logged_in(user_id))
    
    text = f"""
📖 **Help - USDTPilotBot**

**User Commands:**
/start - Main menu
/profile - Your profile
/deposit - Make deposit
/withdraw - Make withdraw
/history - Transaction history
/referral - Referral system
/help - This message
/info - Bot info

{f"""
**Admin Commands:**
/admin - Dashboard
/adminpin 1234 - Login
/adminlogout - Logout
/daily - Daily report
/weekly - Weekly report
/top - Top users
/search - Search user
/deleteuser - Delete user
/settings - System settings
/set key value - Update setting
/backup - Backup database
/maintenance on/off - Maintenance mode
/broadcast msg - Send message
""" if is_admin else ""}
"""
    bot.reply_to(message, text, parse_mode='Markdown')

# ========== CALLBACK HANDLERS ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
    if get_setting('maintenance_mode') == 'true' and user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🔧 Bot is under maintenance")
        return
    
    # ===== PROFILE =====
    if data == "profile":
        user = get_user(user_id)
        if user:
            active_deposit = 0.00
            total_profit = 0.00
            status = "No Deposit" if (user[2] or 0) == 0 else "Active"
            withdrawal_lock = "Unlocked"
            
            keyboard_status = "Visible" if is_keyboard_visible(user_id) else "Hidden"
            
            bot.edit_message_text(
                f"""
👤 **PROFILE**

🆔 ID: `{user[0]}`
👤 Name: @{user[1] or 'No username'}
💰 Balance: ${user[2]:.2f}
📊 Active Deposit: ${active_deposit:.2f}
📈 Total Profit: ${total_profit:.2f}
📌 Status: {status}
🔒 Withdrawal Lock: {withdrawal_lock}

{datetime.now().strftime('%I:%M %p')}

━━━━━━━━━━━━━━━━━━━

⌨️ **Keyboard: {keyboard_status}**

📱 **Menu**
""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=get_keyboard_menu(user_id)
            )
    
    # ===== TOGGLE KEYBOARD =====
    elif data == "toggle_keyboard":
        visible = toggle_keyboard(user_id)
        user = get_user(user_id)
        
        if user:
            active_deposit = 0.00
            total_profit = 0.00
            status = "No Deposit" if (user[2] or 0) == 0 else "Active"
            withdrawal_lock = "Unlocked"
            
            keyboard_status = "Visible" if visible else "Hidden"
            menu = profile_menu() if visible else back_button()
            
            bot.edit_message_text(
                f"""
👤 **PROFILE**

🆔 ID: `{user[0]}`
👤 Name: @{user[1] or 'No username'}
💰 Balance: ${user[2]:.2f}
📊 Active Deposit: ${active_deposit:.2f}
📈 Total Profit: ${total_profit:.2f}
📌 Status: {status}
🔒 Withdrawal Lock: {withdrawal_lock}

{datetime.now().strftime('%I:%M %p')}

━━━━━━━━━━━━━━━━━━━

⌨️ **Keyboard: {keyboard_status}**

{"📱 **Menu**" if visible else "🔹 Tap menu button below to show options"}
""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=menu
            )
    
    # ===== DEPOSIT =====
    elif data == "deposit":
        bot.edit_message_text(
            "💳 **Deposit**\n\nSelect network to see deposit address:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=deposit_networks()
        )
    
    # ===== DEPOSIT NETWORKS =====
    elif data.startswith("deposit_"):
        network = data.replace("deposit_", "").upper()
        
        addresses = {
            "TRC20": "TLPVBmQnS6VTV7MwzLzYy7EjUKqsKob7hs",
            "BEP20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
            "ERC20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
            "TON": "UQBGo3k-EhMubMv4h3RqHszdcJdqoxttvZnuwDvPHbk8jl6P"
        }
        
        address = addresses.get(network, "Address not found")
        
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📝 Submit Amount", callback_data="submit_deposit"),
            InlineKeyboardButton("🔙 Back", callback_data="deposit")
        )
        
        bot.edit_message_text(
            f"""
💳 **Deposit via {network}**

📌 **Send USDT to this address:**

`{address}`

⚠️ **Important:**
• Only send USDT on {network} network
• Minimum: {get_setting('min_deposit')} USDT
• Maximum: {get_setting('max_deposit')} USDT

📝 After sending, press "Submit Amount" or use:
`/deposit_amount 100`

⏳ Status will be PENDING until admin approves
""",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    # ===== SUBMIT DEPOSIT =====
    elif data == "submit_deposit":
        bot.edit_message_text(
            f"""
📝 **Submit Deposit Amount**

Send the amount you sent:

`/deposit_amount 100`

Min: {get_setting('min_deposit')} USDT
Max: {get_setting('max_deposit')} USDT
""",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    
    # ===== WITHDRAW =====
    elif data == "withdraw":
        bot.edit_message_text(
            f"""
💸 **Withdraw**

Send amount:
`/withdraw 50`

Min: {get_setting('min_withdraw')} USDT
Max: {get_setting('max_withdraw')} USDT
""",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    
    # ===== HISTORY =====
    elif data == "history":
        history = get_transaction_history(user_id, 10)
        if not history:
            text = "📜 No transactions yet"
        else:
            text = "📜 **Transaction History**\n\n"
            for tx in history:
                status_emoji = "✅" if tx[2] == "APPROVED" else "❌" if tx[2] == "REJECTED" else "⏳"
                text += f"{status_emoji} **{tx[0]}**\n"
                text += f"   Amount: ${tx[1]:.2f}\n"
                text += f"   Status: {tx[2]}\n"
                text += f"   Date: {tx[4][:16]}\n\n"
        
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    
    # ===== REFERRAL =====
    elif data == "referral":
        bot_username = bot.get_me().username
        link = f"https://t.me/{bot_username}?start={user_id}"
        referrals = get_referral_count(user_id)
        bonus = get_setting('referral_bonus') or 0.5
        bot.edit_message_text(
            f"""
👥 **Referral System**

🔗 Your link:
`{link}`

🎁 Bonus: {bonus} USDT per referral

👥 Total referrals: {referrals}

Share your link and earn!
""",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=back_button()
        )
    
    # ===== BACK =====
    elif data == "back":
        user = get_user(user_id)
        if user:
            active_deposit = 0.00
            total_profit = 0.00
            status = "No Deposit" if (user[2] or 0) == 0 else "Active"
            withdrawal_lock = "Unlocked"
            
            keyboard_status = "Visible" if is_keyboard_visible(user_id) else "Hidden"
            
            bot.edit_message_text(
                f"""
👤 **PROFILE**

🆔 ID: `{user[0]}`
👤 Name: @{user[1] or 'No username'}
💰 Balance: ${user[2]:.2f}
📊 Active Deposit: ${active_deposit:.2f}
📈 Total Profit: ${total_profit:.2f}
📌 Status: {status}
🔒 Withdrawal Lock: {withdrawal_lock}

{datetime.now().strftime('%I:%M %p')}

━━━━━━━━━━━━━━━━━━━

⌨️ **Keyboard: {keyboard_status}**

📱 **Menu**
""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=get_keyboard_menu(user_id)
            )
    
    # ===== ADMIN FEATURES =====
    elif data.startswith("admin_"):
        if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
            bot.answer_callback_query(call.id, "❌ Unauthorized")
            return
        
        if data == "admin_dashboard":
            show_admin_dashboard_callback(call)
        
        elif data == "admin_pending":
            pending = get_pending_with_users()
            if not pending:
                text = "✅ No pending requests"
            else:
                text = f"📋 **Pending Requests:** {len(pending)}\n\n"
                for r in pending[:10]:
                    text += f"🆔 `{r[0]}` | @{r[2] or r[1]} | {r[3]} | ${r[4]:.2f}\n"
                    text += f"   🌐 {r[5]} | 📅 {r[6][:16]}\n\n"
            
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup(row_width=2)
            for r in pending[:5]:
                markup.add(
                    InlineKeyboardButton(f"✅ Approve {r[0]}", callback_data=f"approve_{r[0]}"),
                    InlineKeyboardButton(f"❌ Reject {r[0]}", callback_data=f"reject_{r[0]}")
                )
            markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back"))
            
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        
        elif data == "admin_reports":
            stats = get_admin_stats()
            text = f"""
📊 **Reports Dashboard**

📅 {datetime.now().strftime('%Y-%m-%d')}

👥 Total Users: `{stats['total_users']}`
💰 Total Balance: `${stats['total_balance']:.2f}`

📈 **Transactions:**
📥 Deposits: `{stats['total_deposits']}`
📤 Withdraws: `{stats['total_withdraws']}`
⏳ Pending: `{stats['total_pending']}`
✅ Approved: `{stats['total_approved']}`
❌ Rejected: `{stats['total_rejected']}`

Commands: /daily, /weekly, /top
"""
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("📊 Daily", callback_data="admin_daily"),
                InlineKeyboardButton("📊 Weekly", callback_data="admin_weekly"),
                InlineKeyboardButton("🏆 Top", callback_data="admin_top"),
                InlineKeyboardButton("🔙 Back", callback_data="admin_back")
            )
            
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        
        elif data == "admin_users":
            users = get_all_users()
            text = f"👥 **Total Users:** {len(users)}\n\n"
            for u in users[:10]:
                text += f"🆔 `{u[0]}` | @{u[1] or 'No username'} | ${u[2]:.2f}\n"
            
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back"))
            
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        
        elif data == "admin_settings":
            settings = {}
            conn = sqlite3.connect('bot.db')
            c = conn.cursor()
            c.execute("SELECT key, value FROM settings")
            for row in c.fetchall():
                settings[row[0]] = row[1]
            conn.close()
            
            text = "⚙️ **Admin Settings**\n\n"
            for key, value in settings.items():
                text += f"• {key}: `{value}`\n"
            text += "\nUse: `/set key value`"
            
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back"))
            
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        
        elif data == "admin_back":
            show_admin_dashboard_callback(call)
        
        elif data == "admin_logout":
            admin_logout(user_id)
            bot.edit_message_text(
                "🔒 Logged out from admin",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        
        elif data == "admin_daily":
            stats = get_daily_report()
            text = f"""
📊 **Daily Report**
📅 {datetime.now().strftime('%Y-%m-%d')}

👥 New Users: {stats['new_users']}
💰 Total Deposits: ${stats['total_deposits']:.2f}
💸 Total Withdraws: ${stats['total_withdraws']:.2f}
⏳ Pending: {stats['pending']}
✅ Approved: {stats['approved']}
❌ Rejected: {stats['rejected']}
"""
            bot.answer_callback_query(call.id, "📊 Daily report sent")
            bot.send_message(user_id, text, parse_mode='Markdown')
        
        elif data == "admin_weekly":
            stats = get_weekly_report()
            end = datetime.now()
            start = end - timedelta(days=7)
            text = f"""
📊 **Weekly Report**
📅 {start.strftime('%Y-%m-%d')} - {end.strftime('%Y-%m-%d')}

👥 New Users: {stats['new_users']}
💰 Total Deposits: ${stats['total_deposits']:.2f}
💸 Total Withdraws: ${stats['total_withdraws']:.2f}
⏳ Pending: {stats['pending']}
✅ Approved: {stats['approved']}
❌ Rejected: {stats['rejected']}
"""
            bot.answer_callback_query(call.id, "📊 Weekly report sent")
            bot.send_message(user_id, text, parse_mode='Markdown')
        
        elif data == "admin_top":
            top = get_top_users(10)
            if not top:
                text = "📊 No users yet"
            else:
                text = "🏆 **Top 10 Users**\n\n"
                medals = ["🥇", "🥈", "🥉"]
                for i, u in enumerate(top, 1):
                    medal = medals[i-1] if i <= 3 else f"{i}."
                    text += f"{medal} @{u[1] or u[0]} - ${u[2]:.2f}\n"
            
            bot.answer_callback_query(call.id, "🏆 Top users sent")
            bot.send_message(user_id, text, parse_mode='Markdown')
    
    # ===== APPROVE/REJECT =====
    elif data.startswith("approve_") or data.startswith("reject_"):
        if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
            bot.answer_callback_query(call.id, "❌ Unauthorized")
            return
        
        parts = data.split("_")
        action = parts[0]
        tx_id = int(parts[1])
        
        status = "APPROVED" if action == "approve" else "REJECTED"
        update_transaction(tx_id, status)
        bot.answer_callback_query(call.id, f"✅ Transaction #{tx_id} {status}")
        
        pending = get_pending_with_users()
        if pending:
            text = f"📋 **Pending Requests:** {len(pending)}\n\n"
            for r in pending[:10]:
                text += f"🆔 `{r[0]}` | @{r[2] or r[1]} | {r[3]} | ${r[4]:.2f}\n"
                text += f"   🌐 {r[5]} | 📅 {r[6][:16]}\n\n"
        else:
            text = "✅ No pending requests"
        
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(row_width=2)
        for r in pending[:5]:
            markup.add(
                InlineKeyboardButton(f"✅ Approve {r[0]}", callback_data=f"approve_{r[0]}"),
                InlineKeyboardButton(f"❌ Reject {r[0]}", callback_data=f"reject_{r[0]}")
            )
        markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back"))
        
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    else:
        bot.answer_callback_query(call.id, "Unknown action")

# ========== ADMIN DASHBOARD ==========
def show_admin_dashboard(message):
    stats = get_admin_stats()
    pending = get_pending_with_users()
    text = f"""
🔐 **Admin Dashboard**

📊 **Statistics:**
👥 Total Users: `{stats['total_users']}`
🆕 Today: `{stats['today_users']}`

💰 Total Balance: `${stats['total_balance']:.2f}`

📈 **Transactions:**
📥 Deposits: `{stats['total_deposits']}`
📤 Withdraws: `{stats['total_withdraws']}`

⏳ Pending: `{stats['total_pending']}`
✅ Approved: `{stats['total_approved']}`
❌ Rejected: `{stats['total_rejected']}`

---
📋 **Pending Requests:** {len(pending)}
"""
    
    bot.reply_to(message, text, parse_mode='Markdown', reply_markup=admin_menu())

def show_admin_dashboard_callback(call):
    stats = get_admin_stats()
    pending = get_pending_with_users()
    text = f"""
🔐 **Admin Dashboard**

📊 **Statistics:**
👥 Total Users: `{stats['total_users']}`
🆕 Today: `{stats['today_users']}`

💰 Total Balance: `${stats['total_balance']:.2f}`

📈 **Transactions:**
📥 Deposits: `{stats['total_deposits']}`
📤 Withdraws: `{stats['total_withdraws']}`

⏳ Pending: `{stats['total_pending']}`
✅ Approved: `{stats['total_approved']}`
❌ Rejected: `{stats['total_rejected']}`

---
📋 **Pending Requests:** {len(pending)}
"""
    
    bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode='Markdown',
        reply_markup=admin_menu()
    )

# ========== FLASK SERVER ==========
@app.route('/')
@app.route('/health')
def health():
    return "✅ USDTPilotBot is running 24/7!"

@app.route('/status')
def status():
    stats = get_admin_stats()
    return jsonify({
        'status': 'online',
        'users': stats['total_users'],
        'balance': stats['total_balance'],
        'pending': stats['total_pending']
    })

# ========== START ==========
if __name__ == "__main__":
    print("🚀 USDTPilotBot is starting...")
    print("📊 Bot is running 24/7!")
    print(f"🤖 Bot: @USDTPilotBot")
    print(f"👤 Admin ID: {ADMIN_ID}")
    
    thread = threading.Thread(target=bot.infinity_polling, daemon=True)
    thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
