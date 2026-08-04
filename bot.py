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

WELCOME_BANNER = "https://images.unsplash.com/photo-1621416894569-0f39ed31d247?w=800&auto=format&fit=crop&q=60"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Dictionary-ga lagu kaydiyo tillaabooyinka withdrawal-ka ee isticmaalaha
user_withdrawal_data = {}
user_deposit_amounts = {}


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
      "welcome_message": "Welcome to USDTPilotBot! 🚀 Invest & earn profit for 7 days.",
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


# ========== REPLY KEYBOARD ==========
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
  btn_back = KeyboardButton("🔙 Back")

  markup.add(btn_profile, btn_deposit)
  markup.add(btn_investment, btn_withdraw)
  markup.add(btn_history, btn_referral)
  markup.add(btn_terms, btn_support)
  markup.add(btn_back)
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
  result = c.fetchone()[0]
  conn.close()
  return result if result is not None else 0.00


def add_request(user_id, req_type, amount, network):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO transactions (user_id, type, amount, status, network) VALUES"
      " (?, ?, ?, ?, ?)",
      (user_id, req_type, amount, "PENDING", network),
  )
  tx_id = c.lastrowid
  conn.commit()
  conn.close()
  add_notification(
      user_id,
      f"📝 {req_type} request of {amount} USDT submitted. Waiting for admin"
      " approval.",
      "INFO",
  )
  return tx_id


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


# ========== BACKGROUND WORKER ==========
def check_investments():
  while True:
    try:
      conn = sqlite3.connect("bot.db")
      c = conn.cursor()

      c.execute(
          "SELECT id, user_id, amount, profit FROM investments WHERE"
          " status='ACTIVE'"
      )
      active_investments = c.fetchall()

      for inv in active_investments:
        inv_id, user_id, amount, total_profit = inv
        hourly_profit = total_profit / (7 * 24)
        update_balance(user_id, hourly_profit)

      c.execute("""
                SELECT id, user_id, amount FROM investments 
                WHERE status='ACTIVE' AND datetime(created_at, '+7 days') <= datetime('now')
            """)
      expired_investments = c.fetchall()

      for inv in expired_investments:
        inv_id, user_id, amount = inv
        c.execute(
            "UPDATE investments SET status='COMPLETED' WHERE id=?", (inv_id,)
        )
        conn.commit()

        update_balance(user_id, amount)

        completion_msg = f"""🎉 **Investment Cycle Completed!**

Dear Investor,
Your 7-day investment cycle for **${amount:.2f} USDT** has successfully finished! 

💰 Your initial capital and all accumulated profits have been fully credited to your main balance.
🔓 **Withdrawal Status:** Your withdrawal lock has now expired, and you are completely free to withdraw your funds anytime!

Thank you for choosing USDTPilotBot."""

        try:
          bot.send_message(user_id, completion_msg, parse_mode="Markdown")
        except Exception as e:
          print(f"Error sending completion message: {e}")

        add_notification(
            user_id,
            f"🎉 Investment completed for ${amount}! 7-day cycle finished and"
            " funds unlocked.",
            "SUCCESS",
        )

      conn.close()
    except Exception as e:
      print(f"Error in background worker: {e}")
    time.sleep(3600)


# ========== BOT COMMANDS & HANDLERS ==========
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

  if balance > 0 or active_deposit > 0:
    status = "Active 🟢"
  else:
    status = "No Deposit"

  current_time = datetime.now().strftime("%I:%M %p")

  text = f"""👤 **PROFILE & DASHBOARD**

🆔 ID: `{user_id}`
👤 Name: {name}
💰 Balance: `${balance:.2f} USDT`
📊 Active Deposit: `${active_deposit:.2f} USDT`
📈 Hourly Profit: Active (Updates Every Hour) ⏳
⏳ Status: {status}
🔓 Withdrawal Lock: 7 Days Policy Enforced 🛡️ ({current_time})"""

  if send_welcome_photo:
    bot.send_photo(
        chat_id,
        WELCOME_BANNER,
        caption=(
            "🚀 **Welcome to USDTPilotBot!**\n\nInvest & earn profits for 7 days"
            " with hourly updates."
        ),
        parse_mode="Markdown",
    )

  bot.send_message(
      chat_id,
      text,
      parse_mode="Markdown",
      reply_markup=get_main_reply_keyboard(),
  )


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
        "🔙 Back",
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
        "💳 **Deposit Amount**\n\nPlease select the amount you want to deposit:",
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "💎 Investment":
    markup = InlineKeyboardMarkup(row_width=2)
    amounts = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    buttons = []
    for amt in amounts:
      profit_amt = amt * 0.20 * 7
      buttons.append(
          InlineKeyboardButton(
              f"💎 ${amt} ➔ +${profit_amt:.1f} Profit (7 Days)",
              callback_data=f"invest_{amt}",
          )
      )
    markup.add(*buttons)

    user = get_user(user_id)
    user_bal = user[2] if user else 0.00

    invest_menu_text = f"""💎 **PROFESSIONAL INVESTMENT CENTER**

Grow your capital securely with our automated 7-day hourly profit system.

💰 **Your Current Balance:** `{user_bal:.2f} USDT`
📊 **Plan Overview:** `Profits for 7 Days (Hourly Payouts ⏱️ & Unlock after 7 Days)`

👇 **Select your investment package below to purchase instantly:**"""

    bot.send_message(
        message.chat.id,
        invest_menu_text,
        parse_mode="Markdown",
        reply_markup=markup,
    )

  elif text == "💸 Withdraw":
    user = get_user(user_id)
    balance = user[2] if user else 0.00

    # Hubinta in qofku uu leeyahay active investment oo aan 7 maalmood ka soo marin
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        """
            SELECT created_at FROM investments 
            WHERE user_id=? AND status='ACTIVE' 
            ORDER BY created_at ASC LIMIT 1
        """,
        (user_id,),
    )
    active_inv = c.fetchone()
    conn.close()

    if active_inv:
      invest_time = datetime.strptime(active_inv[0], "%Y-%m-%d %H:%M:%S")
      if datetime.now() < invest_time + timedelta(days=7):
        lock_msg = """💰 **Withdrawal Information**

🔒 Your balance is temporarily locked for withdrawal.

⏰ Please wait 7 days from the date your balance was credited.

✅ After the 7-day period, your withdrawal will be unlocked, and you can withdraw your funds normally. 💸

✨ Thank you for choosing our platform!"""
        bot.send_message(message.chat.id, lock_msg, parse_mode="Markdown")
        return

    if balance <= 0:
      bot.send_message(
          message.chat.id,
          "❌ **Your balance is 0.00 USDT.** You need available funds to"
          " withdraw.",
          parse_mode="Markdown",
      )
      return

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💵 TRC20", callback_data="wd_net_TRC20"),
        InlineKeyboardButton("💵 BEP20", callback_data="wd_net_BEP20"),
        InlineKeyboardButton("💵 ERC20", callback_data="wd_net_ERC20"),
        InlineKeyboardButton("💵 TON", callback_data="wd_net_TON"),
    )

    withdraw_text = f"""💸 **WITHDRAWAL CENTER**

💰 **Available Balance:** `{balance:.2f} USDT`

👇 **Please select your withdrawal network below:**"""
    bot.send_message(
        message.chat.id, withdraw_text, parse_mode="Markdown", reply_markup=markup
    )

  elif text == "📜 History":
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🔄 Refresh History", callback_data="refresh_history"
        )
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
   • Investment plans run for a duration of **7 days**.
   • Profits are calculated and added to your balance **every hour automatically** throughout the 7 days.

2. **Withdrawal Lock (7-Day Policy):**
   • For security and stability, withdrawals are locked for **7 days** until your investment cycle successfully completes and funds are unlocked.

3. **Privacy Policy:**
   • Your user data, Telegram ID, and transaction records are kept secure and confidential.

By using USDTPilotBot, you agree to abide by these rules and conditions."""
    bot.send_message(message.chat.id, terms_text, parse_mode="Markdown")

  elif text == "🛠️ Support":
    bot.send_message(
        message.chat.id,
        "🛠️ **Support**\n\nFor any issues or questions, contact admin."
        " @USDTPilotBotsupport12",
        parse_mode="Markdown",
    )

  elif text == "🔙 Back":
    send_profile_card(message.chat.id, user_id, name)


# Message handler for Withdrawal Address input
@bot.message_handler(
    func=lambda msg: msg.from_user.id in user_withdrawal_data
    and user_withdrawal_data[msg.from_user.id].get("step") == "waiting_address"
)
def process_withdraw_address(message):
  user_id = message.from_user.id
  address = message.text.strip()
  user_withdrawal_data[user_id]["address"] = address
  user_withdrawal_data[user_id]["step"] = "waiting_amount"

  user = get_user(user_id)
  balance = user[2] if user else 0.00

  bot.reply_to(
      message,
      f"""📝 **Wallet Address Saved!**
      
Address: `{address}`

💰 **Available Balance:** `{balance:.2f} USDT`
Now, please send the **Amount** you want to withdraw (e.g., `50` or `100`):""",
      parse_mode="Markdown",
  )


# Message handler for Withdrawal Amount input
@bot.message_handler(
    func=lambda msg: msg.from_user.id in user_withdrawal_data
    and user_withdrawal_data[msg.from_user.id].get("step") == "waiting_amount"
)
def process_withdraw_amount(message):
  user_id = message.from_user.id
  data_dict = user_withdrawal_data[user_id]
  network = data_dict["network"]
  address = data_dict["address"]

  try:
    amount = float(message.text.strip())
    if amount <= 0:
      raise ValueError
  except:
    bot.reply_to(
        message,
        "❌ **Invalid Amount!** Please enter a valid number (e.g., `50`).",
        parse_mode="Markdown",
    )
    return

  user = get_user(user_id)
  balance = user[2] if user else 0.00

  if balance < amount:
    bot.reply_to(
        message,
        f"❌ **Insufficient Balance!** You requested `{amount} USDT`, but your"
        f" available balance is `{balance:.2f} USDT`.",
        parse_mode="Markdown",
    )
    return

  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id))
  conn.commit()
  conn.close()

  tx_id = add_request(user_id, "WITHDRAW", amount, network)
  del user_withdrawal_data[user_id]

  name = message.from_user.first_name or "User"
  username = (
      f"@{message.from_user.username}"
      if message.from_user.username
      else "No Username"
  )
  remaining_bal = balance - amount

  admin_msg = f"""🔔 **NEW WITHDRAWAL REQUEST**

👤 **USER PROFILE:**
• **Name:** {name}
• **Username:** {username}
• **User ID:** `{user_id}`
• **Available Balance Before WD:** `${balance:.2f} USDT`
• **Remaining Balance:** `${remaining_bal:.2f} USDT`

💸 **TRANSACTION DETAILS:**
• **Withdrawal Amount:** `{amount} USDT`
• **Network:** `{network}`
• **Destination Wallet Address:** 
`{address}`
• **Transaction ID:** `{tx_id}`"""

  admin_markup = InlineKeyboardMarkup(row_width=2)
  admin_markup.add(
      InlineKeyboardButton(
          "✅ Approve WD", callback_data=f"adm_wd_app_{tx_id}_{user_id}_{amount}"
      ),
      InlineKeyboardButton(
          "❌ Reject WD", callback_data=f"adm_wd_rej_{tx_id}_{user_id}_{amount}"
      ),
  )

  try:
    bot.send_message(
        ADMIN_ID, admin_msg, parse_mode="Markdown", reply_markup=admin_markup
    )
  except Exception as e:
    print(f"Error sending withdrawal to admin: {e}")

  bot.reply_to(
      message,
      f"""✅ **Withdrawal Request Submitted Successfully!**

💰 **Amount:** `{amount:.2f} USDT`
🌐 **Network:** `{network}`
📍 **Address:** `{address}`
⏳ **Status:** `Pending Admin Review`

Your request has been sent to the admin. Funds will be sent to your wallet shortly.""",
      parse_mode="Markdown",
  )


# ========== CALLBACK HANDLERS ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
  user_id = call.from_user.id
  data = call.data

  if data == "refresh_history":
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🔄 Refresh History", callback_data="refresh_history"
        )
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

  elif data.startswith("wd_net_"):
    network = data.replace("wd_net_", "")
    user_withdrawal_data[user_id] = {
        "network": network,
        "step": "waiting_address",
    }

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"💸 **Withdrawal via {network}**\n\nNow, please send your **Wallet"
            " Address** where you want to receive your funds:"
        ),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)

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
• Note: Capital & profits are locked for 7 days per terms.

When you have paid, click I have paid""",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    bot.answer_callback_query(call.id)

  elif data.startswith("paid_"):
    parts = data.split("_")
    amount = float(parts[1])
    network = parts[2]

    tx_id = add_request(user_id, "DEPOSIT", amount, network)

    user_data = get_user(user_id)
    username = (
        f"@{call.from_user.username}" if call.from_user.username else "No Username"
    )
    name = call.from_user.first_name or "User"
    bal = user_data[2] if user_data else 0.00

    addresses = {
        "TRC20": "TLPVBmQnS6VTV7MwzLzYy7EjUKqsKob7hs",
        "BEP20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "ERC20": "0xe4484af8794b0fe2eccf433f7da7ac81935fc4a0",
        "TON": "UQBGo3k-EhMubMv4h3RqHszdcJdqoxttvZnuwDvPHbk8jl6P",
    }
    used_address = addresses.get(network, "Unknown Address")

    admin_msg = f"""🔔 **NEW DEPOSIT PENDING APPROVAL**

👤 **USER PROFILE:**
• **Name:** {name}
• **Username:** {username}
• **User ID:** `{user_id}`
• **Current Balance:** `${bal:.2f} USDT`

💳 **TRANSACTION DETAILS:**
• **Deposit Amount:** `{amount} USDT`
• **Network Used:** `{network}`
• **Target Wallet Address:** 
`{used_address}`
• **Transaction ID:** `{tx_id}`"""

    admin_markup = InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        InlineKeyboardButton(
            "✅ Approve", callback_data=f"adm_app_{tx_id}_{user_id}_{amount}"
        ),
        InlineKeyboardButton(
            "❌ Reject", callback_data=f"adm_rej_{tx_id}_{user_id}_{amount}"
        ),
    )

    try:
      bot.send_message(
          ADMIN_ID, admin_msg, parse_mode="Markdown", reply_markup=admin_markup
      )
    except Exception as e:
      print(f"Error sending to admin: {e}")

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

  # ========== ADMIN DEPOSIT ACTION HANDLERS ==========
  elif data.startswith("adm_app_"):
    if user_id != ADMIN_ID:
      bot.answer_callback_query(call.id, "❌ Unauthorized action!", show_alert=True)
      return

    parts = data.split("_")
    tx_id = parts[2]
    target_user_id = int(parts[3])
    amount = float(parts[4])

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE transactions SET status='APPROVED' WHERE id=?", (tx_id,)
    )
    conn.commit()
    conn.close()

    update_balance(target_user_id, amount)
    
    add_notification(
        target_user_id,
        f"🎉 Your deposit of ${amount} USDT has been approved and added to your balance!",
        "SUCCESS",
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text + f"\n\n✅ **STATUS:** `APPROVED BY ADMIN`",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "✅ Deposit Approved & Balance Updated!")

    user_success_msg = f"""🎉 **Deposit Approved Successfully!**

Dear Investor,
We are pleased to inform you that your deposit of **${amount:.2f} USDT** has been successfully verified and credited to your account balance. 

📈 You can now proceed to invest your funds and start earning automated profits for 7 days! Thank you for choosing USDTPilotBot."""
    try:
      bot.send_message(target_user_id, user_success_msg, parse_mode="Markdown")
    except Exception as e:
      print(f"Error notifying user: {e}")

  elif data.startswith("adm_rej_"):
    if user_id != ADMIN_ID:
      bot.answer_callback_query(call.id, "❌ Unauthorized action!", show_alert=True)
      return

    parts = data.split("_")
    tx_id = parts[2]
    target_user_id = int(parts[3])
    amount = float(parts[4])

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE transactions SET status='REJECTED' WHERE id=?", (tx_id,)
    )
    conn.commit()
    conn.close()

    add_notification(
        target_user_id,
        f"❌ Your deposit of ${amount} USDT was rejected by admin.",
        "ERROR",
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text + f"\n\n❌ **STATUS:** `REJECTED BY ADMIN`",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "❌ Deposit Rejected.")

    user_reject_msg = f"""❌ Deposit Request Declined 🚫

Dear Valued User,
We regret to inform you that your deposit request for ${amount:.2f} USDT could not be verified or approved at this time. ⚠️

🔍 Possible Reasons:
• Incorrect transaction hash or network. 🌐
• The exact transferred amount did not match. 💵
• Payment was not received on our network address. ❌

If you believe this is an error or have completed the payment correctly, please contact our support team with your transaction proof. 🛠️"""
    try:
      bot.send_message(target_user_id, user_reject_msg, parse_mode="Markdown")
    except Exception as e:
      print(f"Error notifying user about rejection: {e}")

  # ========== ADMIN WITHDRAWAL ACTION HANDLERS ==========
  elif data.startswith("adm_wd_app_"):
    if user_id != ADMIN_ID:
      bot.answer_callback_query(call.id, "❌ Unauthorized action!", show_alert=True)
      return

    parts = data.split("_")
    tx_id = parts[3]
    target_user_id = int(parts[4])
    amount = float(parts[5])

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE transactions SET status='APPROVED' WHERE id=?", (tx_id,)
    )
    conn.commit()
    conn.close()

    add_notification(
        target_user_id,
        f"🎉 Your withdrawal of ${amount} USDT has been approved and sent to your"
        " wallet!",
        "SUCCESS",
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text
        + f"\n\n✅ **STATUS:** `WITHDRAWAL APPROVED BY ADMIN`",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "✅ Withdrawal Approved!")

    try:
      bot.send_message(
          target_user_id,
          f"✅ **Withdrawal Sent!**\n\nYour withdrawal of **${amount:.2f}"
          " USDT** has been successfully processed and sent to your wallet"
          " address.",
          parse_mode="Markdown",
      )
    except Exception as e:
      print(f"Error notifying user: {e}")

  elif data.startswith("adm_wd_rej_"):
    if user_id != ADMIN_ID:
      bot.answer_callback_query(call.id, "❌ Unauthorized action!", show_alert=True)
      return

    parts = data.split("_")
    tx_id = parts[3]
    target_user_id = int(parts[4])
    amount = float(parts[5])

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE transactions SET status='REJECTED' WHERE id=?", (tx_id,)
    )
    c.execute(
        "UPDATE users SET balance = balance + ? WHERE id=?",
        (amount, target_user_id),
    )
    conn.commit()
    conn.close()

    add_notification(
        target_user_id,
        f"❌ Your withdrawal of ${amount} USDT was rejected. Funds returned to"
        " balance.",
        "ERROR",
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text
        + f"\n\n❌ **STATUS:** `WITHDRAWAL REJECTED & REFUNDED`",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "❌ Withdrawal Rejected & Refunded.")

    try:
      bot.send_message(
          target_user_id,
          f"❌ **Withdrawal Declined**\n\nYour withdrawal request for"
          f" **${amount:.2f} USDT** was declined by admin. The funds have been"
          " refunded to your balance.",
          parse_mode="Markdown",
      )
    except Exception as e:
      print(f"Error notifying user: {e}")

  elif data.startswith("invest_"):
    amount = float(data.replace("invest_", ""))
    user = get_user(user_id)
    balance = user[2] if user else 0.00

    if balance < amount:
      bot.answer_callback_query(
          call.id,
          f"❌ Insufficient balance! You need ${amount}, but have ${balance:.2f}.",
          show_alert=True,
      )
      return

    total_profit = amount * 0.20 * 7

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(
        "UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id)
    )
    c.execute(
        "INSERT INTO investments (user_id, amount, profit, status) VALUES (?,"
        " ?, ?, 'ACTIVE')",
        (user_id, amount, total_profit),
    )
    conn.commit()
    conn.close()

    bot.answer_callback_query(
        call.id,
        f"✅ Successfully invested ${amount} for 7 days!",
        show_alert=True,
    )
    bot.send_message(
        call.message.chat.id,
        f"""🚀 **7-DAY INVESTMENT ACTIVATED!**

💵 **Invested Amount:** `${amount:.2f} USDT`
📈 **Total Expected Profit:** `+${total_profit:.2f} USDT`
⏱️ **Hourly Distribution:** `Active (Credited every hour for 7 days)`
⏳ **Duration:** `7 Days Cycle`
🛡️ **Security Policy:** `Withdrawal locked until cycle completion`

Your investment is now live and growing automatically!""",
        parse_mode="Markdown",
    )


# ========== FLASK HEALTH CHECK ==========
@app.route("/")
@app.route("/health")
def health():
  return (
      "✅ USDTPilotBot is running 24/7 with 7-Day Auto-Investment & Clean UI!"
  )


if __name__ == "__main__":
  print(
      "🚀 USDTPilotBot is starting with 7-Day Auto-Investment, Clean UI & Banner..."
  )

  inv_thread = threading.Thread(target=check_investments, daemon=True)
  inv_thread.start()

  bot_thread = threading.Thread(target=bot.infinity_polling, daemon=True)
  bot_thread.start()

  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
