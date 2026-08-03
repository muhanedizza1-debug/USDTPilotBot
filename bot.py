from datetime import datetime, timedelta
import json
import os
import sqlite3
import threading
import time
from flask import Flask, jsonify, request
import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# ========== CONFIG ==========
BOT_TOKEN = "8626470350:AAFxJ3S5FjEjgBK-ySNAaKAZHvuOGRhLQ3A"
ADMIN_ID = 7076265514
ADMIN_PIN = "1234"

# Sawirka quruxda badan ee ku soobaxaya Welcome message-ka
WELCOME_BANNER = "https://images.unsplash.com/photo-1621416894569-0f39ed31d247?w=800&auto=format&fit=crop&q=60"

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

  c.execute("""CREATE TABLE IF NOT EXISTS investments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        profit REAL,
        status TEXT DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
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
      "welcome_message": "Welcome to USDTPilotBot! 🚀 Invest & earn 20% profit in 24 hours.",
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
  btn_investment = KeyboardButton("💎 Investment")
  btn_withdraw = KeyboardButton("💸 Withdraw")
  btn_history = KeyboardButton("📜 History")
  btn_referral = KeyboardButton("🎁 Referral")
  btn_terms = KeyboardButton("📜 Terms")
  btn_support = KeyboardButton("🛠️ Support")

  markup.add(btn_profile, btn_deposit)
  markup.add(btn_investment, btn_withdraw)
  markup.add(btn_history, btn_referral)
  markup.add(btn_terms, btn_support)
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


def update_balance(user_id, amount):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id)
  )
  conn.commit()
  conn.close()


def get_active_deposit(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT SUM(amount) FROM investments WHERE user_id=? AND status='ACTIVE'",
      (user_id,),
  )
  total = c.fetchone()[0] or 0.00
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


def get_transaction_history(user_id, limit=10):
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


def add_notification(user_id, message, type="INFO"):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
      (user_id, message, type),
  )
  conn.commit()
  conn.close()


# ========== BACKGROUND WORKER: HOURLY PROFIT & 24H INVESTMENT CHECKER ==========
def check_investments():
  while True:
    try:
      conn = sqlite3.connect("bot.db")
      c = conn.cursor()

      c.execute("SELECT id, user_id, amount FROM investments WHERE status='ACTIVE'")
      active_investments = c.fetchall()

      for inv in active_investments:
        inv_id, user_id, amount = inv
        hourly_profit = (amount * 0.20) / 24
        update_balance(user_id, hourly_profit)

      c.execute("""
                SELECT id, user_id, amount FROM investments 
                WHERE status='ACTIVE' AND datetime(created_at, '+24 hours') <= datetime('now')
            """)
      expired_investments = c.fetchall()

      for inv in expired_investments:
        inv_id, user_id, amount = inv
        c.execute(
            "UPDATE investments SET status='COMPLETED' WHERE id=?", (inv_id,)
        )
        conn.commit()
        add_notification(
            user_id,
            f"🎉 Investment completed for ${amount}! Your 20% total profit"
            " cycle finished.",
            "SUCCESS",
        )

      conn.close()
    except Exception as e:
      print(f"Error in background worker: {e}")
    time.sleep(3600)


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
  send_profile_card(message.chat.id, user_id, username, send_welcome_photo=True)


def send_profile_card(chat_id, user_id, name, send_welcome_photo=False):
  user = get_user(user_id)
  balance = user[2] if user else 0.00
  active_deposit = get_active_deposit(user_id)
  status = "No Deposit" if balance == 0 and active_deposit == 0 else "Active"
  current_time = datetime.now().strftime("%I:%M %p")

  text = f"""👤 **PROFILE & DASHBOARD**

🆔 ID: `{user_id}`
👤 Name: {name}
💰 Balance: ${balance:.2f}
📊 Active Deposit: ${active_deposit:.2f}
📈 Hourly Profit: Active (Updates Every Hour) ⏳
⏳ Status: {status}
🔓 Withdrawal Lock: 7 Days Policy Enforced 🛡️ ({current_time})"""

  if send_welcome_photo:
    bot.send_photo(
        chat_id,
        WELCOME_BANNER,
        caption=(
            "🚀 **Welcome to USDTPilotBot!**\n\nInvest & earn 20% profit in"
            " 24 hours with hourly updates."
        ),
        parse_mode="Markdown",
    )

  bot.send_message(
      chat_id,
      text,
      parse_mode="Markdown",
      reply_markup=get_main_reply_keyboard(),
  )


# Function-ka soo saaraya qoraalka History-ga si loo isticmaali karo Command iyo Callback-ba
def generate_history_text(user_id):
  history = get_transaction_history(user_id, 10)
  if not history:
    return (
        "📜 **TRANSACTION HISTORY**\n\n❌ No transactions found yet.\nYour"
        " deposits and withdrawals will appear here."
    )

  res_text = "📜 **TRANSACTION HISTORY** (Live Updates)\n\n"
  for tx in history:
    tx_type, amount, status, network, created_at = tx
    # Calaamadaha xaaladaha kala duwan
    if status == "APPROVED" or status == "SUCCESS":
      status_emoji = "✅"
      status_desc = "SUCCESSFUL"
    elif status == "REJECTED":
      status_emoji = "❌"
      status_desc = "REJECTED"
    else:
      status_emoji = "⏳"
      status_desc = "PENDING"

    res_text += f"{status_emoji} **{tx_type}** | `{amount:.2f} USDT`\n"
    res_text += f"   • Network: `{network}`\n"
    res_text += f"   • Status: `{status_desc}`\n"
    res_text += f"   • Date: `{created_at[:16]}`\n\n"

  return res_text


@bot.message_handler(
    func=lambda msg: msg.text
    in [
        "👤 My Profile",
        "💳 Deposit",
        "💎 Investment",
        "💸 Withdraw",
        "📜 History",
        "🎁 Referral",
        "📜 Terms",
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
    markup = InlineKeyboardMarkup(row_width=2)
    amounts = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    buttons = [
        InlineKeyboardButton(f"💵 ${amt} USDT", callback_data=f"dep_amt_{amt}")
        for amt in amounts
    ]
    markup.add(*buttons)

    bot.send_message(
        message.chat.id,
        "💳 **Deposit Amount**\n\nPlease select the amount you want to"
        " deposit:",
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "💎 Investment":
    markup = InlineKeyboardMarkup(row_width=2)
    amounts = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    buttons = [
        InlineKeyboardButton(
            f"💲 ${amt} (+20% in 24h)", callback_data=f"invest_{amt}"
        )
        for amt in amounts
    ]
    markup.add(*buttons)

    bot.send_message(
        message.chat.id,
        "💎 **Investment Plans (20% Profit in 24 Hours)**\n\nChoose an amount"
        " to invest from your balance:",
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "💸 Withdraw":
    withdraw_info_text = f"""💸 **WITHDRAWAL CENTER**

Securely payout your available funds directly to your wallet.

📌 **How to Withdraw:**
Type and send the command followed by your amount. 
*Example:* `/withdraw 50`

⚠️ **Important Policy & Limits:**
• **Lock Period:** Withdrawals are securely locked for **7 days** from your last approved deposit/investment time.
• **Minimum Limit:** `{get_setting('min_withdraw')} USDT`
• **Maximum Limit:** `{get_setting('max_withdraw')} USDT`

Need help? Contact our support team anytime."""
    bot.send_message(message.chat.id, withdraw_info_text, parse_mode="Markdown")

  elif text == "📜 History":
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🔄 Refresh History", callback_data="refresh_history")
    )
    history_msg = generate_history_text(user_id)
    bot.send_message(
        message.chat.id,
        history_msg,
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "🎁 Referral":
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start={user_id}"
    bonus = get_setting("referral_bonus") or 0.5
    bot.send_message(
        message.chat.id,
        f"""👥 **Referral System**

🔗 Your link:
`{link}`

🎁 Bonus: {bonus} USDT per referral

Share your link and earn!""",
        parse_mode="Markdown",
    )

  elif text == "📜 Terms":
    terms_text = """📜 **Terms & Conditions / Privacy Policy**

1. **Investment & Profits:**
   • You earn a 20% profit cycle over 24 hours.
   • Profits are calculated and added to your balance **every hour automatically**.

2. **Withdrawal Lock (7-Day Policy):**
   • For security and stability, both your principal deposit and accumulated profits can only be withdrawn **after 7 days** from the exact hour of your deposit/investment.

3. **Privacy Policy:**
   • Your user data, Telegram ID, and transaction records are kept secure and confidential. We never share your details with third parties.

By using USDTPilotBot, you agree to abide by these rules and conditions."""
    bot.send_message(message.chat.id, terms_text, parse_mode="Markdown")

  elif text == "🛠️ Support":
    bot.send_message(
        message.chat.id,
        "🛠️ **Support**\n\nFor any issues or questions, contact admin.",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["withdraw"])
def withdraw_command(message):
  user_id = message.from_user.id
  try:
    amount = float(message.text.split()[1])
    if amount <= 0:
      raise ValueError
  except:
    bot.reply_to(
        message,
        "❌ **Invalid Format!**\nPlease use the correct command structure:\n👉"
        " `/withdraw 50`",
        parse_mode="Markdown",
    )
    return

  user = get_user(user_id)
  if not user or (user[2] or 0) < amount:
    bot.reply_to(
        message,
        f"❌ **Insufficient Balance!**\nYou requested `{amount:.2f} USDT`, but"
        f" your current balance is `{user[2]:.2f} USDT`.",
        parse_mode="Markdown",
    )
    return

  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      """
        SELECT created_at FROM transactions 
        WHERE user_id=? AND type='DEPOSIT' AND status='APPROVED' 
        ORDER BY created_at DESC LIMIT 1
    """,
      (user_id,),
  )
  last_deposit = c.fetchone()
  conn.close()

  if last_deposit:
    deposit_time = datetime.strptime(last_deposit[0], "%Y-%m-%d %H:%M:%S")
    if datetime.now() < deposit_time + timedelta(days=7):
      remaining = (deposit_time + timedelta(days=7)) - datetime.now()
      days_left = remaining.days
      hours_left = remaining.seconds // 3600

      lock_msg = f"""❌ **Withdrawal Temporarily Locked**

🛡️ In accordance with our security guidelines and the 7-day policy, withdrawals are restricted until the lock period expires.

⏳ **Time Remaining:** 
• `{days_left} Days and {hours_left} Hours`

Thank you for your patience and cooperation."""
      bot.reply_to(message, lock_msg, parse_mode="Markdown")
      return

  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id))
  conn.commit()
  conn.close()

  add_request(user_id, "WITHDRAW", amount, "USDT")

  success_msg = f"""✅ **Withdrawal Request Submitted Successfully!**

📌 **Amount:** `{amount:.2f} USDT`
🔄 **Status:** `Pending Admin Review`

Your transaction is being processed. Funds will be transferred to your wallet shortly."""
  bot.reply_to(message, success_msg, parse_mode="Markdown")


user_deposit_amounts = {}


# ========== CALLBACK HANDLERS (Deposit Networks, Investment & History Refresh) ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
  user_id = call.from_user.id
  data = call.data

  if data == "refresh_history":
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🔄 Refresh History", callback_data="refresh_history")
    )
    updated_history = generate_history_text(user_id)
    try:
      bot.edit_message_text(
          chat_id=call.message.chat.id,
          message_id=call.message.message_id,
          text=updated_history,
          parse_mode="Markdown",
          reply_markup=markup,
      )
      bot.answer_callback_query(call.id, "✅ History updated successfully!")
    except Exception:
      bot.answer_callback_query(call.id, "⚠️ History is already up to date.")

  elif data.startswith("dep_amt_"):
    amount = data.replace("dep_amt_", "")
    user_deposit_amounts[user_id] = amount

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "💵 TRC20 (USDT)", callback_data=f"dep_net_TRC20_{amount}"
        ),
        InlineKeyboardButton(
            "💵 BEP20 (USDT)", callback_data=f"dep_net_BEP20_{amount}"
        ),
        InlineKeyboardButton(
            "💵 ERC20 (USDT)", callback_data=f"dep_net_ERC20_{amount}"
        ),
        InlineKeyboardButton(
            "💵 TON (USDT)", callback_data=f"dep_net_TON_{amount}"
        ),
    )
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"💳 **Deposit Amount: ${amount} USDT**\n\nSelect network to see"
            " deposit address:"
        ),
        parse_mode="Markdown",
        reply_markup=markup,
    )
    bot.answer_callback_query(call.id)

  elif data.startswith("dep_net_"):
    parts = data.split("_")
    network = parts[2]
    amount = parts[3]

    addresses = {
        "TRC20": "TLPVBmQnS6VTV7MwzLzYy7EjUKqsKob7hs",
        "BEP20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "ERC20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "TON": "UQBGo3k-EhMubMv4h3RqHszdcJdqoxttvZnuwDvPHbk8jl6P",
    }
    address = addresses.get(network, "Address not found")

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "✅ I Have Paid", callback_data=f"paid_{amount}_{network}"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""💳 **Deposit via {network} (${amount} USDT)**

📌 **Send USDT to this address:**
`{address}`

⚠️ **Important:**
• Only send USDT on {network} network
• Amount: {amount} USDT
• Note: Capital & profits are lockable for 7 days per terms.

When you have paid, click I have paid""",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    bot.answer_callback_query(call.id)

  elif data.startswith("paid_"):
    parts = data.split("_")
    amount = float(parts[1])
    network = parts[2]

    add_request(user_id, "DEPOSIT", amount, network)
    bot.answer_callback_query(
        call.id,
        "✅ Payment notification sent to admin! Waiting for approval.",
        show_alert=True,
    )
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""✅ **Deposit Request Submitted!**

💰 Amount: `{amount} USDT`
🌐 Network: `{network}`
⏳ Status: `PENDING`

Your balance will be updated automatically once the admin approves your transaction.""",
        parse_mode="Markdown",
    )

  elif data.startswith("invest_"):
    amount = float(data.replace("invest_", ""))
    user = get_user(user_id)
    balance = user[2] if user else 0.00

    if balance < amount:
      bot.answer_callback_query(
          call.id,
          "❌ Insufficient balance! Please deposit first.",
          show_alert=True,
      )
      return

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id)
    )
    c.execute(
        "INSERT INTO investments (user_id, amount, profit, status) VALUES (?,"
        " ?, ?, 'ACTIVE')",
        (user_id, amount, amount * 0.20),
    )
    conn.commit()
    conn.close()

    bot.answer_callback_query(
        call.id,
        f"✅ Successfully invested ${amount}! Hourly profits started.",
        show_alert=True,
    )
    bot.send_message(
        call.message.chat.id,
        f"💎 **Investment Activated!**\n\nAmount: `${amount}`\nExpected Profit:"
        f" `+${amount * 0.20:.2f}` (20% in 24h)\n⏱️ ** Hourly Profit:** Added"
        " every hour automatically!\n🛡️ **7 Days Lock:** Applies to principal &"
        " earnings.",
        parse_mode="Markdown",
    )


# ========== FLASK HEALTH CHECK ==========
@app.route("/")
@app.route("/health")
def health():
  return "✅ USDTPilotBot is running 24/7 with Live History, Terms & Hourly Profits!"


if __name__ == "__main__":
  print(
      "🚀 USDTPilotBot is starting with Live History Refresh, Banner & Terms..."
  )

  inv_thread = threading.Thread(target=check_investments, daemon=True)
  inv_thread.start()

  bot_thread = threading.Thread(target=bot.infinity_polling, daemon=True)
  bot_thread.start()

  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
