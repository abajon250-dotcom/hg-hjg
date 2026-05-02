import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from db import (
    get_pool, get_pending_submissions, get_operators,
    update_operator_prices, update_operator_slot_limit, get_setting, set_setting,
    get_today_stats, get_top_users, get_user, add_crypto_balance,
    reject_submission, get_submission, accept_submission_now,
    get_user_qr_last_30_days, accept_submission_from_hold, hold_submission,
    get_total_users_count, get_new_users_count
)
from states import AdminSetPrice, AdminSetSlot, BroadcastState
from utils import calculate_rank
from keyboards.admin_keyboards import (
    admin_main_menu, pending_actions, operators_price_edit,
    operators_slot_edit, mode_buttons, confirm_clear, payout_list,
    work_actions
)
from keyboards.user_keyboards import main_menu

router = Router()
hold_tasks = {}

async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ------------------------------------------------------------
# Главное меню и общие callback
# ------------------------------------------------------------
@router.message(F.text == "👑 Админ панель")
async def admin_panel_button(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет прав")
        return
    await message.answer("👑 Панель администратора", reply_markup=admin_main_menu())

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("👑 Панель администратора", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Непроверенные QR (использует get_pending_submissions)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_pending")
async def list_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current_mode = await get_setting("sale_mode", "hold")
    pending = await get_pending_submissions_by_mode(current_mode, 20)
    if not pending:
        await callback.message.edit_text(f"Нет непроверенных заявок в режиме {current_mode.upper()}.", reply_markup=admin_main_menu())
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await callback.message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))
    await callback.message.delete()
    await callback.answer()

# ------------------------------------------------------------
# Изменение цен (две цены: холд и БХ)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_prices")
async def edit_prices_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(
            text=f"{op['name']} (ХОЛД: {op['price_hold']}$, БХ: {op['price_bh']}$)",
            callback_data=f"edit_price:{op['name']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Выберите оператора для изменения цен:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_price:"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(edit_operator=operator)
    await state.set_state(AdminSetPrice.waiting_for_price)
    await callback.message.edit_text(f"Введите новые цены для {operator} в формате: цена_холд цена_бх\nПример: 15 12")
    await callback.answer()

@router.message(AdminSetPrice.waiting_for_price)
async def set_new_prices(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError
        price_hold = float(parts[0].replace(',', '.'))
        price_bh = float(parts[1].replace(',', '.'))
    except:
        await message.answer("❌ Неверный формат. Введите две цены через пробел, например: 15 12")
        return
    data = await state.get_data()
    operator = data['edit_operator']
    await update_operator_prices(operator, price_hold, price_bh)
    await message.answer(f"✅ Цены для {operator} обновлены:\nХОЛД: {price_hold}$, БХ: {price_bh}$")
    await state.clear()

# ------------------------------------------------------------
# Переключение режима ХОЛД/БХ
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_toggle_mode")
async def toggle_mode_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    await callback.message.edit_text(f"Текущий режим: {'ХОЛД' if current == 'hold' else 'БХ'}", reply_markup=mode_buttons(current))
    await callback.answer()

@router.callback_query(F.data == "toggle_mode_confirm")
async def toggle_mode(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    await set_setting("sale_mode", new_mode)
    await callback.message.edit_text(f"Режим изменён на: {'БХ' if new_mode == 'bh' else 'ХОЛД'}", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Управление слотами брони
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_slots")
async def slots_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    await callback.message.edit_text("Выберите оператора для установки лимита слотов:", reply_markup=operators_slot_edit(operators))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_slot:"))
async def start_edit_slot(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(slot_operator=operator)
    await state.set_state(AdminSetSlot.waiting_for_slot_limit)
    await callback.message.edit_text(f"Введите лимит слотов для {operator} (число, -1 безлимит, 0 недоступно):")
    await callback.answer()

@router.message(AdminSetSlot.waiting_for_slot_limit)
async def set_slot_limit(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        limit = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    operator = data['slot_operator']
    await update_operator_slot_limit(operator, limit)
    await message.answer(f"Лимит слотов для {operator} установлен: {limit if limit != -1 else 'безлимит'}")
    await state.clear()

# ------------------------------------------------------------
# Статистика (общая + пользователи)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    today_stats = await get_today_stats()
    top_users = await get_top_users(5)
    total_users = await get_total_users_count()
    new_today = await get_new_users_count(1)
    new_week = await get_new_users_count(7)
    text = (
        f"📊 **Статистика за сегодня:**\n"
        f"✅ Зачтено QR: {today_stats['total_qr']}\n"
        f"💰 Сумма: {today_stats['total_earned']:.2f}$\n\n"
        f"👥 **Пользователи:**\n"
        f"Всего: {total_users} | за сегодня: +{new_today} | за 7 дней: +{new_week}\n\n"
        f"🏆 **Топ-5 по общему заработку:**\n"
    )
    for i, u in enumerate(top_users, 1):
        user = await get_user(u['user_id'])
        name = f"@{user['username']}" if user and user['username'] else f"ID {u['user_id']}"
        text += f"{i}. {name} — {u['total_earned']:.2f}$\n"
    await callback.message.edit_text(text, reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Отдельная кнопка пользователей (опционально)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    total = await get_total_users_count()
    today = await get_new_users_count(1)
    week = await get_new_users_count(7)
    text = (
        f"👥 **Статистика пользователей**\n\n"
        f"📊 Всего зарегистрировано: {total}\n"
        f"✅ За сегодня: {today}\n"
        f"📆 За 7 дней: {week}"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Выплаты (без aiosqlite, через get_pool)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_payouts")
async def payouts_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, earned_today FROM users WHERE earned_today > 0")
        users = [{"user_id": r['user_id'], "username": r['username'], "earned_today": r['earned_today']} for r in rows]
    if not users:
        await callback.message.edit_text("Нет пользователей для выплаты сегодня.", reply_markup=admin_main_menu())
        return
    await callback.message.edit_text("💸 Пользователи к выплате:", reply_markup=payout_list(users))
    await callback.answer()

@router.callback_query(F.data.startswith("mark_paid:"))
async def mark_paid(callback: CallbackQuery):
    uid = int(callback.data.split(":")[1])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", uid)
    await callback.answer("Пользователь отмечен как выплаченный")
    await callback.message.delete()
    await callback.message.answer("Главное меню админа", reply_markup=admin_main_menu())

# ------------------------------------------------------------
# Очистка непроверенных (без aiosqlite)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_clear_pending")
async def confirm_clear(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("Вы уверены, что хотите удалить все непроверенные заявки?", reply_markup=confirm_clear())
    await callback.answer()

@router.callback_query(F.data == "confirm_clear_pending")
async def clear_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qr_submissions WHERE status = 'pending'")
    await callback.message.edit_text("Все непроверенные заявки удалены.", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Крипто-баланс
# ------------------------------------------------------------
@router.message(Command("add_crypto"))
async def add_crypto(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /add_crypto <user_id> <сумма>")
        return
    try:
        uid = int(args[1])
        amount = float(args[2])
    except:
        await message.answer("Неверный формат")
        return
    await add_crypto_balance(uid, amount)
    await message.answer(f"Крипто-баланс пользователя {uid} пополнен на {amount}$")

# ------------------------------------------------------------
# Рассылка (без aiosqlite)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.edit_text("📢 Введите текст сообщения для рассылки (можно с фото, видео, документом).\nДля отмены /cancel")
    await callback.answer()

@router.message(BroadcastState.waiting_for_message)
async def broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        user_ids = [r['user_id'] for r in rows]
    if not user_ids:
        await message.answer("Нет пользователей.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]
    ])
    await state.update_data(broadcast_message=message)
    await message.answer(f"Будет отправлено {len(user_ids)} пользователям. Начать?", reply_markup=kb)

@router.callback_query(F.data == "confirm_broadcast")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    orig: Message = data.get('broadcast_message')
    if not orig:
        await callback.answer("Сообщение не найдено")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        user_ids = [r['user_id'] for r in rows]
    success = 0
    fail = 0
    for uid in user_ids:
        try:
            if orig.text:
                await bot.send_message(uid, orig.text, parse_mode="HTML")
            elif orig.photo:
                await bot.send_photo(uid, orig.photo[-1].file_id, caption=orig.caption)
            elif orig.video:
                await bot.send_video(uid, orig.video.file_id, caption=orig.caption)
            elif orig.document:
                await bot.send_document(uid, orig.document.file_id, caption=orig.caption)
            else:
                await bot.send_message(uid, "Сообщение от администратора")
            success += 1
        except:
            fail += 1
    await callback.message.edit_text(f"✅ Рассылка завершена. Успешно: {success}, Ошибок: {fail}")
    await state.clear()
    await callback.answer()

# ------------------------------------------------------------
# Принятие заявки (холд/БХ) – использует hold_tasks
# ------------------------------------------------------------
@router.callback_query(F.data.startswith("accept_sub:"))
async def accept_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'pending':
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    mode = await get_setting("sale_mode", "hold")
    if mode == "bh":
        qr_count_30d, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr_count_30d)
        earned = sub['price'] + bonus
        await accept_submission_now(submission_id, admin_id, earned)
        try:
            await bot.send_message(sub['user_id'], f"✅ Ваш QR принят! Начислено {earned:.2f}$ (цена {sub['price']}$ + бонус {bonus}$).", reply_markup=main_menu(sub['user_id'] in ADMIN_IDS))
        except:
            pass
        await callback.answer("Заявка принята (БХ)")
        try:
            new_caption = f"✅ Принято (БХ, начислено) (админ @{callback.from_user.username})\n" + callback.message.caption.split("ID заявки:")[0]
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        except:
            pass
    else:
        hold_until = datetime.now() + timedelta(minutes=30)
        await hold_submission(submission_id, admin_id, hold_until)
        from handlers.callback_handlers import start_hold_timer
        delay = 30 * 60
        task = asyncio.create_task(start_hold_timer(bot, submission_id, sub['price'], sub['user_id'], delay))
        hold_tasks[submission_id] = task
        await callback.answer("Заявка переведена в холд на 30 минут")
        try:
            new_caption = f"⏳ Заявка на холде до {hold_until.strftime('%H:%M')} (админ @{callback.from_user.username})\n" + callback.message.caption.split("ID заявки:")[0]
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        except:
            pass

# ------------------------------------------------------------
# Отклонение заявки с выбором причины
# ------------------------------------------------------------
@router.callback_query(F.data.startswith("reject_sub:"))
async def reject_submission_reason(callback: CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[1])
    await state.update_data(reject_submission_id=submission_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Блок (неверный QR)", callback_data=f"reject_reason:block:{submission_id}"),
         InlineKeyboardButton(text="📸 Нескан (плохое фото)", callback_data=f"reject_reason:noscan:{submission_id}")]
    ])
    try:
        await callback.message.edit_caption(caption="Выберите причину отклонения:", reply_markup=kb)
    except:
        await callback.message.edit_text("Выберите причину отклонения:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("reject_reason:"))
async def reject_with_reason(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return
    _, reason, submission_id = callback.data.split(":")
    submission_id = int(submission_id)
    sub = await get_submission(submission_id)
    if not sub or sub['status'] not in ('pending', 'hold'):
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    if submission_id in hold_tasks:
        hold_tasks[submission_id].cancel()
        del hold_tasks[submission_id]
    await reject_submission(submission_id, admin_id, reason)
    try:
        if reason == 'block':
            msg = "❌ Ваш QR отклонён. Причина: неверный QR или номер."
        else:
            msg = "❌ Ваш QR отклонён. Причина: не удалось сканировать (плохое фото)."
        await bot.send_message(sub['user_id'], msg, reply_markup=main_menu(sub['user_id'] in ADMIN_IDS))
    except:
        pass
    await callback.message.delete()
    await callback.message.answer(f"❌ Заявка #{submission_id} отклонена (причина: {'блок' if reason=='block' else 'нескан'})")
    await callback.answer()

# ------------------------------------------------------------
# Дополнительные текстовые команды
# ------------------------------------------------------------
@router.message(Command("pending"))
async def cmd_pending(message: Message):
    if not await is_admin(message.from_user.id):
        return
    pending = await get_pending_submissions(10)
    if not pending:
        await message.answer("Нет непроверенных заявок.")
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))

@router.message(Command("set_prices"))
async def cmd_set_prices(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 4:
        await message.answer("Использование: /set_prices <оператор> <цена_холд> <цена_бх>\nПример: /set_prices Билайн 15 12")
        return
    operator = args[1]
    try:
        price_hold = float(args[2])
        price_bh = float(args[3])
    except:
        await message.answer("Цены должны быть числами.")
        return
    await update_operator_prices(operator, price_hold, price_bh)
    await message.answer(f"✅ Цены для {operator} установлены: ХОЛД = {price_hold}$, БХ = {price_bh}$")

@router.message(Command("set_slot"))
async def cmd_set_slot(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /set_slot <оператор> <лимит>")
        return
    operator = args[1]
    try:
        limit = int(args[2])
    except:
        await message.answer("Лимит должен быть целым числом.")
        return
    await update_operator_slot_limit(operator, limit)
    await message.answer(f"✅ Лимит слотов для {operator} установлен: {limit if limit != -1 else 'безлимит'}")

@router.message(Command("set_mode"))
async def cmd_set_mode(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2 or args[1] not in ('hold', 'bh'):
        await message.answer("Использование: /set_mode hold|bh")
        return
    await set_setting("sale_mode", args[1])
    await message.answer(f"Режим сдачи изменён на {'ХОЛД' if args[1]=='hold' else 'БХ'}")

@router.callback_query(F.data == "admin_withdraw_requests")
async def list_withdraw_requests(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    requests = await get_pending_withdraw_requests()
    if not requests:
        await callback.message.edit_text("Нет активных заявок на вывод.", reply_markup=admin_main_menu())
        return
    for req in requests:
        user = await get_user(req['user_id'])
        text = f"Заявка #{req['id']}\n👤 @{user['username']} (ID {user['user_id']})\n💰 {req['amount']}$\n🕒 {req['requested_at']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"withdraw_paid:{req['id']}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"withdraw_reject:{req['id']}")]
        ])
        await callback.message.answer(text, reply_markup=kb)
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data.startswith("withdraw_paid:"))
async def withdraw_paid(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    req_id = int(callback.data.split(":")[1])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, amount FROM withdraw_requests WHERE id = $1 AND status = 'pending'", req_id)
        if not row:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        user_id = row['user_id']
        amount = row['amount']
        # Снимаем сумму с баланса (если не сняли ранее)
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance - $1 WHERE user_id = $2", amount, user_id)
        await update_withdraw_request(req_id, 'paid', callback.from_user.id)
    await callback.answer("Выплата отмечена")
    await callback.message.delete()
    await callback.message.answer(f"✅ Выплата по заявке #{req_id} подтверждена.")
    # Уведомляем пользователя
    user = await get_user(user_id)
    if user:
        await callback.bot.send_message(user_id, f"✅ Ваша заявка на вывод {amount}$ выполнена. Деньги отправлены вам.")

@router.callback_query(F.data.startswith("withdraw_reject:"))
async def withdraw_reject(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    req_id = int(callback.data.split(":")[1])
    await update_withdraw_request(req_id, 'rejected', callback.from_user.id)
    await callback.answer("Заявка отклонена")
    await callback.message.delete()