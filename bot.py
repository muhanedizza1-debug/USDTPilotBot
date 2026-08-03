  elif data.startswith("supp_app_"):
    if user_id != ADMIN_ID:
      bot.answer_callback_query(call.id, "❌ Unauthorized action!", show_alert=True)
      return

    target_user_id = int(data.replace("supp_app_", ""))

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text + f"\n\n✅ **STATUS:** `ACCEPTED BY ADMIN`",
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "✅ Support request accepted!")

    # Halkaan waxaad ku dari kartaa username-ka ama xiriirka admin-ka ee saxda ah
    admin_username = "@HalkanGeliAdminUsername" # Ku bedel username-kaaga Telegram-ka
    
    user_success_msg = f"""✅ **Support Request Accepted!**

Dear User,
Your support request has been accepted by the admin. You can now communicate your issue or questions directly by reaching out here: 
👉 {admin_username}"""
    
    try:
      bot.send_message(target_user_id, user_success_msg, parse_mode="Markdown")
    except Exception as e:
      print(f"Error notifying user: {e}")
