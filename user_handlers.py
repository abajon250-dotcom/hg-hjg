import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta

from config import ADMIN_IDS, REQUIRED_CHANNEL
from db import (
    register_user, has_accepted_terms, accept_terms, get_user,
    get_operator_price, create_submission, get_setting, set_setting,
    add_crypto_balance, get_operators, count_active_bookings_for_operator,
    get_user_qr_last_30_days, get_active_booking, cancel_booking,
    create_booking, get_user_stats, get_operator_top_regions,
    get_operator_conditions, get_referral_percent, get_referral_stats,
    get_user_role, get_most_popular_operator, get_low_stock_operators,
    get_pool
)
from states import SubmitEsim
from utils import (
    validate_phone, normalize_phone, calculate_rank,
    calculate_volume_points, calculate_regularity_points, calculate_priority
)
from user_keyboards import (
    main_menu, profile_keyboard, booking_menu, back_button,
    subscription_check_button, get_accept_terms_keyboard, operators_for_booking
)
from admin_keyboards import pending_actions

router = Router()

TERMS_TEXT = """📄 **Условия работы:** ..."""  # опущено для краткости, но можно вставить полный текст

# ---------- Старт ----------
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
    most_taken = await get_most_popular_operator()
    low_stock = await get_low_stock_operators()

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
        f"⚠️ Минимальный остаток: {', '.join(low_stock) if low_stock else 'все слоты свободны'}\n\n"
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

# ---------- Приём фото ----------
@router.message(SubmitEsim.waiting_for_photo_and_phone, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    # ... (код без изменений, использует get_pool для проверки дубля)
    # см. предыдущий ответ
    pass

@router.message(SubmitEsim.waiting_for_photo_and_phone)
async def incorrect_input(message: Message):
    await message.answer("❌ Пожалуйста, отправьте **фото** с подписью-номером. Для отмены нажмите ❌ Стоп")

@router.message(F.text == "❌ Стоп")
async def stop_action(message: Message, state: FSMContext):
    current_state = await state.get_state()
    role = await get_user_role(message.from_user.id)
    if current_state:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker'))
    else:
        await message.answer("🤷‍♂️ Нет активного действия.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker'))

# ---------- Профиль ----------
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return

    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user['user_id'])
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        qr_today = await conn.fetchval("""
            SELECT COUNT(*) FROM qr_submissions
            WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE
        """, user['user_id']) or 0

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
        acc_str = str(accepted) if accepted else "пусто"
        blk_str = str(blocked) if blocked else "пусто"
        nsc_str = str(noscan) if noscan else "пусто"
        sum_str = f"{sum_earned:.2f}$" if sum_earned else "пусто"
        return f"✅ {acc_str} ❌ {blk_str} 🔥 {nsc_str} 💰 {sum_str}"

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
        "  - МТС (включая салон) — 14$ (бх - 8$ за eSIM)\n"
        "  - Сбер — 10$ (бх - 7$ за eSIM)\n"
        "  - Билайн — 13$ (бх - 9$ за eSIM)\n"
        "  - Т2 — 12$ (бх - 8$ за eSIM)\n"
        "  - ВТБ — 25$ (бх 18$)\n"
        "  - Газпром — 28$ (бх 21$)\n"
        "  - Тинькофф — 12$\n"
        "  - Мегафон — 11$\n"
        "  - Миранда — 12$\n"
        "  - Волна / 7телеком — 12$\n"
        "  - Йота — 14$\n\n"
        "• **Мануалы по регистрации:**\n"
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
        total = stats['total'] if stats['total'] else "пусто"
        blocked = stats['blocked'] if stats['blocked'] else "пусто"
        noscan = stats['noscan'] if stats['noscan'] else "пусто"
        sum_earned = stats['sum_earned'] if stats['sum_earned'] else 0
        sum_str = f"{sum_earned:.2f}$" if sum_earned else "пусто"
        text += f"• **{label}**\n"
        text += f"  ✅ Сдано: {total}\n"
        text += f"  🚫 Блоки: {blocked}\n"
        text += f"  🔥 Несканы: {noscan}\n"
        text += f"  💰 Сумма: {sum_str}\n\n"
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

@router.callback_query(F.data == "my_numbers")
async def show_my_numbers(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT phone FROM qr_submissions WHERE user_id = $1 ORDER BY submitted_at DESC", user_id)
    if not rows:
        await callback.answer("У вас нет сохранённых номеров.", show_alert=True)
        return
    numbers = [row['phone'] for row in rows]
    text = "📞 Ваши номера:\n" + "\n".join(f"+{num}" for num in numbers)
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT operator, price, status, submitted_at, earned_amount, reject_reason
            FROM qr_submissions
            WHERE user_id = $1
            ORDER BY submitted_at DESC
            LIMIT 10
        """, user_id)
    if not rows:
        await callback.answer("Нет сдач", show_alert=True)
        return
    text = "📜 **Последние 10 сдач**\n\n"
    for row in rows:
        status_emoji = "✅" if row['status'] == "accepted" else "⏳" if row['status'] == "pending" else "❌"
        reason = f" ({'блок' if row['reject_reason']=='block' else 'нескан'})" if row['status'] == 'rejected' and row['reject_reason'] else ""
        earned = row['earned_amount'] or 0
        dt = row['submitted_at'].strftime("%Y-%m-%d %H:%M")
        text += f"{status_emoji} {row['operator']} - {row['price']}$ | {dt} | +{earned}$ {reason}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

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
    if op_data and op_data['slot_limit'] != -1:
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

@router.message(F.text == "🎁 Бонусы")
async def cmd_bonuses(message: Message):
    user_id = message.from_user.id
    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user_id)
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        qr_today = await conn.fetchval("""
            SELECT COUNT(*) FROM qr_submissions
            WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE
        """, user_id) or 0

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
    await message.answer(text, reply_markup=back_button())

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
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", user_id)
    await message.answer(f"✅ {amount:.2f}$ переведены в крипто-баланс. Для вывода используйте /withdraw")

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
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance - $1 WHERE user_id = $2", amount, user_id)
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"💰 Запрос вывода: @{message.from_user.username} (ID {user_id}) на сумму {amount}$")
    await message.answer(f"✅ Запрос на вывод {amount}$ отправлен администратору.")

@router.callback_query(F.data == "ref_system")
async def ref_system_callback(callback: CallbackQuery):
    await referral_button(callback.message)
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def back_menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    role = await get_user_role(callback.from_user.id)
    await callback.message.answer("Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))