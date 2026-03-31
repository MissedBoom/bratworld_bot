import os
import random
import sqlite3
import time
import asyncio

import discord
from discord.ext import commands

TOKEN = os.getenv("TOKEN")

WORK_MIN = 800
WORK_MAX = 1100
WORK_COOLDOWN = 600  # 10 minutes in seconds

DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "economy.db")

db_lock = asyncio.Lock()

WORK_MESSAGES = [
    "You pulled off a clean BRAT WORLD hustle and earned **{amount:,} BRAT CASH**.",
    "You cashed in on your brat energy and collected **{amount:,} BRAT CASH**.",
    "You worked the room perfectly and walked away with **{amount:,} BRAT CASH**.",
    "You played your part in BRAT WORLD and got paid **{amount:,} BRAT CASH**.",
    "You stayed sharp, stayed bratty, and earned **{amount:,} BRAT CASH**.",
    "Your grind paid off. You secured **{amount:,} BRAT CASH**."
]


def init_database() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                last_work INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def ensure_user_exists(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, balance, last_work) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()


def get_user_data(user_id: int) -> tuple[int, int]:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT balance, last_work FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()

    if row is None:
        return 0, 0

    return row[0], row[1]


def apply_work_reward(user_id: int, amount: int, timestamp: int) -> int:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET balance = balance + ?, last_work = ?
            WHERE user_id = ?
            """,
            (amount, timestamp, user_id)
        )

        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        new_balance = cursor.fetchone()[0]
        conn.commit()

    return new_balance


def format_remaining_time(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds}s"


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def setup_hook():
    init_database()
    synced = await bot.tree.sync()
    print(f"✅ Bot connected as {bot.user}")
    print(f"✅ {len(synced)} slash commands synced")
    for cmd in synced:
        print(f"  - /{cmd.name}")


@bot.tree.command(name="work", description="Earn BRAT CASH.")
async def work(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = int(time.time())

    async with db_lock:
        balance, last_work = get_user_data(user_id)
        elapsed = now - last_work

        if elapsed < WORK_COOLDOWN:
            remaining = WORK_COOLDOWN - elapsed

            embed = discord.Embed(
                title="⏳ You need to wait",
                description=(
                    f"You already worked recently.\n"
                    f"Come back in **{format_remaining_time(remaining)}** to earn more **BRAT CASH**."
                ),
                color=0xED4245
            )
            embed.set_footer(text="Cooldown: 10 minutes")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        amount = random.randint(WORK_MIN, WORK_MAX)
        new_balance = apply_work_reward(user_id, amount, now)

    flavor_text = random.choice(WORK_MESSAGES).format(amount=amount)

    embed = discord.Embed(
        title="💸 BRAT CASH collected",
        description=flavor_text,
        color=0x57F287
    )
    embed.add_field(name="Earned", value=f"{amount:,} BRAT CASH", inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance:,} BRAT CASH", inline=True)
    embed.set_footer(text="Use /work again in 10 minutes.")

    await interaction.response.send_message(embed=embed)


bot.run(TOKEN)
