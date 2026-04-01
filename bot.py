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


# --------------------------------
# /WORK COMMAND
# --------------------------------

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
                last_work INTEGER NOT NULL DEFAULT 0,
                last_gamble INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        if "last_gamble" not in columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN last_gamble INTEGER NOT NULL DEFAULT 0"
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

def get_top_users(limit: int = 10) -> list[tuple[int, int]]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT user_id, balance
            FROM users
            ORDER BY balance DESC, user_id ASC
            LIMIT ?
            """,
            (limit,)
        )
        return cursor.fetchall()

def get_user_rank(user_id: int) -> tuple[int, int]:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        balance = row[0] if row else 0

        cursor = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE balance > ?
               OR (balance = ? AND user_id < ?)
            """,
            (balance, balance, user_id)
        )
        rank = cursor.fetchone()[0] + 1

    return rank, balance
    
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

# ----------------------
# /balance COMMAND
# ----------------------

@bot.tree.command(name="balance", description="Check your BRAT CASH balance.")
@discord.app_commands.describe(member="The member whose balance you want to check")
async def balance(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user

    async with db_lock:
        user_balance, _ = get_user_data(target.id)

    embed = discord.Embed(
        title="💰 BRAT CASH Balance",
        description=f"**{target.display_name}** currently has **{user_balance:,} BRAT CASH**.",
        color=0x5865F2
    )

    if target.avatar:
        embed.set_thumbnail(url=target.avatar.url)

    if target == interaction.user:
        embed.set_footer(text="Keep grinding with /work.")
    else:
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

# ---------------------
# /leaderboard COMMAND
# ---------------------

@bot.tree.command(name="leaderboard", description="View the richest members in BRAT WORLD.")
async def leaderboard(interaction: discord.Interaction):
    async with db_lock:
        top_users = get_top_users(10)
        requester_rank, requester_balance = get_user_rank(interaction.user.id)

    if not top_users:
        embed = discord.Embed(
            title="🏆 BRAT WORLD Leaderboard",
            description="No one has earned any **BRAT CASH** yet.",
            color=0xF1C40F
        )
        await interaction.response.send_message(embed=embed)
        return

    lines = []
    requester_in_top_10 = False

    for index, (user_id, balance) in enumerate(top_users, start=1):
        username = f"User {user_id}"

        if user_id == interaction.user.id:
            requester_in_top_10 = True

        if interaction.guild:
            member = interaction.guild.get_member(user_id)

            if member is None:
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    member = None

            if member is not None:
                username = member.display_name
            else:
                try:
                    user = await bot.fetch_user(user_id)
                    username = user.display_name
                except (discord.NotFound, discord.HTTPException):
                    pass

        if index == 1:
            prefix = "🥇"
        elif index == 2:
            prefix = "🥈"
        elif index == 3:
            prefix = "🥉"
        else:
            prefix = f"**{index}.**"

        lines.append(f"{prefix} {username} — **{balance:,} BRAT CASH**")

    embed = discord.Embed(
        title="🏆 BRAT WORLD Leaderboard",
        description="\n".join(lines),
        color=0xF1C40F
    )

    if not requester_in_top_10:
        embed.add_field(
            name="Your Position",
            value=f"**#{requester_rank}** — **{requester_balance:,} BRAT CASH**",
            inline=False
        )

    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

# ---------------------------
# /gamble COMMAND
# ---------------------------

GAMBLE_COST = 10_000
GAMBLE_COOLDOWN = 300  # 5 minutes in seconds

SPIN_WINDOW_SIZE = 5
SPIN_DELAYS = [0.18, 0.18, 0.22, 0.26, 0.32, 0.40, 0.52, 0.68, 0.90]

GAMBLE_RESULTS = [
    {
        "key": "loser",
        "name": "LOSER",
        "chance": 25,
        "payout": 0,
        "message_lines": [
            "*You've been focusing on the the wheel but a gentle girl came next to you, teased her beautiful cleavage and you were staring at her curves like a dumb boy already~*",
            "**'Shhh that's it, no need to win when I'm around~'**",
            "*You realize you lost all your BRAT CASH but it didn't matter, a hot brat like her deserved it anyway...*",
            "The wheel stopped on **LOSER**.",
            "You lost your entire stake.",
        ],
        "image_file": "loser.gif"
    },
    {
        "key": "so_close",
        "name": "SO CLOSE",
        "chance": 30,
        "payout": 5_000,
        "message_lines": [
            "*You've been winning a lot lately. Tonight was your lucky night ! You were about to spin the wheel again and a pretty girl in front of you caught your eyes and slowly licked her lips, making you throbb instantly*",
            '**"You should be focused on your bet silly, or one day, someone will steal it all~ "**',
            "*You look down on the machine and some of your BRAT CASH disappeared.*",
            "The wheel landed on **SO CLOSE**.",
            "You got part of your stake back.",
        ],
        "image_file": "so_close.gif"
    },
    {
        "key": "back_at_you",
        "name": "BACK AT YOU",
        "chance": 25,
        "payout": 10_000,
        "message_lines": [],
    },
    {
        "key": "double_up",
        "name": "DOUBLE UP",
        "chance": 15,
        "payout": 20_000,
        "message_lines": [],
    },
    {
        "key": "jackpot",
        "name": "JACKPOT",
        "chance": 5,
        "payout": 35_000,
        "message_lines": [],
    }
]

def build_gamble_result_text(result: dict) -> str:
    lines = result.get("message_lines", [])
    return "\n".join(lines).strip()

def update_user_balance(user_id: int, delta: int) -> int:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (delta, user_id)
        )

        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        new_balance = cursor.fetchone()[0]
        conn.commit()

    return new_balance

@bot.tree.command(name="gamble", description="Spend 10,000 BRAT CASH to spin the casino wheel.")
async def gamble(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = int(time.time())

    async with db_lock:
        balance, _ = get_user_data(user_id)
        last_gamble = get_last_gamble(user_id)

        elapsed = now - last_gamble
        if elapsed < GAMBLE_COOLDOWN:
            remaining = GAMBLE_COOLDOWN - elapsed

            embed = discord.Embed(
                title="🎰 Casino cooldown",
                description=(
                    f"You already used **/gamble** recently.\n"
                    f"Come back in **{format_remaining_time(remaining)}** to spin again."
                ),
                color=0xED4245
            )
            embed.set_footer(text="Gamble cooldown is active.")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if balance < GAMBLE_COST:
            missing = GAMBLE_COST - balance

            embed = discord.Embed(
                title="🎰 Not enough BRAT CASH",
                description=(
                    f"You need **{GAMBLE_COST:,} BRAT CASH** to use **/gamble**.\n"
                    f"You are currently missing **{missing:,} BRAT CASH**."
                ),
                color=0xED4245
            )
            embed.add_field(name="Current Balance", value=f"{balance:,} BRAT CASH", inline=True)
            embed.add_field(name="Required", value=f"{GAMBLE_COST:,} BRAT CASH", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        result = random.choices(
            GAMBLE_RESULTS,
            weights=[entry["chance"] for entry in GAMBLE_RESULTS],
            k=1
        )[0]

        net_change = result["payout"] - GAMBLE_COST
        new_balance = apply_gamble_result(user_id, net_change, now)

    await interaction.response.defer()

    spin_windows = generate_spin_windows(result["name"])

    for index, (window, delay) in enumerate(zip(spin_windows, SPIN_DELAYS), start=1):
        embed = discord.Embed(
            title="🎰 BRAT WORLD Casino",
            description=(
                "**Spinning the wheel...**\n\n"
                f"{build_spin_line(window)}"
            ),
            color=0xFEE75C
        )

        if index < len(SPIN_DELAYS) // 2:
            embed.set_footer(text="The wheel is spinning fast...")
        else:
            embed.set_footer(text="The wheel is slowing down...")

        await interaction.edit_original_response(embed=embed)
        await asyncio.sleep(delay)

    final_window = spin_windows[-1]

    if net_change > 0:
        outcome_text = f"+{net_change:,} BRAT CASH"
        color = 0x57F287
    elif net_change < 0:
        outcome_text = f"-{abs(net_change):,} BRAT CASH"
        color = 0xED4245
    else:
        outcome_text = "±0 BRAT CASH"
        color = 0xFEE75C

    result_text = build_gamble_result_text(result)

    description = (
        f"**The wheel stops on {result['name']}!**\n\n"
        f"{build_spin_line(final_window)}"
    )

    if result_text:
        description += f"\n\n{result_text}"

    final_embed = discord.Embed(
        title="🎰 BRAT WORLD Casino",
        description=description,
        color=color
    )

    final_embed.add_field(name="Stake", value=f"{GAMBLE_COST:,} BRAT CASH", inline=True)
    final_embed.add_field(name="Result", value=result["name"], inline=True)
    final_embed.add_field(name="Net Change", value=outcome_text, inline=True)
    final_embed.add_field(name="New Balance", value=f"{new_balance:,} BRAT CASH", inline=False)
    final_embed.set_footer(text=f"Use /gamble again in {GAMBLE_COOLDOWN // 60} minutes.")

    attachment_file = None

    if result.get("image_file"):
        filename = result["image_file"]
        attachment_file = discord.File(f"assets/{filename}", filename=filename)
        final_embed.set_image(url=f"attachment://{filename}")

    if attachment_file:
        await interaction.edit_original_response(
            embed=final_embed,
            attachments=[attachment_file]
        )
    else:
        await interaction.edit_original_response(embed=final_embed)

def get_last_gamble(user_id: int) -> int:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT last_gamble FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()

    return row[0] if row else 0


def apply_gamble_result(user_id: int, net_change: int, timestamp: int) -> int:
    ensure_user_exists(user_id)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET balance = balance + ?, last_gamble = ?
            WHERE user_id = ?
            """,
            (net_change, timestamp, user_id)
        )

        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        new_balance = cursor.fetchone()[0]
        conn.commit()

    return new_balance


def build_spin_line(window: list[str]) -> str:
    center_index = len(window) // 2
    parts = []

    for index, label in enumerate(window):
        if index == center_index:
            parts.append(f"**【 {label} 】**")
        else:
            parts.append(f"`{label}`")

    return "  ".join(parts)


def generate_spin_windows(final_result_name: str) -> list[list[str]]:
    pool = [entry["name"] for entry in GAMBLE_RESULTS]
    total_frames = len(SPIN_DELAYS)

    sequence = [
        random.choice(pool)
        for _ in range(total_frames + SPIN_WINDOW_SIZE)
    ]

    final_center_index = (total_frames - 1) + (SPIN_WINDOW_SIZE // 2)
    sequence[final_center_index] = final_result_name

    windows = []
    for i in range(total_frames):
        windows.append(sequence[i:i + SPIN_WINDOW_SIZE])

    return windows

# -----------------
# /add & remove COMMAND
# -----------------

@bot.tree.command(name="add", description="Add BRAT CASH to a member.")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(
    member="The member who will receive BRAT CASH",
    amount="The amount of BRAT CASH to add"
)
async def add(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    async with db_lock:
        new_balance = update_user_balance(member.id, amount)

    embed = discord.Embed(
        title="➕ BRAT CASH Added",
        description=f"Added **{amount:,} BRAT CASH** to **{member.display_name}**.",
        color=0x57F287
    )
    embed.add_field(name="Member", value=member.mention, inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance:,} BRAT CASH", inline=True)
    embed.set_footer(text=f"Action performed by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="remove", description="Remove BRAT CASH from a member.")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(
    member="The member who will lose BRAT CASH",
    amount="The amount of BRAT CASH to remove"
)
async def remove(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    async with db_lock:
        current_balance, _ = get_user_data(member.id)
        removed_amount = min(amount, current_balance)
        new_balance = update_user_balance(member.id, -removed_amount)

    embed = discord.Embed(
        title="➖ BRAT CASH Removed",
        description=f"Removed **{removed_amount:,} BRAT CASH** from **{member.display_name}**.",
        color=0xED4245
    )
    embed.add_field(name="Member", value=member.mention, inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance:,} BRAT CASH", inline=True)

    if removed_amount < amount:
        embed.add_field(
            name="Note",
            value="The requested amount was higher than the member's balance, so the balance was reduced to 0.",
            inline=False
        )

    embed.set_footer(text=f"Action performed by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

@add.error
async def add_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.",
            ephemeral=True
        )


@remove.error
async def remove_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.",
            ephemeral=True
        )

# --------------------
# /give & request COMMAND
# --------------------

def transfer_brat_cash(from_user_id: int, to_user_id: int, amount: int) -> tuple[bool, int, int]:
    if amount <= 0:
        return False, 0, 0

    ensure_user_exists(from_user_id)
    ensure_user_exists(to_user_id)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (from_user_id,)
        )
        from_balance = cursor.fetchone()[0]

        if from_balance < amount:
            cursor = conn.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (to_user_id,)
            )
            to_balance = cursor.fetchone()[0]
            return False, from_balance, to_balance

        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (amount, from_user_id)
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, to_user_id)
        )

        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (from_user_id,)
        )
        new_from_balance = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (to_user_id,)
        )
        new_to_balance = cursor.fetchone()[0]

        conn.commit()

    return True, new_from_balance, new_to_balance

class BratCashRequestView(discord.ui.View):
    def __init__(self, requester: discord.Member, target: discord.Member, amount: int):
        super().__init__(timeout=300)
        self.requester = requester
        self.target = target
        self.amount = amount
        self.message = None
        self.completed = False

    def build_pending_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="💸 BRAT CASH Request",
            description=(
                f"{self.requester.mention} is requesting **{self.amount:,} BRAT CASH** from {self.target.mention}.\n\n"
                f"{self.target.mention}, do you want to accept this request?"
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Only the requested member can use these buttons.")
        return embed

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "❌ Only the requested member can accept this request.",
                ephemeral=True
            )
            return

        if self.completed:
            await interaction.response.send_message(
                "❌ This request has already been handled.",
                ephemeral=True
            )
            return

        async with db_lock:
            success, new_target_balance, new_requester_balance = transfer_brat_cash(
                self.target.id,
                self.requester.id,
                self.amount
            )

        self.completed = True
        for item in self.children:
            item.disabled = True

        if success:
            embed = discord.Embed(
                title="✅ Request Accepted",
                description=(
                    f"{self.target.mention} sent **{self.amount:,} BRAT CASH** to {self.requester.mention}."
                ),
                color=0x57F287
            )
            embed.add_field(
                name=f"{self.target.display_name}'s New Balance",
                value=f"{new_target_balance:,} BRAT CASH",
                inline=True
            )
            embed.add_field(
                name=f"{self.requester.display_name}'s New Balance",
                value=f"{new_requester_balance:,} BRAT CASH",
                inline=True
            )
        else:
            embed = discord.Embed(
                title="❌ Request Failed",
                description=(
                    f"{self.target.mention} tried to accept the request, but does not have enough **BRAT CASH**."
                ),
                color=0xED4245
            )
            embed.add_field(
                name="Current Balance",
                value=f"{new_target_balance:,} BRAT CASH",
                inline=True
            )
            embed.add_field(
                name="Requested Amount",
                value=f"{self.amount:,} BRAT CASH",
                inline=True
            )

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "❌ Only the requested member can decline this request.",
                ephemeral=True
            )
            return

        if self.completed:
            await interaction.response.send_message(
                "❌ This request has already been handled.",
                ephemeral=True
            )
            return

        self.completed = True
        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="❌ Request Declined",
            description=(
                f"{self.target.mention} declined the **{self.amount:,} BRAT CASH** request from {self.requester.mention}."
            ),
            color=0xED4245
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.completed:
            return

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="⌛ Request Expired",
            description=(
                f"The **{self.amount:,} BRAT CASH** request from {self.requester.mention} to {self.target.mention} has expired."
            ),
            color=0xFEE75C
        )

        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

@bot.tree.command(name="give", description="Give BRAT CASH to another member.")
@discord.app_commands.describe(
    member="The member you want to give BRAT CASH to",
    amount="The amount of BRAT CASH to give"
)
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    if member.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ You cannot give BRAT CASH to yourself.",
            ephemeral=True
        )
        return

    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot give BRAT CASH to a bot.",
            ephemeral=True
        )
        return

    async with db_lock:
        success, new_sender_balance, new_receiver_balance = transfer_brat_cash(
            interaction.user.id,
            member.id,
            amount
        )

    if not success:
        embed = discord.Embed(
            title="❌ Not enough BRAT CASH",
            description=(
                f"You tried to give **{amount:,} BRAT CASH**, but you do not have enough."
            ),
            color=0xED4245
        )
        embed.add_field(name="Your Balance", value=f"{new_sender_balance:,} BRAT CASH", inline=True)
        embed.add_field(name="Required", value=f"{amount:,} BRAT CASH", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title="💸 BRAT CASH Sent",
        description=(
            f"{interaction.user.mention} gave **{amount:,} BRAT CASH** to {member.mention}."
        ),
        color=0x57F287
    )
    embed.add_field(name="Your New Balance", value=f"{new_sender_balance:,} BRAT CASH", inline=True)
    embed.add_field(name=f"{member.display_name}'s New Balance", value=f"{new_receiver_balance:,} BRAT CASH", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="request", description="Request BRAT CASH from another member.")
@discord.app_commands.describe(
    member="The member you want to request BRAT CASH from",
    amount="The amount of BRAT CASH you want to request"
)
async def request(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    if member.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ You cannot request BRAT CASH from yourself.",
            ephemeral=True
        )
        return

    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot request BRAT CASH from a bot.",
            ephemeral=True
        )
        return

    view = BratCashRequestView(interaction.user, member, amount)
    await interaction.response.send_message(
        embed=view.build_pending_embed(),
        view=view
    )
    view.message = await interaction.original_response()
    
bot.run(TOKEN)
