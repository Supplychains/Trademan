# bot.py
# Python 3.10+
# pip install python-telegram-bot==21.4
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Chat
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("auction-bot")

MAX_PLAYERS = 3
ROUNDS = 6
CHOICES = [1, 2, 3, 4, 5, 6]


@dataclass
class Player:
    user_id: int
    name: str
    is_bot: bool = False
    score: int = 0
    used: Set[int] = field(default_factory=set)
    secret: Optional[int] = None
    passed: bool = False


@dataclass
class Room:
    chat_id: int
    players_order: List[int] = field(default_factory=list)  # list of user_ids
    players: Dict[int, Player] = field(default_factory=dict)
    round: int = 1
    starter_idx: int = 0
    turn_idx: int = 0
    bid: Optional[int] = None
    revealed: bool = False

    def alive_ids(self) -> List[int]:
        return [uid for uid in self.players_order if not self.players[uid].passed]

    def everyone_selected(self) -> bool:
        return all(self.players[uid].secret is not None for uid in self.players_order)

    def true_value(self) -> int:
        return sum(self.players[uid].secret or 0 for uid in self.players_order)

    def winner(self) -> Player:
        for uid in self.players_order:
            if not self.players[uid].passed:
                return self.players[uid]
        return self.players[self.players_order[0]]


# In-memory rooms per group chat
rooms: Dict[int, Room] = {}


def user_display_name(update: Update) -> str:
    u = update.effective_user
    fn = (u.first_name or "").strip()
    ln = (u.last_name or "").strip()
    return (fn + (" " + ln if ln else "")).strip() or u.username or str(u.id)


async def ensure_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Room:
    chat: Chat = update.effective_chat
    room = rooms.get(chat.id)
    if not room:
        room = Room(chat_id=chat.id)
        rooms[chat.id] = room
    return room


def kb_select_number(used: Set[int]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for n in CHOICES:
        text = f"{n}" + (" ×" if n in used else "")
        row.append(InlineKeyboardButton(text=text, callback_data=f"pick:{n}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def kb_auction() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Повысить (+1)", callback_data="bid:raise")],
        [InlineKeyboardButton("Пас", callback_data="bid:pass")],
    ])


# === Commands ===

async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    room = await ensure_room(update, context)
    room.players.clear()
    room.players_order.clear()
    room.round = 1
    room.starter_idx = 0
    room.turn_idx = 0
    room.bid = None
    room.revealed = False
    await update.effective_chat.send_message(
        "Создан новый стол на 3 места. Набор открыт.\n"
        "Команды: /join — присоединиться, /addbot — добавить бота, /start — начать."
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    room = await ensure_room(update, context)
    user = update.effective_user
    if user.id in room.players:
        await update.effective_chat.send_message("Вы уже в списке игроков.")
        return
    if len(room.players_order) >= MAX_PLAYERS:
        await update.effective_chat.send_message("Стол заполнен.")
        return
    p = Player(user_id=user.id, name=user_display_name(update))
    room.players[user.id] = p
    room.players_order.append(user.id)
    await update.effective_chat.send_message(
        f"Игрок добавлен: {p.name} ({len(room.players_order)}/{MAX_PLAYERS})."
    )


async def cmd_addbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    room = await ensure_room(update, context)
    if len(room.players_order) >= MAX_PLAYERS:
        await update.effective_chat.send_message("Стол заполнен.")
        return
    bot_id = - (len([p for p in room.players.values() if p.is_bot]) + 1)
    p = Player(user_id=bot_id, name=f"Бот {abs(bot_id)}", is_bot=True)
    room.players[bot_id] = p
    room.players_order.append(bot_id)
    await update.effective_chat.send_message(
        f"Добавлен {p.name} ({len(room.players_order)}/{MAX_PLAYERS})."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    room = await ensure_room(update, context)
    if len(room.players_order) != MAX_PLAYERS:
        await update.effective_chat.send_message("Нужно ровно 3 игрока (люди и/или боты).")
        return
    await start_round(update, context, room)


# === Round flow ===

async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE, room: Room):
    room.bid = None
    room.revealed = False
    for uid in room.players_order:
        room.players[uid].secret = None
        room.players[uid].passed = False
    room.turn_idx = room.starter_idx

    await context.bot.send_message(
        room.chat_id,
        f"Раунд {room.round}/6. Стартует {room.players[room.players_order[room.starter_idx]].name}.\n"
        f"Люди получат выбор в личку, боты выберут сами."
    )

    # Ask humans, auto-pick for bots
    for uid in room.players_order:
        p = room.players[uid]
        if p.is_bot:
            for n in CHOICES:
                if n not in p.used:
                    p.secret = n
                    break
        else:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"Раунд {room.round}. Выберите тайное число (1–6). "
                         f"Каждое число можно использовать один раз за игру.",
                    reply_markup=kb_select_number(p.used)
                )
            except Exception:
                await context.bot.send_message(
                    room.chat_id,
                    f"{p.name}, напишите боту в личку и нажмите /start, чтобы он мог вам отвечать."
                )

    asyncio.create_task(wait_for_secrets_and_start_auction(context, room))


async def wait_for_secrets_and_start_auction(context: ContextTypes.DEFAULT_TYPE, room: Room):
    for _ in range(120):
        if room.everyone_selected():
            break
        await asyncio.sleep(1)
    if not room.everyone_selected():
        await context.bot.send_message(room.chat_id, "Не все выбрали число вовремя. Автоподстановка минимального.")
    for uid in room.players_order:
        p = room.players[uid]
        if p.secret is None:
            for n in CHOICES:
                if n not in p.used:
                    p.secret = n
                    break
    room.bid = 1
    await context.bot.send_message(
        room.chat_id,
        f"Числа зафиксированы. Стартовая ставка: {room.bid}\n"
        f"Ходит: {room.players[room.players_order[room.turn_idx]].name}",
        reply_markup=kb_auction()
    )
    await maybe_bot_move(context, room)


def next_turn(room: Room):
    for _ in range(len(room.players_order)):
        room.turn_idx = (room.turn_idx + 1) % len(room.players_order)
        uid = room.players_order[room.turn_idx]
        if not room.players[uid].passed:
            return


async def auction_status_text(room: Room) -> str:
    alive = ", ".join(room.players[uid].name for uid in room.alive_ids())
    return f"Ставка: {room.bid} • В игре: {alive} • Ходит: {room.players[room.players_order[room.turn_idx]].name}"


async def handle_auction_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room = rooms.get(query.message.chat_id)
    if not room or room.bid is None:
        return

    uid_act = update.effective_user.id
    turn_uid = room.players[room.players_order[room.turn_idx]].user_id
    if uid_act != turn_uid:
        await query.reply_text("Сейчас не ваш ход.")
        return
    if room.players[uid_act].passed:
        await query.reply_text("Вы уже пасовали.")
        return

    action = query.data
    if action == "bid:raise":
        room.bid += 1
        await context.bot.edit_message_text(
            chat_id=room.chat_id,
            message_id=query.message.message_id,
            text=f"{room.players[uid_act].name}: повышаю до {room.bid}\n" +
                 await auction_status_text(room),
            reply_markup=kb_auction()
        )
        next_turn(room)
    elif action == "bid:pass":
        room.players[uid_act].passed = True
        await context.bot.edit_message_text(
            chat_id=room.chat_id,
            message_id=query.message.message_id,
            text=f"{room.players[uid_act].name}: пас.\n" +
                 await auction_status_text(room),
            reply_markup=kb_auction()
        )
    await end_or_continue(update, context, room)
    await maybe_bot_move(context, room)


async def end_or_continue(update: Update, context: ContextTypes.DEFAULT_TYPE, room: Room):
    if len(room.alive_ids()) == 1:
        w = room.winner()
        true_val = room.true_value()
        paid = room.bid or 0
        delta = true_val - paid
        w.score += delta
        for uid in room.players_order:
            room.players[uid].used.add(room.players[uid].secret or 0)

        reveal = " + ".join(str(room.players[uid].secret) for uid in room.players_order)
        await context.bot.send_message(
            room.chat_id,
            f"Открываем числа: {reveal} = {true_val}\n"
            f"Победитель: {w.name}. Заплатил {paid}. Очки за раунд: {delta:+d}\n"
            f"Итог: " + ", ".join(f"{room.players[uid].name}: {room.players[uid].score}"
                                  for uid in room.players_order)
        )

        if room.round >= ROUNDS:
            podium = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
            await context.bot.send_message(
                room.chat_id,
                "Игра завершена.\n" +
                "\n".join(f"{i+1}. {p.name} — {p.score}" for i, p in enumerate(podium))
            )
            try:
                del rooms[room.chat_id]
            except KeyError:
                pass
        else:
            room.round += 1
            room.starter_idx = (room.starter_idx + 1) % len(room.players_order)
            await start_round(update, context, room)
    else:
        await context.bot.send_message(
            room.chat_id,
            await auction_status_text(room),
            reply_markup=kb_auction()
        )


async def maybe_bot_move(context: ContextTypes.DEFAULT_TYPE, room: Room):
    # While next player is a bot, let it act
    while True:
        uid = room.players[room.players_order[room.turn_idx]].user_id
        p = room.players[uid]
        if not p.is_bot or p.passed or room.bid is None:
            return
        await asyncio.sleep(1.0)
        my = p.secret or 1
        min_est = my + 2
        max_est = my + 12
        target = (min_est + max_est) // 2
        if (room.bid or 0) < target and (room.bid or 0) < max_est:
            room.bid = (room.bid or 0) + 1
            await context.bot.send_message(room.chat_id, f"{p.name}: повышаю до {room.bid}")
            next_turn(room)
        else:
            p.passed = True
            await context.bot.send_message(room.chat_id, f"{p.name}: пас.")
        dummy_update = Update(update_id=0)
        await end_or_continue(dummy_update, context, room)
        if room.bid is None:
            return


async def cb_pick_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if not data.startswith("pick:"):
        return
    n = int(data.split(":")[1])
    for room in rooms.values():
        if query.from_user.id in room.players:
            p = room.players[query.from_user.id]
            if p.secret is not None:
                await query.edit_message_text("Число уже выбрано.")
                return
            if n in p.used:
                await query.edit_message_text("Это число уже использовано ранее.")
                return
            if n not in CHOICES:
                return
            p.secret = n
            await query.edit_message_text(f"Число зафиксировано: {n}. Ждём остальных.")
            return


def register_handlers(app):
    app.add_handler(CommandHandler("newgame", cmd_newgame))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("addbot", cmd_addbot))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_auction_button, pattern=r"^bid:"))
    app.add_handler(CallbackQueryHandler(cb_pick_number, pattern=r"^pick:"))
