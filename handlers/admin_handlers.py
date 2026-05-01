import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from db import (
    get_pool, get_pending_submissions, get_operators, update_operator_prices,
    update_operator_slot_limit, get_setting, set_setting, get_today_stats,
    get_top_users, get_user, add_crypto_balance, reject_submission,
    get_submission, accept_submission_now, get_user_qr_last_30_days,
    accept_submission_from_hold, hold_submission, take_submission,
    get_user_role, remove_worker, add_worker, get_workers, mark_submission_failed,
    mark_submission_blocked
)
from states import AdminSetPrice, AdminSetSlot, BroadcastState, AdminAddWorker, AdminDelWorker
from utils import calculate_rank
from user_keyboards import main_menu
from admin_keyboards import (
    admin_main_menu, pending_actions, operators_price_edit,
    operators_slot_edit, mode_buttons, confirm_clear, payout_list,
    workers_menu, work_actions
)

router = Router()
hold_tasks = {}

async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

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

@router.callback_query(F.data == "admin_pending")
async def list_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    pending = await get_pending_submissions(20)
    if not pending:
        await callback.message.edit_text("Нет непроверенных заявок.", reply_markup=admin_main_menu())
        await callback.answer()
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await callback.message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data == "admin_prices")
async def edit_prices_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    await callback.message.edit_text("Выберите оператора для изменения цен:", reply_markup=operators_price_edit(operators))
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

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    today_stats = await get_today_stats()
    top_users = await get_top_users(5)
    text = f"📊 Статистика за сегодня:\n✅ Зачтено QR: {today_stats['total_qr']}\n💰 Сумма: {today_stats['total_earned']:.2f}$\n\n🏆 Топ-5 по общему заработку:\n"
    for i, u in enumerate(top_users, 1):
        user = await get_user(u['user_id'])
        name = f"@{user['username']}" if user and user['username'] else f"ID {u['user_id']}"
        text += f"{i}. {name} — {u['total_earned']:.2f}$\n"
    await callback.message.edit_text(text, reply_markup=admin_main_menu())
    await callback.answer()

@router.callback_query(F.data == "admin_payouts")
async def payouts_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, earned_today FROM users WHERE earned_today > 0")
        users = [dict(row) for row in rows]
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
        user_ids = [row['user_id'] for row in rows]
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
        user_ids = [row['user_id'] for row in rows]
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

# ---------- Управление работниками (команды) ----------
@router.message(Command("add_worker"))
async def cmd_add_worker(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /add_worker <user_id>")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("Неверный ID")
        return
    user = await get_user(user_id)
    if not user:
        await message.answer("Пользователь не найден")
        return
    await add_worker(user_id)
    await message.answer(f"✅ Пользователь {user_id} назначен работником.")

@router.message(Command("remove_worker"))
async def cmd_remove_worker(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /remove_worker <user_id>")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("Неверный ID")
        return
    await remove_worker(user_id)
    await message.answer(f"✅ Пользователь {user_id} больше не работник.")

# ---------- Обработка заявок (взятие, засчитать, слетел, блок) ----------
@router.callback_query(F.data.startswith("take_sub:"))
async def take_submission_callback(callback: CallbackQuery, bot: Bot):
    worker_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'pending':
        await callback.answer("Заявка уже обработана или недоступна", show_alert=True)
        return
    role = await get_user_role(worker_id)
    if role not in ('admin', 'worker'):
        await callback.answer("У вас нет прав брать заявки в работу", show_alert=True)
        return
    await take_submission(submission_id, worker_id)
    try:
        await bot.send_message(sub['user_id'], "👨‍💻 Ваш номер взят в работу! Ожидайте решения.")
    except:
        pass
    await callback.message.edit_caption(
        caption=f"🔄 Заявка #{submission_id} в работе у @{callback.from_user.username}\nОператор: {sub['operator']}\nНомер: {sub['phone']}",
        reply_markup=work_actions(submission_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pay_sub:"))
async def pay_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе или уже обработана", show_alert=True)
        return
    mode = await get_setting("sale_mode", "hold")
    if mode == "bh":
        qr_count_30d, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr_count_30d)
        earned = sub['price'] + bonus
        await accept_submission_now(submission_id, admin_id, earned)
        await bot.send_message(sub['user_id'], f"✅ Ваш номер принят! Начислено {earned:.2f}$ (цена {sub['price']}$ + бонус {bonus}$).")
        await callback.message.edit_caption(caption=f"✅ Заявка #{submission_id} засчитана (админ @{callback.from_user.username})", reply_markup=None)
    else:
        hold_until = datetime.now() + timedelta(minutes=30)
        await hold_submission(submission_id, admin_id, hold_until)
        delay = 30 * 60
        from callback_handlers import start_hold_timer
        task = asyncio.create_task(start_hold_timer(bot, submission_id, sub['price'], sub['user_id'], delay))
        hold_tasks[submission_id] = task
        await bot.send_message(sub['user_id'], f"✅ Номер принят и переведён в холд на 30 минут. Начисление будет автоматически.")
        await callback.message.edit_caption(caption=f"⏳ Заявка #{submission_id} в холде до {hold_until.strftime('%H:%M')} (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

@router.callback_query(F.data.startswith("fail_sub:"))
async def fail_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе", show_alert=True)
        return
    await mark_submission_failed(submission_id, admin_id)
    await bot.send_message(sub['user_id'], "🔄 Ваш номер слетел (не засчитан).")
    await callback.message.edit_caption(caption=f"❌ Заявка #{submission_id} помечена как слетевшая (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

@router.callback_query(F.data.startswith("block_sub:"))
async def block_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе", show_alert=True)
        return
    await mark_submission_blocked(submission_id, admin_id)
    await bot.send_message(sub['user_id'], "🚫 Ваш номер заблокирован (не засчитан).")
    await callback.message.edit_caption(caption=f"🚫 Заявка #{submission_id} заблокирована (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    total = await get_total_users_count()
    pool = await get_pool()
    async with pool.acquire() as conn:
        today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE DATE(registered_at) = CURRENT_DATE")
        week = await conn.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= NOW() - INTERVAL '7 days'")
    text = f"👥 **Статистика пользователей**\n\n"
    text += f"📊 Всего зарегистрировано: {total}\n"
    text += f"✅ За сегодня: {today}\n"
    text += f"📆 За 7 дней: {week}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_main_menu())
    await callback.answer()

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