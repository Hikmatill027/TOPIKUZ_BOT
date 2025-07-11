import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, filters, MessageHandler, CallbackQueryHandler, \
    ConversationHandler
from apscheduler.schedulers.background import BackgroundScheduler
import os, database, tempfile
import random
from dotenv import load_dotenv
from gtts import gTTS
import signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# States for buttons
PRONOUNCE = 1
ADD_WORD = 2
REVIEW_TEXT = 3
FEEDBACK = 4


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Sends a menu with buttons instead of requiring text commands. """
    try:
        keyboard = [
            ["📚 Takrorlash", "📖 Grammar"],
            ["🏆 Leaderboard", "📊 Progressiyam"],
            ["🎧 Talaffuz", "➕ So'z qo'shish"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "👋 안녕하세요! TOPIK Helper Bot-ga xush kelibsiz!\n\n"
            "Quyidagi tugmalardan birini tanlang:", reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start function: {e}")
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.")


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Handle button-based commands instead of text commands. """
    text = update.message.text.strip()

    if text == "📚 Takrorlash":
        await review_word(update, context)
        return REVIEW_TEXT
    elif text == "➕ So'z qo'shish":
        keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_add_word")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📝 Yangi so‘zni quyidagi formatda yuboring:\n`한국어 - Oʻzbekcha`\n\n" 
                                        "❌ Bekor qilish uchun tugmani bosing.",
                                        reply_markup=reply_markup)
        return ADD_WORD
    elif text == "🏆 Leaderboard":
        await show_leaderboard(update, context)
    elif text == "📊 Progressiyam":
        await show_progress(update, context)
    elif text == "🎧 Talaffuz":
        await update.message.reply_text("Talaffuz qilmoqchi bo‘lgan so‘zni yuboring.")
        return PRONOUNCE
    elif text == "📖 Grammar":
        await show_grammar_levels(update, context)
    elif text == "🔙 Orqaga":
        await start(update, context)
    else:
        await update.message.reply_text("⚠️ Noto‘g‘ri tanlov. Tugmalardan birini tanlang.")


async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ User adds one or more flashcards: Korean -> Uzbek (multiple entries supported) """
    user_id = update.message.from_user.id
    message = update.message.text.strip()

    # Check if the user wants to cancel
    if message.lower() in ["❌ cancel", "❌ bekor qilish"]:
        await update.message.reply_text("❌ So'z qo'shish jarayoni bekor qilindi.")
        return ConversationHandler.END

    database.add_user(user_id)
    message = message.replace("/add", "").strip()

    lines = message.split("\n")
    added_words = []
    failed_lines = []
    words_to_add = []

    for line in lines:
        if " - " not in line:
            failed_lines.append(line)
            continue

        korean, uzbek = line.split(" - ", 1)
        korean, uzbek = korean.strip(), uzbek.strip()

        # Ensure it's not a duplicate
        if database.word_exists(user_id, korean):
            continue

        words_to_add.append((korean, uzbek))
        added_words.append(f"🇰🇷 {korean} → 🇺🇿 {uzbek}")

    if words_to_add:
        database.add_flashcard(user_id, words_to_add)

        print(f"Adding {len(words_to_add)} words for user {user_id}")
        database.update_progress(user_id, words_added=len(words_to_add))

        success_message = "✅ Quyidagi so‘zlar qo‘shildi:\n" + "\n".join(added_words)
        await update.message.reply_text(success_message)
        return ADD_WORD
    else:
        await update.message.reply_text("⚠️ Hech qanday to‘g‘ri formatdagi so‘z topilmadi.")

    # Notify about errors
    if failed_lines:
        error_message = "⚠️ Quyidagi so‘zlar noto‘g‘ri formatda edi va qo‘shilmadi:\n" + "\n".join(failed_lines)
        await update.message.reply_text(error_message)

    return ConversationHandler.END


async def cancel_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the add word process."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ So'z qo'shish jarayoni bekor qilindi.")
    return ConversationHandler.END


#              Takrorlash quiz
async def review_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a 10-question multiple-choice quiz"""
    user_id = update.message.from_user.id
    try:
        database.add_user(user_id)

        flashcards = database.get_due_flashcard(user_id, limit=10)  # Fetch 10 questions

        if flashcards:
            context.user_data["quiz_questions"] = flashcards  # Store questions
            context.user_data["quiz_index"] = 0  # Track progress
            context.user_data["correct_count"] = 0  # Track correct answers

            await ask_next_question(update, context)  # Start quiz
        else:
            await update.message.reply_text(
                "❌ Hali hech qanday fleshkarta yoʻq! /add 한국어 - Oʻzbekcha buyrugʻidan foydalanib, qoʻshing."
            )
    except Exception as e:
        logger.error(f"Error in review_word function: {e}")
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.")


async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the next multiple-choice question"""
    quiz_index = context.user_data["quiz_index"]
    quiz_questions = context.user_data["quiz_questions"]

    if quiz_index < len(quiz_questions):
        flashcard_id, korean, correct_answer = quiz_questions[quiz_index]
        context.user_data["current_flashcard"] = (flashcard_id, correct_answer)

        # Get 3 random incorrect options
        incorrect_options = database.get_random_wrong_answers(correct_answer, limit=3)
        options = [correct_answer] + incorrect_options
        random.shuffle(options)  # Shuffle options

        # Create inline keyboard
        buttons = [[InlineKeyboardButton(option, callback_data=option)] for option in options]
        reply_markup = InlineKeyboardMarkup(buttons)

        await update.effective_message.reply_text(f"🇰🇷 {korean}\n\n🇺🇿 Qaysi tarjima to‘g‘ri?",
                                                  reply_markup=reply_markup)
    else:
        await show_quiz_summary(update, context)


async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle answer selection"""
    query = update.callback_query
    if not query:
        return
    user_answer = query.data
    user_id = query.from_user.id
    username = query.from_user.username or f"User_{user_id}"
    await query.answer()

    current_flashcard = context.user_data.get("current_flashcard")

    flashcard_id, correct_answer = current_flashcard

    if user_answer == correct_answer:
        context.user_data["correct_count"] += 1
        database.update_user_score(user_id, username, 5)
        await query.edit_message_text("✅ To‘g‘ri!")
        database.update_flashcard_review(flashcard_id, correct=True)
    else:
        await query.edit_message_text(f"❌ Noto‘g‘ri! To‘g‘ri javob: {correct_answer}")
        database.update_flashcard_review(flashcard_id, correct=False)

    database.track_review(user_id, user_answer == correct_answer)
    context.user_data["quiz_index"] += 1

    # Check if there are more questions
    quiz_index = context.user_data["quiz_index"]
    quiz_questions = context.user_data["quiz_questions"]

    if quiz_index < len(quiz_questions):
        await ask_next_question(update, context)
        return REVIEW_TEXT
    else:
        await show_quiz_summary(update, context)
        return ConversationHandler.END


async def show_quiz_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show final quiz summary"""
    correct_count = context.user_data["correct_count"]
    total_questions = len(context.user_data["quiz_questions"])
    accuracy = (correct_count / total_questions) * 100

    summary_text = (
        f"📊 **Quiz Yakunlandi!**\n"
        f"- **To‘g‘ri javoblar:** {correct_count}/{total_questions}\n"
        f"- **Aniqlik:** {accuracy:.2f}%\n"
        "🔥 Davom eting va TOPIKda muvaffaqiyat qozoning!"
    )

    await update.effective_message.reply_text(summary_text, parse_mode="Markdown")


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Show top 10 users based on their score """
    top_users = database.get_top_users(limit=10)

    if not top_users:
        await update.message.reply_text("📉 Hali hech qanday reyting yo'q.")
        return

    leaderboard_text = "🏆 **Leaderboard** 🏆\n\n"
    for rank, (username, score) in enumerate(top_users, start=1):
        leaderboard_text += f"{rank}. @{username}: {score} ball\n"

    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")


async def set_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ User selects difficulty level after answering correctly """
    difficulty_mapping = {"Qiyin": 1, "Oʻrtacha": 2, "Oson": 3}
    difficulty_text = update.message.text.strip()

    flashcard_id = context.user_data.get("flashcard_id")

    if flashcard_id and difficulty_text in difficulty_mapping:
        difficulty = difficulty_mapping[difficulty_text]
        database.update_difficulty(flashcard_id, difficulty)
        await update.message.reply_text(
            f"✅ Qiyinlik darajasi {difficulty_text} ga oʻrnatildi. Keyingi takrorlash rejalashtirildi!")
    else:
        await update.message.reply_text(
            "❌ Notoʻgʻri tanlov. Iltimos, 'Qiyin', 'Oʻrtacha' yoki 'Oson' dan birini tanlang.")


# Send reminder to keep users entertaining
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """ Sends reminders to users with due flashcards """
    users = database.get_users_with_due_flashcards()

    for user in users:
        user_id = user["user_id"]
        words = database.get_due_flashcard(user_id, limit=10)
        if words:
            words_text = "\n".join([f"🇰🇷 {korean}" for _, korean, _ in words])
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎯 **Bugungi chaqiruv:**\n{words_text}\n\nJavoblaringizni yuboring!",
                parse_mode="Markdown"
            )


def start_scheduler(application: Application):
    """ Starts the scheduler for reminders """
    scheduler = BackgroundScheduler(timezone="Asia/Tashkent")  # Set timezone
    scheduler.add_job(lambda: application.create_task(send_reminder(application)), 'cron', hour=6, minute=0)
    scheduler.start()
    return scheduler


def stop_scheduler(scheduler):
    """Stop the scheduler gracefully."""
    logger.info("Stopping scheduler...")
    scheduler.shutdown(wait=False)


# Pronunciation Logic
async def start_pronounce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Start pronunciation session """
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_pronounce")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("🔊 Iltimos, so‘z kiriting:", reply_markup=reply_markup)
    return PRONOUNCE


async def pronounce_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Pronounces a Korean word using gTTS """
    text = update.message.text.replace("/speak", "").strip()

    if not text:
        await update.message.reply_text("⚠️ Iltimos, talaffuz qilinadigan soʻzni kiriting!")
        return PRONOUNCE

    # Generate speech
    tts = gTTS(text=text + ".", lang='ko')
    temp_file = tempfile.NamedTemporaryFile(delete=True, suffix=".mp3")
    tts.save(temp_file.name)

    # Send audio
    with open(temp_file.name, "rb") as audio:
        await update.effective_message.reply_voice(audio)

    temp_file.close()

    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_pronounce")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("🔊 Yana bir so‘z kiriting yoki '❌ Bekor qilish' tugmasini bosing.",
                                    reply_markup=reply_markup)
    return PRONOUNCE


async def cancel_pronounce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Exit pronunciation session """
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Talaffuz sessiyasi tugatildi.")
    return ConversationHandler.END


# User progress
async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Display user progress """
    user_id = update.message.chat_id
    words_added, words_reviewed, correct_answers, accuracy = database.get_user_progress(user_id)

    progress_text = (
        f"📊 **Your Progress:**\n"
        f"- **Words Added:** {words_added}\n"
        f"- **Words Reviewed:** {words_reviewed}\n"
        f"- **Correct Answers:** {correct_answers}\n"
        f"- **Accuracy:** {accuracy}%"
    )

    await update.message.reply_text(progress_text, parse_mode="Markdown")


# Grammar Logic
async def show_grammar_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display a message indicating that the Grammar feature is under development."""
    await update.message.reply_text("📖 Grammar bo‘limi hozirda ishlab chiqilmoqda. Tez orada foydalanishingiz mumkin bo‘ladi!")

# async def show_grammar_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Display grammar levels."""
#     keyboard = [
#         [InlineKeyboardButton("🟢 Beginner", callback_data="grammar_beginner")],
#         [InlineKeyboardButton("🟡 Intermediate", callback_data="grammar_intermediate")],
#         [InlineKeyboardButton("🔴 Advanced", callback_data="grammar_advanced")],
#     ]
#     reply_markup = InlineKeyboardMarkup(keyboard)
#     await update.message.reply_text("📖 Choose a grammar level:", reply_markup=reply_markup)


async def show_grammar_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of grammar rules for the selected level."""
    query = update.callback_query
    level_map = {
        "grammar_beginner": "Beginner",
        "grammar_intermediate": "Intermediate",
        "grammar_advanced": "Advanced",
    }
    level = level_map.get(query.data)

    if not level:
        return

    # Store the selected level
    context.user_data["grammar_level"] = level

    # Initialize page number if not set
    if "grammar_page" not in context.user_data:
        context.user_data["grammar_page"] = 0

    await update_grammar_page(query, context)


async def update_grammar_page(query, context):
    """Update the grammar rule list with pagination."""
    level = context.user_data.get("grammar_level")
    page = context.user_data.get("grammar_page", 0)
    rules = database.get_grammar_rules_by_level(level)  # Fetch all rules

    if not rules:
        await query.edit_message_text(f"🚧 No grammar rules found for {level} level.")
        return

    rules_per_page = 10  # Number of rules per page
    paginated_rules, total_pages = paginate_items(rules, page, rules_per_page)

    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"grammar_rule_{rule_id}")]
        for rule_id, title in paginated_rules
    ]

    # Add "⬅ Orqaga" and "Oldinga ➡" buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Orqaga", callback_data="grammar_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Oldinga ➡️", callback_data="grammar_next"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(f"📚 {level} Grammar Rules (Page {page + 1}/{total_pages}):",
                                      reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to update grammar page: {e}")


async def show_grammar_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display a selected grammar rule explanation."""
    query = update.callback_query
    rule_id = query.data.replace("grammar_rule_", "")

    try:
        rule = database.get_grammar_rule(rule_id)
        if not rule:
            await query.edit_message_text("⚠️ This grammar rule is not available.")
            return

        title, explanation, examples = rule
        example_text = "\n".join([f"🔹 {ex}" for ex in examples])

        response = f"📖 **{title}**\n\n{explanation}\n\n**Examples:**\n{example_text}"
        await query.edit_message_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error fetching grammar rule {rule_id}: {e}")
        await query.edit_message_text("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.")


async def handle_grammar_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle '⬅ Orqaga' and 'Oldinga ➡' buttons."""
    query = update.callback_query
    action = query.data

    logger.info(f"Handling grammar pagination action: {action}")

    await query.answer()

    # Get current page and total rules
    current_page = context.user_data.get("grammar_page", 0)
    level = context.user_data.get("grammar_level")
    rules = database.get_grammar_rules_by_level(level)
    rules_per_page = 10
    total_pages = (len(rules) - 1) // rules_per_page + 1

    # Update page number based on action
    if action == "grammar_prev":
        new_page = max(0, current_page - 1)
    elif action == "grammar_next":
        new_page = min(total_pages - 1, current_page + 1)
    else:
        new_page = current_page

    logger.info(f"Current page: {current_page}, New page: {new_page}, Total pages: {total_pages}")

    # Update context with the new page
    context.user_data["grammar_page"] = new_page

    # Call the update function to refresh the grammar page
    await update_grammar_page(query, context)


def paginate_items(items, page, items_per_page):
    """Paginate a list of items."""
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    total_pages = (len(items) - 1) // items_per_page + 1
    return items[start_idx:end_idx], total_pages


async def start_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Start feedback session """
    logger.info(f"User {update.effective_user.id} triggered /feedback")
    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_feedback")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("📝 Iltimos, fikr-mulohazangizni kiriting:\n\n"
                                    "❌ Bekor qilish uchun /cancel buyrug‘ini yuboring.",
                                    reply_markup=reply_markup)
    return FEEDBACK


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Handle feedback submission """
    user_id = update.message.from_user.id
    username = update.message.from_user.username or f"User_{user_id}"
    feedback = update.message.text.strip()

    # Notify the admin
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")  # Set your admin chat ID in the environment variables
    if admin_chat_id:
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"📩 Yangi fikr-mulohaza:\n\n"
                 f"👤 @{username} (ID: {user_id})\n"
                 f"📝 {feedback}"
    )

    await update.message.reply_text("✅ Fikringiz uchun rahmat! Sizning fikringiz biz uchun muhim.")
    return ConversationHandler.END


async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Exit feedback session """
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Fikr-mulohaza sessiyasi tugatildi.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    scheduler = start_scheduler(app)

    # Handle shutdown signals
    signal.signal(signal.SIGINT, lambda sig, frame: stop_scheduler(scheduler))
    signal.signal(signal.SIGTERM, lambda sig, frame: stop_scheduler(scheduler))

    # Handlers
    conv_handler_pronounce = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎧 Talaffuz"), handle_buttons)],
        states={
            PRONOUNCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pronounce_word),
                CallbackQueryHandler(cancel_pronounce, pattern="cancel_pronounce")
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_pronounce, pattern="cancel_pronounce")]
    )

    conv_handler_word = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ So'z qo'shish$"), handle_buttons)],
        states={
            ADD_WORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_word),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^(❌ Cancel|❌ Bekor qilish)$"), start)  # Handle cancel action
        ]
    )

    conv_handler_review_text = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📚 Takrorlash$"), handle_buttons)],
        states={
            REVIEW_TEXT: [CallbackQueryHandler(check_answer)],
        },
        fallbacks=[CommandHandler("start", start)]

    )

    conv_handler_feedback = ConversationHandler(
        entry_points=[CommandHandler("feedback", start_feedback)],
        states={
            FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback),
                CallbackQueryHandler(cancel_feedback, pattern="^cancel_feedback$")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_feedback)
        ]
)


    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler_pronounce)
    app.add_handler(conv_handler_word)
    app.add_handler(conv_handler_review_text)
    app.add_handler(conv_handler_feedback)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    # app.add_handler(CommandHandler("grammar", show_grammar_levels))
    # app.add_handler(CallbackQueryHandler(show_grammar_rules, pattern="^grammar_"))
    # app.add_handler(CallbackQueryHandler(handle_grammar_pagination, pattern="^grammar_(prev|next)$"))
    # app.add_handler(CallbackQueryHandler(show_grammar_explanation, pattern="^grammar_rule_"))
    # app.add_handler(CallbackQueryHandler(cancel_add_word, pattern="cancel_add_word"))

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"An error occurred while running the bot: {e}", exc_info=True)
