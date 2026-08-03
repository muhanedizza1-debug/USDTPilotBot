from datetime import datetime, timedelta
import json
import os
import sqlite3
import threading
import time
from flask import Flask, jsonify, request
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# ========== CONFIG ==========
BOT_TOKEN = "8626470350:AAFxJ3S5FjEjgBK-ySNAaKAZHvuOGRhLQ3A"
ADMIN_ID = 7076265514
ADMIN_PIN = "1234"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ========== DATABASE ==========
def init_db():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()

  c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        referred_by INTEGER DEFAULT 0,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        status TEXT,
        network TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        type TEXT,
        read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  default_settings = {
      "bonus_amount": "1.0",
      "min_deposit": "10",
      "max_deposit": "10000",
      "min_withdraw": "10",
      "max_withdraw": "10000",
      "referral_bonus": "0.5",
      "maintenance_mode": "false",
      "welcome_message": "Welcome to USDTPilotBot! 🚀",
      "currency": "USDT",
  }

  for key, value in default_settings.items():
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )

  conn.commit()
  conn.close()


init_db()


# ========== REPLY KEYBOARD (Menu-ga hoose) ==========
def get_main_reply_keyboard():
  markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
  btn_profile = KeyboardButton("👤 My Profile")
  btn_deposit = KeyboardButton("💳 Deposit")
  btn_mining = KeyboardButton("📈 Mining")
  btn_withdraw = KeyboardButton("💸 Withdraw")
  btn_history = KeyboardButton("📜 History")
  btn_referral = KeyboardButton("🎁 Referral")
  btn_support = KeyboardButton("🛠️ Support")

  markup.add(btn_profile, btn_deposit)
  markup.add(btn_mining, btn_withdraw)
  markup.add(btn_history, btn_referral)
  markup.add(btn_support)
  return markup


# ========== DATABASE FUNCTIONS ==========
def get_setting(key):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT value FROM settings WHERE key=?", (key,))
  result = c.fetchone()
  conn.close()
  return result[0] if result else None


def update_setting(key, value):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
  conn.commit()
  conn.close()


def add_user(user_id, username, referred_by=0):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT id FROM users WHERE id=?", (user_id,))
  if not c.fetchone():
    c.execute(
        "INSERT INTO users (id, username, referred_by) VALUES (?, ?, ?)",
        (user_id, username, referred_by),
    )
    if referred_by > 0:
      bonus = float(get_setting("referral_bonus") or 0.5)
      update_balance(referred_by, bonus)
      add_notification(
          referred_by, f"🎉 New referral! You earned {bonus} USDT", "SUCCESS"
      )
    conn.commit()
  conn.close()


def get_user(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT * FROM users WHERE id=?", (user_id,))
  data = c.fetchone()
  conn.close()
  return data


def get_all_users():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT id, username, balance FROM users ORDER BY balance DESC")
  data = c.fetchall()
  conn.close()
  return data


def get_top_users(limit=10):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT id, username, balance FROM users ORDER BY balance DESC LIMIT ?",
      (limit,),
  )
  data = c.fetchall()
  conn.close()
  return data


def search_user(query):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT id, username, balance FROM users WHERE id LIKE ? OR username"
      " LIKE ?",
      (f"%{query}%", f"%{query}%"),
  )
  data = c.fetchall()
  conn.close()
  return data


def delete_user(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("DELETE FROM users WHERE id=?", (user_id,))
  c.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))
  conn.commit()
  conn.close()


def update_balance(user_id, amount):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id)
  )
  conn.commit()
  conn.close()


def get_total_balance():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT SUM(balance) FROM users")
  total = c.fetchone()[0] or 0
  conn.close()
  return total


def get_total_users():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT COUNT(*) FROM users")
  total = c.fetchone()[0]
  conn.close()
  return total


def get_today_users():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT COUNT(*) FROM users WHERE DATE(registered_at) = DATE('now')")
  total = c.fetchone()[0]
  conn.close()
  return total


def get_referral_count(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
  total = c.fetchone()[0]
  conn.close()
  return total


def add_request(user_id, req_type, amount, network):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO transactions (user_id, type, amount, status, network) VALUES"
      " (?, ?, ?, ?, ?)",
      (user_id, req_type, amount, "PENDING", network),
  )
  conn.commit()
  conn.close()
  add_notification(
      user_id,
      f"📝 {req_type} request of {amount} USDT submitted. Waiting for admin"
      " approval.",
      "INFO",
  )


def get_pending():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT * FROM transactions WHERE status='PENDING' ORDER BY created_at DESC")
  return c.fetchall()


def get_pending_with_users():
  conn = sqlite3.connect("bot.db")
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
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("UPDATE transactions SET status=? WHERE id=?", (status, tx_id))
  conn.commit()
  conn.close()
  if status == "APPROVED":
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "SELECT user_id, amount, type FROM transactions WHERE id=?", (tx_id,)
    )
    tx = c.fetchone()
    if tx:
      if tx[2] == "DEPOSIT":
        update_balance(tx[0], tx[1])
        add_notification(
            tx[0],
            f"✅ Deposit of {tx[1]} USDT approved! Balance updated.",
            "SUCCESS",
        )
      elif tx[2] == "WITHDRAW":
        add_notification(tx[0], f"✅ Withdraw of {tx[1]} USDT approved!", "SUCCESS")
    conn.close()
  elif status == "REJECTED":
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "SELECT user_id, amount, type FROM transactions WHERE id=?", (tx_id,)
    )
    tx = c.fetchone()
    if tx:
      add_notification(tx[0], f"❌ {tx[2]} of {tx[1]} USDT rejected.", "WARNING")
    conn.close()


def get_transaction_history(user_id, limit=20):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      """
    SELECT type, amount, status, network, created_at
    FROM transactions
    WHERE user_id=?
    ORDER BY created_at DESC LIMIT ?
    """,
      (user_id, limit),
  )
  data = c.fetchall()
  conn.close()
  return data


def get_deposit_total():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT SUM(amount) FROM transactions WHERE type='DEPOSIT' AND"
      " status='APPROVED'"
  )
  total = c.fetchone()[0] or 0
  conn.close()
  return total


def get_withdraw_total():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT SUM(amount) FROM transactions WHERE type='WITHDRAW' AND"
      " status='APPROVED'"
  )
  total = c.fetchone()[0] or 0
  conn.close()
  return total


def get_transactions_by_status(status):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT COUNT(*) FROM transactions WHERE status=?", (status,))
  total = c.fetchone()[0]
  conn.close()
  return total


def add_notification(user_id, message, type="INFO"):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
      (user_id, message, type),
  )
  conn.commit()
  conn.close()


admin_sessions = {}


def is_admin_logged_in(user_id):
  return user_id == ADMIN_ID and admin_sessions.get(user_id, False)


def admin_login(user_id):
  admin_sessions[user_id] = True


def admin_logout(user_id):
  if user_id in admin_sessions:
    del admin_sessions[user_id]


def get_admin_stats():
  return {
      "total_users": get_total_users(),
      "today_users": get_today_users(),
      "total_balance": get_total_balance(),
      "total_deposits": int(get_deposit_total()),
      "total_withdraws": int(get_withdraw_total()),
      "total_pending": len(get_pending()),
      "total_approved": get_transactions_by_status("APPROVED"),
      "total_rejected": get_transactions_by_status("REJECTED"),
  }


# ========== BOT COMMANDS & MESSAGE HANDLERS ==========
@bot.message_handler(commands=["start"])
def start(message):
  user_id = message.from_user.id
  username = message.from_user.first_name or "User"

  if get_setting("maintenance_mode") == "true" and user_id != ADMIN_ID:
    bot.reply_to(message, "🔧 Bot is under maintenance. Please try again later.")
    return

  referred_by = 0
  if message.text and " " in message.text:
    try:
      referred_by = int(message.text.split()[1])
      if referred_by == user_id:
        referred_by = 0
    except:
      pass

  add_user(user_id, username, referred_by)
  send_profile_card(message.chat.id, user_id, username)


def send_profile_card(chat_id, user_id, name):
  user = get_user(user_id)
  balance = user[2] if user else 0.00
  active_deposit = 0.00
  total_profit = 0.00
  status = "No Deposit" if balance == 0 else "Active"
  current_time = datetime.now().strftime("%I:%M %p")

  text = f"""👤 **PROFILE**

🆔 ID: `{user_id}`
👤 Name: {name}
💰 Balance: ${balance:.2f}
📊 Active Deposit: ${active_deposit:.2f}
📈 Total Profit: ${total_profit:.2f}
⏳ Status: {status}
🔓 Withdrawal Lock: Unlocked ✅ {current_time}"""

  bot.send_message(
      chat_id,
      text,
      parse_mode="Markdown",
      reply_markup=get_main_reply_keyboard(),
  )


# Text Handler-ka badhamada Reply Keyboard-ka hoose
@bot.message_handler(
    func=lambda msg: msg.text
    in [
        "👤 My Profile",
        "💳 Deposit",
        "📈 Mining",
        "💸 Withdraw",
        "📜 History",
        "🎁 Referral",
        "🛠️ Support",
    ]
)
def handle_reply_menu(message):
  user_id = message.from_user.id
  name = message.from_user.first_name or "User"
  text = message.text

  if text == "👤 My Profile":
    send_profile_card(message.chat.id, user_id, name)

  elif text == "💳 Deposit":
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💵 TRC20 (USDT)", callback_data="deposit_trc20"),
        InlineKeyboardButton("💵 BEP20 (USDT)", callback_data="deposit_bep20"),
        InlineKeyboardButton("💵 ERC20 (USDT)", callback_data="deposit_erc20"),
        InlineKeyboardButton("💵 TON (USDT)", callback_data="deposit_ton"),
    )
    bot.send_message(
        message.chat.id,
        "💳 **Deposit**\n\nSelect network to see deposit address:",
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "📈 Mining":
    bot.send_message(
        message.chat.id,
        "📈 **Mining**\n\nMining feature coming soon! Stay tuned.",
        parse_mode="Markdown",
    )

  elif text == "💸 Withdraw":
    bot.send_message(
        message.chat.id,
        f"""💸 **Withdraw**

Send amount using command:
`/withdraw 50`

Min: {get_setting('min_withdraw')} USDT
Max: {get_setting('max_withdraw')} USDT""",
        parse_mode="Markdown",
    )

  elif text == "📜 History":
    history = get_transaction_history(user_id, 10)
    if not history:
      res_text = "📜 No transactions yet"
    else:
      res_text = "📜 **Transaction History**\n\n"
      for tx in history:
        status_emoji = (
            "✅" if tx[2] == "APPROVED" else "❌" if tx[2] == "REJECTED" else "⏳"
        )
        res_text += f"{status_emoji} **{tx[0]}**\n"
        res_text += f"   Amount: ${tx[1]:.2f}\n"
        res_text += f"   Status: {tx[2]}\n"
        res_text += f"   Date: {tx[4][:16]}\n\n"
    bot.send_message(message.chat.id, res_text, parse_mode="Markdown")

  elif text == "🎁 Referral":
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start={user_id}"
    referrals = get_referral_count(user_id)
    bonus = get_setting("referral_bonus") or 0.5
    bot.send_message(
        message.chat.id,
        f"""👥 **Referral System**

🔗 Your link:
`{link}`

🎁 Bonus: {bonus} USDT per referral

👥 Total referrals: {referrals}

Share your link and earn!""",
        parse_mode="Markdown",
    )

  elif text == "🛠️ Support":
    bot.send_message(
        message.chat.id,
        "🛠️ **Support**\n\nFor any issues or questions, contact admin: "
        f"@{bot.get_me().username} or message @{ADMIN_ID}",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["admin"])
def admin_command(message):
  user_id = message.from_user.id
  if user_id != ADMIN_ID:
    bot.reply_to(message, "❌ Unauthorized")
    return

  if is_admin_logged_in(user_id):
    show_admin_dashboard(message)
  else:
    bot.reply_to(message, "🔐 Please login first:\n/adminpin 1234")


@bot.message_handler(commands=["adminpin"])
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


@bot.message_handler(commands=["withdraw"])
def withdraw_command(message):
  user_id = message.from_user.id
  if get_setting("maintenance_mode") == "true":
    bot.reply_to(message, "🔧 Bot is under maintenance.")
    return

  try:
    amount = float(message.text.split()[1])
    if amount <= 0:
      raise ValueError
    min_withdraw = float(get_setting("min_withdraw") or 10)
    max_withdraw = float(get_setting("max_withdraw") or 10000)
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
        parse_mode="Markdown",
    )
    return

  add_request(user_id, "WITHDRAW", amount, "USDT")
  bot.reply_to(
      message,
      f"""✅ **Withdraw request submitted!**

📌 Amount: `{amount:.2f}` USDT
⏳ Status: PENDING

Admin will approve.""",
      parse_mode="Markdown",
  )


@bot.message_handler(commands=["deposit_amount"])
def deposit_amount(message):
  user_id = message.from_user.id
  try:
    amount = float(message.text.split()[1])
    if amount <= 0:
      raise ValueError
  except:
    bot.reply_to(message, "❌ Use: /deposit_amount 100")
    return

  add_request(user_id, "DEPOSIT", amount, "TRC20")
  bot.reply_to(
      message,
      f"✅ **Deposit request of {amount:.2f} USDT submitted!** Status: PENDING",
      parse_mode="Markdown",
  )


# ========== CALLBACK HANDLERS (Network Deposit & Admin) ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
  user_id = call.from_user.id
  data = call.data

  if data.startswith("deposit_"):
    network = data.replace("deposit_", "").upper()
    addresses = {
        "TRC20": "TLPVBmQnS6VTV7MwzLzYy7EjUKqsKob7hs",
        "BEP20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "ERC20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "TON": "UQBGo3k-EhMubMv4h3RqHszdcJdqoxttvZnuwDvPHbk8jl6P",
    }
    address = addresses.get(network, "Address not found")

    bot.send_message(
        call.message.chat.id,
        f"""💳 **Deposit via {network}**

📌 **Send USDT to this address:**
`{address}`

⚠️ **Important:**
• Only send USDT on {network} network
• Minimum: {get_setting('min_deposit')} USDT

📝 After sending, use:
`/deposit_amount 100`""",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


def show_admin_dashboard(message):
  stats = get_admin_stats()
  pending = get_pending_with_users()
  text = f"""🔐 **Admin Dashboard**

📊 **Statistics:**
👥 Total Users: `{stats['total_users']}`
🆕 Today: `{stats['today_users']}`
💰 Total Balance: `${stats['total_balance']:.2f}`

⏳ Pending Requests: {len(pending)}"""
  bot.reply_to(message, text, parse_mode="Markdown")


# ========== FLASK HEALTH CHECK ==========
@app.route("/")
@app.route("/health")
def health():
  return "✅ USDTPilotBot is running 24/7!"


if __name__ == "__main__":
  print("🚀 USDTPilotBot is starting with the new interface...")
  thread = threading.Thread(target=bot.infinity_polling, daemon=True)
  thread.start()

  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
