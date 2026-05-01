# user_handlers.py (исправленный)
import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import aiosqlite

from config import ADMIN_IDS, REQUIRED_CHANNEL
from db import (
    register_user, has_accepted_terms, accept_terms, get_user,
    get_operator_price, create_submission, get_setting, set_setting,
    add_crypto_balance, get_operators, count_active_bookings_for_operator,
    get_user_qr_last_30_days, get_active_booking, cancel_booking,
    create_booking, get_user_stats, get_operator_top_regions,
    get_operator_conditions, get_referral_percent, get_referral_stats,
    DATABASE, update_user_earnings, get_user_role
)
from states import SubmitEsim
from utils import (
    validate_phone, normalize_phone, calculate_rank,
    calculate_volume_points, calculate_regularity_points, calculate_priority
)
from keyboards.user_keyboards import (
    main_menu, profile_keyboard, booking_menu, back_button,
    subscription_check_button, get_accept_terms_keyboard
)

router = Router()

TERMS_TEXT = """📄 **Условия работы:**

• Формат сдачи: одним сообщением — QR‑код + номер телефона в формате "79999999999" для каждой eSIM.

• Критерии: оплаченный тариф (минимум 100 минут) и рабочий QR‑код, залитые QR в несколько приёмок не оплачиваем.

• Выплаты: ежедневно, день в день, после 17:00-19:00 (МСК).

• Wi‑Fi‑звонки не требуются! Не сканируйте QR‑код своим устройством - часто он одноразовый, ничего включать не нужно.

⚠ Условия могут меняться без уведомления.
Без принятия условий доступ к функционалу закрыт."""

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
        except:
            pass
    user = message.from_user
    await register_user(user.id, user.username, user.full_name, referrer_id)

    role = await get_user_role(user.id)
    is_admin = user.id in ADMIN_IDS
    if await has_accepted_terms(user.id):
        await message.answer("✅ Вы уже приняли условия.", reply_markup=main_menu(is_admin, role == 'worker'))
    else:
        await message.answer(TERMS_TEXT, parse_mode="Markdown", reply_markup=get_accept_terms_keyboard())

@router.callback_query(F.data == "accept_terms")
async def accept_terms_callback(callback: CallbackQuery):
    await accept_terms(callback.from_user.id)
    await callback.answer("Условия приняты!")
    if REQUIRED_CHANNEL:
        text = f"✅ Условия приняты!\n\nТеперь подпишитесь на наш канал: {REQUIRED_CHANNEL}\n\nНажмите кнопку ниже после подписки."
        await callback.message.edit_text(text, reply_markup=subscription_check_button())
    else:
        await callback.message.delete()
        role = await get_user_role(callback.from_user.id)
        await callback.message.answer("🎉 Добро пожаловать!", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    if not REQUIRED_CHANNEL:
        await callback.message.delete()
        role = await get_user_role(callback.from_user.id)
        await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))
        return
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, callback.from_user.id)
        if member.status in ("left", "kicked"):
            await callback.answer("❌ Вы не подписаны на канал. Подпишитесь и нажмите снова.", show_alert=True)
        else:
            await callback.answer("✅ Подписка подтверждена!")
            await callback.message.delete()
            role = await get_user_role(callback.from_user.id)
            await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))
    except Exception as e:
        logging.error(f"Check subscription error: {e}")
        await callback.answer("⚠️ Ошибка проверки подписки. Попробуйте позже.", show_alert=True)

# ---------- Сдать ESIM ----------
@router.message(F.text == "📱 Сдать ESIM")
async def cmd_sell_esim(message: Message):
    mode = await get_setting("sale_mode", "hold")
    operators = await get_operators()

    async with aiosqlite.connect(DATABASE) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT operator, COUNT(*) as cnt 
            FROM qr_submissions 
            WHERE status = 'accepted' AND submitted_at >= datetime('now', '-30 days')
            GROUP BY operator 
            ORDER BY cnt DESC LIMIT 1
        """)
        row = await cur.fetchone()
        most_taken = row['operator'] if row else "нет данных"

        low_stock = []
        for op in operators:
            if op['slot_limit'] != -1:
                used = await count_active_bookings_for_operator(op['name'])
                free = op['slot_limit'] - used
                if free <= 2:
                    low_stock.append(op['name'])
        low_stock_text = ", ".join(low_stock) if low_stock else "все слоты свободны"

    mode_text = "БХ 🟢 (мгновенное начисление)" if mode == "bh" else "ХОЛД 🔴 (начисление через 30 минут)"
    mode_short = "БХ 🟢" if mode == "bh" else "ХОЛД 🔴"

    operators_text = ""
    for op in operators:
        price = op['price_bh'] if mode == 'bh' else op['price_hold']
        marker = "🟢" if (op['name'] in low_stock or op['name'] == most_taken) else ""
        operators_text += f"{op['name']} - {price}$ {marker}\n"

    text = (
        f"📱 **Сдать ESIM**\n\n"
        f"Режим сдачи: {mode_text}\n\n"
        f"🔥 Больше всего взято: {most_taken}\n"
        f"⚠️ Минимальный остаток: {low_stock_text}\n\n"
        f"**Операторы и цены:**\n{operators_text}\n"
        f"Для смены режима нажмите кнопку ниже."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Режим сдачи: {mode_short}", callback_data="toggle_mode_from_sell")],
        *[[InlineKeyboardButton(text=f"{op['name']} - {op['price_bh'] if mode == 'bh' else op['price_hold']}$",
                                callback_data=f"select_operator:{op['name']}")] for op in operators],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "toggle_mode_from_sell")
async def toggle_mode_from_sell(callback: CallbackQuery):
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    await set_setting("sale_mode", new_mode)
    await cmd_sell_esim(callback.message)
    await callback.answer(f"Режим изменён на {'БХ' if new_mode == 'bh' else 'ХОЛД'}")

@router.callback_query(F.data.startswith("select_operator:"))
async def select_operator(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    mode = await get_setting("sale_mode", "hold")
    price = await get_operator_price(operator, mode)
    if price is None:
        await callback.answer("Ошибка: оператор не найден")
        return
    await state.update_data(operator=operator, price=price)
    await state.set_state(SubmitEsim.waiting_for_photo_and_phone)
    await callback.message.delete()
    await callback.message.answer(
        f"📱 Оператор: {operator}\n💰 Стоимость: {price}$ + бонус ранга.\n\n"
        "Отправьте **фото QR-кода** и **номер телефона** в подписи (пример: +79001234567).\n\n"
        "❗ Важно: фото и номер в одном сообщении.\n\nДля отмены нажмите ❌ Стоп"
    )
    await callback.answer()

@router.message(SubmitEsim.waiting_for_photo_and_phone, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    if not message.caption:
        await message.answer("❌ Добавьте номер телефона в подпись к фото.")
        return
    phone = message.caption.strip()
    if not validate_phone(phone):
        await message.answer("❌ Неверный номер. Нужно 11 цифр, начинается с 7. Пример: +79001234567")
        return
    phone = normalize_phone(phone)
    region = phone[:3] if len(phone) >= 3 else ""
    data = await state.get_data()
    operator = data['operator']
    price = data['price']
    user_id = message.from_user.id
    photo_file_id = message.photo[-1].file_id

    mode = await get_setting("sale_mode", "hold")
    if mode == "hold":
        async with aiosqlite.connect(DATABASE) as conn:
            async with conn.execute(
                "SELECT id FROM qr_submissions WHERE operator = ? AND phone = ? AND submitted_at >= datetime('now', '-30 minutes')",
                (operator, phone)
            ) as cur:
                if await cur.fetchone():
                    await message.answer("❌ Этот QR уже сдан недавно (режим ХОЛД). Подождите 30 минут.")
                    await state.clear()
                    return

    submission_id = await create_submission(user_id, operator, price, phone, photo_file_id, region)
    await message.answer("✅ QR принят на проверку. Ожидайте решения админа.", reply_markup=main_menu(user_id in ADMIN_IDS, (await get_user_role(user_id)) == 'worker'))
    await state.clear()

    user = await get_user(user_id)
    username = user['username'] or str(user_id)
    qr_count_30d, _ = await get_user_qr_last_30_days(user_id)
    _, bonus = calculate_rank(qr_count_30d)
    text = (
        f"🆕 Новая сдача eSIM\n"
        f"👤 Пользователь: @{username} (ID {user_id})\n"
        f"📱 Оператор: {operator}\n"
        f"💰 Стоимость: {price}$ + бонус {bonus}$\n"
        f"📞 Номер: {phone}\n"
        f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"ID заявки: {submission_id}"
    )
    from keyboards.admin_keyboards import pending_actions
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_photo(admin, photo_file_id, caption=text, reply_markup=pending_actions(submission_id))
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin}: {e}")

@router.message(SubmitEsim.waiting_for_photo_and_phone)
async def incorrect_input(message: Message, state: FSMContext):
    if message.text and "Стоп" in message.text:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu(...))
        return
    await message.answer("❌ Пожалуйста, отправьте **фото** с подписью-номером...")

@router.message(F.text == "❌ Стоп")
async def stop_action(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        role = await get_user_role(message.from_user.id)
        await message.answer(
            "✅ Действие отменено. Возврат в главное меню.",
            reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker')
        )
    else:
        role = await get_user_role(message.from_user.id)
        await message.answer(
            "🤷‍♂️ Нет активного действия для отмены.",
            reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker')
        )

# ---------- Профиль ----------
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return

    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user['user_id'])
    rank_name, bonus = calculate_rank(qr_count_30d)

    async with aiosqlite.connect(DATABASE) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM qr_submissions WHERE user_id = ? AND status='accepted' AND date(submitted_at) = date('now')",
            (user['user_id'],)
        )
        qr_today = (await cur.fetchone())[0] or 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    stats_1d = await get_user_stats(user['user_id'], 1)
    stats_7d = await get_user_stats(user['user_id'], 7)
    stats_30d = await get_user_stats(user['user_id'], 30)
    stats_total = await get_user_stats(user['user_id'], None)

    def fmt(stats):
        accepted = stats.get('accepted') or 0
        blocked = stats.get('blocked') or 0
        noscan = stats.get('noscan') or 0
        sum_earned = stats.get('sum_earned') or 0
        return (f"✅ {accepted if accepted else 'пусто'} "
                f"❌ {blocked if blocked else 'пусто'} "
                f"🔥 {noscan if noscan else 'пусто'} "
                f"💰 {f'{sum_earned:.2f}$' if sum_earned else 'пусто'}")

    text = (
        f"👤 Профиль @{user['username']} · ID {user['user_id']}\n"
        f"🏆 Ранг: {rank_name}\n"
        f"💰 Бонус: +{bonus}$ к QR\n"
        f"📊 Зачтено за месяц: {qr_count_30d}\n"
        f"🔥 Приоритет: {priority:.1f} · {rank_name}\n"
        f"💵 Ожидаемая выплата за сегодня: {user['earned_today']:.2f}$\n"
        f"💰 Крипто-баланс: {user['crypto_balance']:.2f}$\n"
        f"🕒 Всего заработано: {user['total_earned']:.2f}$\n"
        f"👥 Реферальный бонус: {user['referral_earnings']:.2f}$\n\n"
        f"📊 **Статистика по периодам:**\n"
        f"1 день: {fmt(stats_1d)}\n"
        f"7 дней: {fmt(stats_7d)}\n"
        f"30 дней: {fmt(stats_30d)}\n"
        f"Всего: {fmt(stats_total)}"
    )
    await message.answer(text, reply_markup=profile_keyboard())


# ---------- Полезное ----------
@router.callback_query(F.data == "useful")
async def useful_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="stats_detailed")],
        [InlineKeyboardButton(text="📞 Операторы", callback_data="operators_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text("📚 **Полезное** – выберите раздел:", parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "faq")
async def faq_section(callback: CallbackQuery):
    text = (
        "**FAQ – Часто задаваемые вопросы**\n\n"
        "• **Актуальный прайс (за каждую отдельную eSIM с холодом 30м)**\n"
        "  - МТС (включая салон) — 18$ (бесход - 14$ за eSIM)\n"
        "  - Сбер — 12$ (бесход - 10$ за eSIM)\n"
        "  - Билайн — 15$ (бесход - 12$ за eSIM)\n"
        "  - Т2 — 14$ (бесход - 10$ за eSIM)\n"
        "  - ВТБ — 25$ (неоплаченный 20$)\n"
        "  - Газпром — 28$ (неоплаченный 23$)\n"
        "  - Тинькофф — 14$\n"
        "  - Мегафон — 14$\n"
        "  - Миранда — 11$\n"
        "  - Волна / 7телеком — 12$\n"
        "  - Йота — 14$\n\n"
        "• **Мануалы по регистрации**:\n"
        "  [SberMobile](https://t.me/c/3751926773/3/18)\n"
        "  [BeeLine](https://t.me/c/3751926773/3/19)\n"
        "  [MTS](https://t.me/c/3751926773/3/20)\n\n"
        "⚠️ Ссылки работают только при подписке на [HITORO HUB](https://t.me/+76Z8pTDcnE85YWU0)\n\n"
        "📞 **По всем вопросам:** @hitorowork"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "stats_detailed")
async def detailed_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    periods = [(1, "1 день"), (7, "7 дней"), (30, "30 дней"), (None, "все время")]
    text = "📊 **Статистика по отчётным дням**\n\n"
    for days, label in periods:
        stats = await get_user_stats(user_id, days)
        # Заменяем 0 на "пусто"
        s_total = stats['total'] if stats['total'] > 0 else "пусто"
        s_blocked = stats['blocked'] if stats['blocked'] > 0 else "пусто"
        s_noscan = stats['noscan'] if stats['noscan'] > 0 else "пусто"
        s_sum = f"{stats['sum_earned']:.2f}$" if stats['sum_earned'] > 0 else "пусто"
        text += f"• **{label}**\n"
        text += f"  ✅ Сдано: {s_total}\n"
        text += f"  🚫 Блоки: {s_blocked}\n"
        text += f"  🔥 Несканы: {s_noscan}\n"
        text += f"  💰 Сумма: {s_sum}\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "operators_list")
async def operators_list(callback: CallbackQuery):
    ops = await get_operators()
    kb = []
    for op in ops:
        kb.append([InlineKeyboardButton(text=op['name'], callback_data=f"operator_stats:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="useful")])
    await callback.message.edit_text("Выберите оператора для просмотра статистики:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("operator_stats:"))
async def operator_stats(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    # Топ-5 регионов за неделю
    top_regions = await get_operator_top_regions(operator, 7)
    conditions = await get_operator_conditions(operator)
    reg_text = "\n".join([f"{r['region_name']} — {r['cnt']} шт." for r in top_regions]) if top_regions else "Нет данных"
    text = (
        f"📡 **Оператор: {operator}**\n\n"
        f"**ТОП-5 лучших регионов (за неделю):**\n{reg_text}\n\n"
        f"**Условия по оператору:**\n"
        f"Минимум {conditions.get('min_minutes', 50)} минут звонков по РФ либо равносильный баланс.\n"
        f"{conditions.get('conditions', '')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К списку", callback_data="operators_list")],
        [InlineKeyboardButton(text="🏠 В профиль", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

# ---------- Мои номера, рефералы, история ----------
@router.callback_query(F.data == "my_numbers")
async def show_my_numbers(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DATABASE) as conn:
        async with conn.execute(
            "SELECT DISTINCT phone FROM qr_submissions WHERE user_id = ? ORDER BY submitted_at DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await callback.answer("У вас нет сохранённых номеров.", show_alert=True)
        return
    numbers = [row[0] for row in rows]
    text = "📞 Ваши номера:\n" + "\n".join(f"+{num}" for num in numbers)
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "ref_system")
async def ref_system_callback(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start")
        return
    ref_percent = await get_referral_percent(user['user_id'])
    ref_stats = await get_referral_stats(user['user_id'])
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    text = (
        f"🌟 **Реферальная программа**\n\n"
        f"Ваша ссылка: {link}\n\n"
        f"👥 Приглашено пользователей: {ref_stats['count']}\n"
        f"💰 Заработано с рефералов: ${user['referral_earnings']:.2f}\n"
        f"📈 Текущий процент бонуса: {ref_percent}% от дохода рефералов\n\n"
        f"**Как растёт процент?**\n"
        f"0–20 QR рефералов → 0%\n"
        f"21–40 → 1%\n"
        f"41–60 → 2%\n"
        f"61–100 → 3%\n"
        f"101–199 → 3.5%\n"
        f"200+ → 4%\n\n"
        f"Запрос на вывод доступен от $10."
    )
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "my_bot")
async def my_bot_callback(callback: CallbackQuery):
    text = (
        "🤖 **Мой бот**\n\n"
        "Подключите **своего Telegram-бота** для приёма номеров.\n\n"
        "Это нужно для двух вещей:\n"
        "- **Безопасность** – если основной бот временно заблокируют, вы продолжите работать через личного.\n"
        "- **Стабильность** – личный бот отвечает быстрее и без задержек.\n\n"
        "**Как подключить?**\n"
        "1. Напишите [@BotFather](https://t.me/botfather) и создайте нового бота командой /newbot.\n"
        "2. Скопируйте токен.\n"
        "3. Пришлите токен сюда командой: `/deploy <токен>`\n"
        "4. Администратор получит уведомление и свяжется с вами.\n\n"
        "⚠️ Подключение – одним токеном, полная инструкция внутри раздела."
    )
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DATABASE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT operator, price, status, submitted_at, earned_amount, reject_reason
            FROM qr_submissions
            WHERE user_id = ?
            ORDER BY submitted_at DESC
            LIMIT 10
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
    if not rows:
        await callback.answer("Нет сдач", show_alert=True)
        return
    text = "📜 **Последние 10 сдач**\n\n"
    for row in rows:
        status_emoji = "✅" if row['status'] == "accepted" else "⏳" if row['status'] == "pending" else "❌"
        reason_text = ""
        if row['status'] == "rejected" and row['reject_reason']:
            reason_text = f" ({'блок' if row['reject_reason']=='block' else 'нескан'})"
        earned = row['earned_amount'] or 0
        dt = row['submitted_at'][:16]
        text += f"{status_emoji} {row['operator']} - {row['price']}$ | {dt} | +{earned}$ {reason_text}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def back_menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS))

# ---------- Бронирование (как в предыдущей версии) ----------
@router.message(F.text == "📅 Бронирование")
async def cmd_booking(message: Message):
    active = await get_active_booking(message.from_user.id)
    if active:
        text = f"📌 Активная бронь: {active['operator']}\n{active['created_at']}"
        await message.answer(text, reply_markup=booking_menu(True))
    else:
        await message.answer("Нет активной брони.", reply_markup=booking_menu(False))

@router.callback_query(F.data == "book_operator")
async def book_operator_list(callback: CallbackQuery):
    operators = await get_operators()
    available = []
    for op in operators:
        limit = op['slot_limit']
        if limit == -1:
            free = "∞"
            available.append({"name": op['name'], "free_slots": free})
        else:
            used = await count_active_bookings_for_operator(op['name'])
            free_slots = limit - used
            if free_slots > 0:
                available.append({"name": op['name'], "free_slots": free_slots})
    if not available:
        await callback.answer("Нет свободных слотов для бронирования.", show_alert=True)
        return
    from keyboards.user_keyboards import operators_for_booking
    await callback.message.edit_text("Выберите оператора для бронирования:", reply_markup=operators_for_booking(available))
    await callback.answer()

@router.callback_query(F.data.startswith("book:"))
async def create_booking_callback(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    user_id = callback.from_user.id
    existing = await get_active_booking(user_id)
    if existing:
        await callback.answer("У вас уже есть активная бронь. Отмените её сначала.", show_alert=True)
        return
    op_list = await get_operators()
    op_data = next((op for op in op_list if op['name'] == operator), None)
    if op_data:
        if op_data['slot_limit'] != -1:
            used = await count_active_bookings_for_operator(operator)
            if used >= op_data['slot_limit']:
                await callback.answer("Все слоты заняты.", show_alert=True)
                return
    await create_booking(user_id, operator)
    await callback.message.edit_text(f"✅ Вы забронировали {operator}. Бронь сгорит после сдачи eSIM.", reply_markup=booking_menu(True))
    await callback.answer()

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    booking = await get_active_booking(user_id)
    if not booking:
        await callback.answer("У вас нет активной брони.", show_alert=True)
        return
    await cancel_booking(booking['id'])
    await callback.message.edit_text("Бронь отменена.", reply_markup=booking_menu(False))
    await callback.answer()

@router.callback_query(F.data == "edit_booking")
async def edit_booking_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    booking = await get_active_booking(user_id)
    if booking:
        await cancel_booking(booking['id'])
    await book_operator_list(callback)

# ---------- Бонусы ----------
@router.message(F.text == "🎁 Бонусы")
async def cmd_bonuses(message: Message):
    user_id = message.from_user.id
    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user_id)
    rank_name, bonus = calculate_rank(qr_count_30d)

    async with aiosqlite.connect(DATABASE) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM qr_submissions WHERE user_id = ? AND status='accepted' AND date(submitted_at) = date('now')",
            (user_id,)
        )
        qr_today = (await cur.fetchone())[0] or 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    text = (
        f"🎁 **Бонусная система**\n\n"
        f"📈 Ранг: {qr_count_30d} / 30 (Профи), /60 (Элита)\n"
        f"🏆 {rank_name} +${bonus}/QR\n"
        f"⭐ Объём: {volume_points}/5 (сегодня {qr_today} QR)\n"
        f"⭐ Регулярность: {regularity_points}/4 ({len(unique_dates)} дней)\n"
        f"🔥 Приоритет: {priority:.1f} / 7\n\n"
        f"**Ранги:**\n"
        f"• Старт (0–29 QR) → +$0/QR\n"
        f"• Профи (30–59 QR) → +$0.5/QR\n"
        f"• Элита (60+ QR) → +$1/QR\n\n"
        f"Приоритет = объём + регулярность (до 7 баллов).\n"
        f"Чем выше приоритет – тем быстрее вам достаются слоты."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=back_button())

# ---------- Рефералы из главного меню ----------
@router.message(F.text == "👥 Рефералы")
async def referral_button(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return
    ref_percent = await get_referral_percent(user['user_id'])
    ref_stats = await get_referral_stats(user['user_id'])
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    text = (
        f"🌟 Реферальная программа\n\n"
        f"Ваша ссылка: {link}\n\n"
        f"👥 Приглашено: {ref_stats['count']}\n"
        f"💰 Заработано: {user['referral_earnings']:.2f}$\n"
        f"📈 Текущий процент бонуса: {ref_percent}%\n\n"
        f"Шкала:\n"
        f"0–20 QR → 0%\n21–40 → 1%\n41–60 → 2%\n61–100 → 3%\n101–199 → 3.5%\n200+ → 4%\n\n"
        f"Запрос на вывод от $10."
    )
    await message.answer(text, reply_markup=back_button())   # убрали parse_mode

# ---------- Мой бот из главного меню ----------
@router.message(F.text == "🤖 Мой бот")
async def my_bot_button(message: Message):
    text = (
        "🤖 **Мой бот**\n\n"
        "Подключите своего Telegram-бота для приёма номеров.\n\n"
        "**Зачем это нужно?**\n"
        "• **Безопасность** – если основной бот заблокируют, вы продолжите через личного.\n"
        "• **Стабильность** – личный бот отвечает быстрее.\n\n"
        "**Инструкция:**\n"
        "1. Создайте бота у [@BotFather](https://t.me/botfather) (команда /newbot).\n"
        "2. Скопируйте токен.\n"
        "3. Отправьте его этой командой: `/deploy <токен>`\n"
        "4. Администратор получит уведомление и свяжется с вами для завершения настройки.\n\n"
        "⚠️ Подключение – бесплатно, одним токеном."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=back_button())

@router.message(Command("deploy"))
async def deploy_command(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /deploy <токен_бота>")
        return
    token = args[1]
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"🚀 Запрос на развёртывание бота от @{message.from_user.username} (ID {message.from_user.id})\nТокен: {token}")
    await message.answer("✅ Запрос отправлен администратору. Ожидайте.")

# ---------- Крипто-выплаты ----------
@router.message(Command("pay"))
async def pay_earnings(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала /start")
        return
    if user['earned_today'] <= 0:
        await message.answer("Нет средств для перевода.")
        return
    amount = user['earned_today']
    await add_crypto_balance(user_id, amount)
    async with aiosqlite.connect(DATABASE) as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = ?", (user_id,))
        await conn.commit()
    await message.answer(f"✅ {amount:.2f}$ переведены в крипто-баланс. Для вывода используйте /withdraw")

@router.message(F.text == "📋 Мои заявки")
async def my_tasks(message: Message):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role != 'worker' and user_id not in ADMIN_IDS:
        await message.answer("Эта функция только для работников.")
        return
    # Получаем заявки, которые взял этот работник и которые ещё не завершены (status 'taken')
    async with aiosqlite.connect(DATABASE) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT id, operator, phone, submitted_at, taken_at
            FROM qr_submissions
            WHERE taken_by = ? AND status = 'taken'
            ORDER BY taken_at DESC
        """, (user_id,))
        rows = await cur.fetchall()
    if not rows:
        await message.answer("У вас нет активных заявок в работе.")
        return
    text = "📋 Ваши активные заявки:\n\n"
    for row in rows:
        text += f"ID {row['id']} | {row['operator']} | +{row['phone']} | взято: {row['taken_at']}\n"
    await message.answer(text, reply_markup=back_button())

@router.message(F.text == "❌ Стоп")
async def stop_action(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("✅ Действие отменено. Возврат в главное меню.",
                             reply_markup=main_menu(message.from_user.id in ADMIN_IDS,
                                                    await get_user_role(message.from_user.id) == 'worker'))
    else:
        await message.answer("🤷‍♂️ Нет активного действия для отмены.",
                             reply_markup=main_menu(message.from_user.id in ADMIN_IDS,
                                                    await get_user_role(message.from_user.id) == 'worker'))

@router.message(F.text == "📋 Мои заявки")
async def my_tasks(message: Message):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role not in ('admin', 'worker'):
        await message.answer("Эта функция только для работников и администраторов.")
        return
    async with aiosqlite.connect(DATABASE) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT id, operator, phone, submitted_at, taken_at
            FROM qr_submissions
            WHERE taken_by = ? AND status = 'taken'
            ORDER BY taken_at DESC
        """, (user_id,))
        rows = await cur.fetchall()
    if not rows:
        await message.answer("У вас нет активных заявок в работе.", reply_markup=back_button())
        return
    text = "📋 Ваши активные заявки:\n\n"
    for row in rows:
        text += (f"ID {row['id']} | {row['operator']} | +{row['phone']}\n"
                 f"   взято: {row['taken_at']}\n")
    await message.answer(text, reply_markup=back_button())

@router.message(F.text == "❌ Стоп")
async def stop_action(message: Message, state: FSMContext):
    print("Обработчик ❌ Стоп вызван")  # для отладки
    current_state = await state.get_state()
    if current_state:
        await state.clear()

@router.message(Command("withdraw"))
async def withdraw_cmd(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /withdraw <сумма>")
        return
    try:
        amount = float(args[1])
    except:
        await message.answer("Неверная сумма")
        return
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала /start")
        return
    if user['crypto_balance'] < amount:
        await message.answer("❌ Недостаточно средств на крипто-балансе.")
        return
    async with aiosqlite.connect(DATABASE) as conn:
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance - ? WHERE user_id = ?", (amount, user_id))
        await conn.commit()
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"💰 Запрос вывода: @{message.from_user.username} (ID {user_id}) на сумму {amount}$")
    await message.answer(f"✅ Запрос на вывод {amount}$ отправлен администратору.")