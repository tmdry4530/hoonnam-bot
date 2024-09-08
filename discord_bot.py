import os
import random
from discord.ext import tasks
from datetime import datetime, timedelta
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
import asyncpg

load_dotenv()

# 상수 정의
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID'))
DATABASE_URL = os.getenv('DATABASE_URL')
ROLE_ID_LEVEL_15 = int(os.getenv('ROLE_ID_LEVEL_15'))
ROLE_ID_LEVEL_30 = int(os.getenv('ROLE_ID_LEVEL_30'))
ROLE_ID_LEVEL_50 = int(os.getenv('ROLE_ID_LEVEL_50'))
XP_COOLDOWN = timedelta(minutes=1)
VOICE_XP_COOLDOWN = timedelta(minutes=10)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def init_db():
    bot.db = await asyncpg.create_pool(DATABASE_URL)

async def close_db():
    await bot.db.close()

async def create_tables():
    async with bot.db.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id BIGINT PRIMARY KEY,
                xp INTEGER NOT NULL,
                level INTEGER NOT NULL,
                last_message_time TIMESTAMP,
                last_voice_time TIMESTAMP
            )
        ''')

async def load_user_data(user_id):
    async with bot.db.acquire() as conn:
        user_data = await conn.fetchrow('SELECT * FROM user_levels WHERE user_id = $1', user_id)
        return user_data or {'xp': 0, 'level': 1, 'last_message_time': None, 'last_voice_time': None}

async def save_user_data(user_id, data):
    async with bot.db.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_levels(user_id, xp, level, last_message_time, last_voice_time)
            VALUES($1, $2, $3, $4, $5)
            ON CONFLICT(user_id) DO UPDATE
            SET xp = EXCLUDED.xp, level = EXCLUDED.level,
                last_message_time = EXCLUDED.last_message_time,
                last_voice_time = EXCLUDED.last_voice_time
        ''', user_id, data['xp'], data['level'], data['last_message_time'], data['last_voice_time'])

def calculate_xp_to_next_level(level):
    base_xp = 50
    increment = 100
    return base_xp + (level - 1) * increment

async def assign_role(channel, member, role_id, action="add"):
    guild = member.guild
    try:
        role = guild.get_role(role_id)
        if role:
            if action == "add" and role not in member.roles:
                await member.add_roles(role)
                await channel.send(f"{member.mention}, 축하합니다! {role.name} 역할이 부여되었습니다.")
            elif action == "remove" and role in member.roles:
                await member.remove_roles(role)
                await channel.send(f"{member.mention}, 죄송합니다. {role.name} 역할이 제거되었습니다.")
    except discord.Forbidden:
        print(f"권한 부족으로 역할을 {'부여' if action == 'add' else '제거'}할 수 없습니다: {member.name}")
    except Exception as e:
        await channel.send(f"오류가 발생했습니다: {e}")

async def handle_xp_change(channel, member, user_data, xp_change):
    user_data['xp'] += xp_change
    level_changed = False

    while user_data['xp'] >= calculate_xp_to_next_level(user_data['level']):
        user_data['level'] += 1
        level_changed = True

    while user_data['xp'] < 0 and user_data['level'] > 1:
        user_data['level'] -= 1
        user_data['xp'] += calculate_xp_to_next_level(user_data['level'] - 1)
        level_changed = True

    if user_data['xp'] < 0:
        user_data['xp'] = 0

    if level_changed:
        await channel.send(f"{member.mention}님, 레벨이 변경되었습니다! 현재 레벨: {user_data['level']} (다음 레벨까지 {calculate_xp_to_next_level(user_data['level']) - user_data['xp']} XP 필요)")
        
        if user_data['level'] >= 50:
            await assign_role(channel, member, ROLE_ID_LEVEL_50)
        elif user_data['level'] >= 30:
            await assign_role(channel, member, ROLE_ID_LEVEL_30)
        elif user_data['level'] >= 15:
            await assign_role(channel, member, ROLE_ID_LEVEL_15)
        
        if user_data['level'] < 50:
            await assign_role(channel, member, ROLE_ID_LEVEL_50, "remove")
        if user_data['level'] < 30:
            await assign_role(channel, member, ROLE_ID_LEVEL_30, "remove")
        if user_data['level'] < 15:
            await assign_role(channel, member, ROLE_ID_LEVEL_15, "remove")

    return user_data

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    user_data = await load_user_data(user_id)
    now = datetime.now()

    if user_data['last_message_time'] is None or (now - user_data['last_message_time']) >= XP_COOLDOWN:
        xp_gain = random.randint(10, 30)
        user_data['last_message_time'] = now
        user_data = await handle_xp_change(message.channel, message.author, user_data, xp_gain)
        await save_user_data(user_id, user_data)

    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def voice_activity_xp():
    now = datetime.now()
    for guild in bot.guilds:
        for member in guild.members:
            if member.voice and member.voice.channel:
                user_id = member.id
                user_data = await load_user_data(user_id)
                
                if user_data['last_voice_time'] is None or (now - user_data['last_voice_time']) >= VOICE_XP_COOLDOWN:
                    xp_gain = random.randint(10, 30)
                    user_data['last_voice_time'] = now
                    user_data = await handle_xp_change(guild.system_channel, member, user_data, xp_gain)
                    await save_user_data(user_id, user_data)

@bot.tree.command(name="레벨", description="현재 레벨을 확인합니다.")
async def level(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = await load_user_data(user_id)
    current_level = user_data['level']
    current_xp = user_data['xp']
    xp_to_next_level = calculate_xp_to_next_level(current_level)
    await interaction.response.send_message(f"{interaction.user.mention}님의 현재 레벨: {current_level}, 현재 XP: {current_xp}/{xp_to_next_level}")

@bot.tree.command(name="순위", description="서버 리더보드를 확인합니다.")
async def leaderboard(interaction: discord.Interaction):
    guild = interaction.guild
    leaderboard_data = []
    async with bot.db.acquire() as conn:
        records = await conn.fetch('''
            SELECT user_id, level, xp 
            FROM user_levels 
            ORDER BY level DESC, xp DESC 
            LIMIT 10
        ''')
        for record in records:
            member = guild.get_member(record['user_id'])
            if member:
                leaderboard_data.append((member.name, record['level'], record['xp']))

    leaderboard_message = "서버 리더보드 (상위 10명):\n"
    for idx, (name, level, xp) in enumerate(leaderboard_data, 1):
        leaderboard_message += f"{idx}. {name} - 레벨 {level} ({xp} XP)\n"

    await interaction.response.send_message(f"```{leaderboard_message}```")

@bot.tree.command(name="지급", description="XP를 지급합니다.")
async def give_xp(interaction: discord.Interaction, member: discord.Member, xp_amount: int):
    if ADMIN_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.")
        return

    user_data = await load_user_data(member.id)
    user_data = await handle_xp_change(interaction.channel, member, user_data, xp_amount)
    await save_user_data(member.id, user_data)
    await interaction.response.send_message(f"{member.mention}님에게 {xp_amount} XP가 지급되었습니다.")

@bot.tree.command(name="회수", description="XP를 회수합니다.")
async def remove_xp(interaction: discord.Interaction, member: discord.Member, xp_amount: int):
    if ADMIN_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.")
        return

    user_data = await load_user_data(member.id)
    user_data = await handle_xp_change(interaction.channel, member, user_data, -xp_amount)
    await save_user_data(member.id, user_data)
    await interaction.response.send_message(f"{member.mention}님에게서 {xp_amount} XP를 회수했습니다.")

@bot.tree.command(name="훈남봇_설명", description="봇의 기능을 설명합니다.")
async def bot_description(interaction: discord.Interaction):
    description = (
        "**훈남봇 기능 목록:**\n\n"
        "1. **레벨 확인**: `/레벨` 명령어로 자신의 현재 레벨과 경험치를 확인할 수 있습니다.\n"
        "2. **리더보드**: `/순위` 명령어로 서버의 상위 10명 레벨을 확인할 수 있습니다.\n"
        "3. **경험치 지급**: `/지급` 명령어로 특정 사용자에게 경험치를 지급할 수 있습니다. (관리자 전용)\n"
        "4. **경험치 회수**: `/회수` 명령어로 특정 사용자의 경험치를 회수할 수 있습니다. (관리자 전용)\n"
        "5. **자동 경험치 획득**: 메시지 작성 및 음성 채팅 참여로 자동으로 경험치를 획득합니다.\n"
        "6. **역할 자동 부여**: 특정 레벨에 도달하면 자동으로 역할이 부여됩니다.\n"
    )
    await interaction.response.send_message(description)

TEST_GUILD_ID = int(os.getenv('TEST_GUILD_ID'))
@bot.event
async def on_ready():
    await init_db()
    await create_tables()
    print(f'Logged in as {bot.user}!')
    voice_activity_xp.start()
    
    print("Syncing slash commands...")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

bot_token = os.getenv('DISCORD_BOT_TOKEN')
bot.run(bot_token)
