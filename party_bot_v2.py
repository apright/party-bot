import os
import json
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8573908942:AAGDxl6rz7DTcqHFU5wpLbcw0U1Y777ycsE")
DATA_FILE = Path("party_ledger.json")
CURRENCY = "₹"  # change if you want


# ========= STORAGE HELPERS =========

def load_data():
    if not DATA_FILE.exists():
        return {"balances": {}, "history": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_user_entry(data, user_id, display_name):
    """Make sure a user has a balances entry with fields: name, lost, paid."""
    balances = data.setdefault("balances", {})
    entry = balances.setdefault(str(user_id), {"name": display_name, "lost": 0.0, "paid": 0.0})

    # Update latest name and backfill old schema if needed
    entry["name"] = display_name
    if "lost" not in entry:
        entry["lost"] = entry.get("total", 0.0)  # from old version
    if "paid" not in entry:
        entry["paid"] = 0.0

    return entry


def add_loss(user_id, display_name, amount, reason, by_user_id, by_name):
    data = load_data()

    entry = ensure_user_entry(data, user_id, display_name)
    entry["lost"] += amount

    history = data.setdefault("history", [])
    history.append({
        "kind": "loss",
        "loser_id": user_id,
        "loser_name": display_name,
        "amount": amount,
        "reason": reason,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "recorded_by_id": by_user_id,
        "recorded_by_name": by_name,
    })

    save_data(data)


def add_payment(user_id, display_name, amount, reason):
    data = load_data()

    entry = ensure_user_entry(data, user_id, display_name)
    entry["paid"] += amount

    history = data.setdefault("history", [])
    history.append({
        "kind": "payment",
        "payer_id": user_id,
        "payer_name": display_name,
        "amount": amount,
        "reason": reason,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })

    save_data(data)


def reset_all():
    data = {"balances": {}, "history": []}
    save_data(data)


# ========= COMMAND HANDLERS =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎉 Welcome to Party Account Bot v2!\n\n"
        "Track who loses bets *and* who pays for parties.\n\n"
        "Main commands:\n"
        "/lost @user amount [reason]  - record a loss\n"
        "/paid amount [reason]        - you paid for the group\n"
        "/score                        - show lost / paid / net\n"
        "/me                           - your own stats\n"
        "/history                      - recent log\n"
        "/toploser                     - biggest net loser\n"
        "/settle                       - reset everything\n"
    )
    await update.message.reply_text(text)


async def lost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /lost @username amount [reason]
    Example: /lost @rahul 200 Beer pong
    """
    message = update.message
    if not message:
        return

    if not context.args or len(context.args) < 2:
        await message.reply_text(
            "Usage: /lost @username amount [reason]\n"
            "Example: /lost @rahul 200 Beer pong"
        )
        return

    # 1) Get loser from mention or plain text
    loser_user = None
    loser_name = None

    if message.entities:
        for ent in message.entities:
            if ent.type in ("text_mention", "mention"):
                if ent.type == "text_mention":
                    loser_user = ent.user
                    loser_name = loser_user.full_name
                else:
                    mention_text = message.text[ent.offset:ent.offset + ent.length]
                    loser_name = mention_text
                break

    if loser_user is None and loser_name is None:
        # fallback: first argument as name
        loser_name = context.args[0]

    # 2) Parse amount
    try:
        amount = None
        amount_index = None
        for i, arg in enumerate(context.args):
            try:
                amount = float(arg)
                amount_index = i
                break
            except ValueError:
                continue
        if amount is None:
            raise ValueError("No numeric amount")
    except Exception:
        await message.reply_text(
            "Couldn't understand the amount.\n"
            "Usage: /lost @username amount [reason]\n"
            "Example: /lost @rahul 200 Beer pong"
        )
        return

    # 3) Reason
    reason_parts = context.args[amount_index + 1:]
    reason = " ".join(reason_parts) if reason_parts else "No reason"

    # 4) Loser ID
    if loser_user is not None:
        loser_id = loser_user.id
        if not loser_name:
            loser_name = loser_user.full_name
    else:
        # text-only name
        loser_id = f"name:{loser_name}"

    recorder = message.from_user

    add_loss(
        user_id=loser_id,
        display_name=loser_name,
        amount=amount,
        reason=reason,
        by_user_id=recorder.id,
        by_name=recorder.full_name,
    )

    await message.reply_text(
        f"Recorded: {loser_name} lost {CURRENCY}{amount:.2f} – {reason}"
    )


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /paid amount [reason]
    Example: /paid 1200 Zomato party
    """
    message = update.message
    if not message:
        return

    if not context.args:
        await message.reply_text(
            "Usage: /paid amount [reason]\n"
            "Example: /paid 1200 Zomato party"
        )
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await message.reply_text(
            "Couldn't understand the amount.\n"
            "Usage: /paid amount [reason]\n"
            "Example: /paid 1200 Zomato party"
        )
        return

    reason_parts = context.args[1:]
    reason = " ".join(reason_parts) if reason_parts else "Party expense"

    payer = message.from_user

    add_payment(
        user_id=payer.id,
        display_name=payer.full_name,
        amount=amount,
        reason=reason,
    )

    await message.reply_text(
        f"Recorded: {payer.full_name} paid {CURRENCY}{amount:.2f} – {reason}"
    )


async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    balances = data.get("balances", {})

    if not balances:
        await update.message.reply_text("No bets or payments recorded yet.")
        return

    def net(entry):
        return entry.get("lost", entry.get("total", 0.0)) - entry.get("paid", 0.0)

    sorted_items = sorted(balances.items(), key=lambda kv: net(kv[1]), reverse=True)

    lines = ["🧾 Party Ledger (lost / paid / net):"]
    for _, entry in sorted_items:
        name = entry.get("name", "Unknown")
        lost_amt = entry.get("lost", entry.get("total", 0.0))
        paid_amt = entry.get("paid", 0.0)
        net_amt = lost_amt - paid_amt

        lines.append(
            f"{name}: lost {CURRENCY}{lost_amt:.2f}, "
            f"paid {CURRENCY}{paid_amt:.2f}, "
            f"net {CURRENCY}{net_amt:.2f}"
        )

    await update.message.reply_text("\n".join(lines))


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    data = load_data()
    balances = data.get("balances", {})
    entry = balances.get(str(user.id))

    if not entry:
        await update.message.reply_text("You have no recorded bets or payments yet.")
        return

    lost_amt = entry.get("lost", entry.get("total", 0.0))
    paid_amt = entry.get("paid", 0.0)
    net_amt = lost_amt - paid_amt

    loss_count = sum(
        1 for h in data.get("history", [])
        if h.get("kind") == "loss" and str(h.get("loser_id")) == str(user.id)
    )
    pay_count = sum(
        1 for h in data.get("history", [])
        if h.get("kind") == "payment" and str(h.get("payer_id")) == str(user.id)
    )

    await update.message.reply_text(
        f"{user.full_name}, you have:\n"
        f"- Lost {CURRENCY}{lost_amt:.2f} across {loss_count} bets\n"
        f"- Paid {CURRENCY}{paid_amt:.2f} across {pay_count} expenses\n"
        f"=> Net {CURRENCY}{net_amt:.2f}"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    history_list = data.get("history", [])

    if not history_list:
        await update.message.reply_text("No history yet.")
        return

    last_entries = history_list[-10:]
    lines = ["📚 Last entries:"]

    for idx, h in enumerate(reversed(last_entries), start=1):
        kind = h.get("kind", "loss")
        ts = h.get("timestamp", "")
        if kind == "loss":
            name = h.get("loser_name", "Unknown")
            amount = h.get("amount", 0)
            reason = h.get("reason", "")
            lines.append(f"{idx}. LOSS  {name} lost {CURRENCY}{amount:.2f} – {reason} ({ts})")
        else:
            name = h.get("payer_name", "Unknown")
            amount = h.get("amount", 0)
            reason = h.get("reason", "")
            lines.append(f"{idx}. PAID  {name} paid {CURRENCY}{amount:.2f} – {reason} ({ts})")

    await update.message.reply_text("\n".join(lines))


async def toploser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    balances = data.get("balances", {})

    if not balances:
        await update.message.reply_text("No data yet.")
        return

    def net(entry):
        return entry.get("lost", entry.get("total", 0.0)) - entry.get("paid", 0.0)

    top_id, top_entry = max(balances.items(), key=lambda kv: net(kv[1]))
    name = top_entry.get("name", "Unknown")
    net_amt = net(top_entry)

    await update.message.reply_text(
        f"🏆 Current Champion Loser: {name} with net {CURRENCY}{net_amt:.2f}"
    )


async def settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    reset_all()
    await update.message.reply_text(
        f"✅ All balances and history reset by {user.full_name} on {datetime.now().strftime('%Y-%m-%d %H:%M')}."
    )


# ========= FALLBACK =========

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I don't understand that command. Try /score or /lost.")


# ========= MAIN =========

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lost", lost))
    app.add_handler(CommandHandler("paid", paid))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("toploser", toploser))
    app.add_handler(CommandHandler("settle", settle))

    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Party bot v2 is running... Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
