import os
import random
from discord.ext import tasks
from collections import defaultdict
from datetime import datetime, timedelta
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncpg

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
intents.voice_states = True

bot = commands.Bot(intents=intents)

admin_role_id = int(os.getenv('ADMIN_ROLE_ID'))
DATABASE_URL = os.getenv('DATABASE_URL')

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
        if user_data:
            return {
                'xp': user_data['xp'],
                'level': user_data['level'],
                'last_message_time': user_data['last_message_time'],
                'last_voice_time': user_data['last_voice_time']
            }
        else:
            return {'xp': 0, 'level': 1, 'last_message_time': None, 'last_voice_time': None}

async def save_user_data(user_id, data):
    async with bot.db.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_levels(user_id, xp, level, last_message_time, last_voice_time)
            VALUES($1, $2, $3, $4, $5)
            ON CONFLICT(user_id) DO UPDATE
            SET xp = EXCLUDED.xp, level = EXCLUDED.level, last_message_time = EXCLUDED.last_message_time, last_voice_time = EXCLUDED.last_voice_time
        ''', user_id, data['xp'], data['level'], data['last_message_time'], data['last_voice_time'])

def calculate_xp_to_next_level(level):
    base_xp = 50
    increment = 100
    xp_required = 0

    for i in range(1, level + 1):
        if 1 <= i <= 10:
            xp_required += increment
        elif 11 <= i <= 20:
            increment = 150
            xp_required += increment
        elif 21 <= i <= 30:
            increment = 200
            xp_required += increment
        else:
            increment += 50
            xp_required += increment

    return xp_required

async def assign_role_on_level_up(channel, member, new_level):
    guild = member.guild

    try:
        if new_level >= 50:
            role_id_50 = int(os.getenv('ROLE_ID_LEVEL_50'))
            role = guild.get_role(role_id_50)
            if role and role not in member.roles:
                await member.add_roles(role)
                await channel.send(f"{member.mention}, 축하합니다! {role.name} 역할이 부여되었습니다.")

        elif new_level >= 30:
            role_id_30 = int(os.getenv('ROLE_ID_LEVEL_30'))
            role = guild.get_role(role_id_30)
            if role and role not in member.roles:
                await member.add_roles(role)
                await channel.send(f"{member.mention}, 축하합니다! {role.name} 역할이 부여되었습니다.")

        elif new_level >= 15:
            role_id_15 = int(os.getenv('ROLE_ID_LEVEL_15'))
            role = guild.get_role(role_id_15)
            if role and role not in member.roles:
                await member.add_roles(role)
                await channel.send(f"{member.mention}, 축하합니다! {role.name} 역할이 부여되었습니다.")
    except discord.Forbidden:
        print(f"권한 부족으로 역할을 부여할 수 없습니다: {member.name}")
    except Exception as e:
        await channel.send(f"오류가 발생했습니다: {e}")

async def remove_role_on_level_down(channel, member, new_level):
    guild = member.guild

    try:
        if new_level < 15:
            role_id_15 = int(os.getenv('ROLE_ID_LEVEL_15'))
            role = guild.get_role(role_id_15)
            if role and role in member.roles:
                await member.remove_roles(role)
                await channel.send(f"{member.mention}, 죄송합니다. {role.name} 역할이 제거되었습니다.")

        if new_level < 30:
            role_id_30 = int(os.getenv('ROLE_ID_LEVEL_30'))
            role = guild.get_role(role_id_30)
            if role and role in member.roles:
                await member.remove_roles(role)
                await channel.send(f"{member.mention}, 죄송합니다. {role.name} 역할이 제거되었습니다.")

        if new_level < 50:
            role_id_50 = int(os.getenv('ROLE_ID_LEVEL_50'))
            role = guild.get_role(role_id_50)
            if role and role in member.roles:
                await member.remove_roles(role)
                await channel.send(f"{member.mention}, 죄송합니다. {role.name} 역할이 제거되었습니다.")
    except discord.Forbidden:
        print(f"권한 부족으로 역할을 제거할 수 없습니다: {member.name}")
    except Exception as e:
        await channel.send(f"오류가 발생했습니다: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    user_data = await load_user_data(user_id)
    
    now = datetime.now()

    if user_data['last_message_time'] is None or (now - user_data['last_message_time']) >= timedelta(minutes=1):
        xp_gain = random.randint(10, 30)
        user_data['xp'] += xp_gain
        user_data['last_message_time'] = now
        xp_to_next_level = calculate_xp_to_next_level(user_data['level'])

        if user_data['xp'] >= xp_to_next_level:
            user_data['level'] += 1
            user_data['xp'] -= xp_to_next_level
            await message.channel.send(f"{message.author.mention}님, 레벨업 했습니다! 현재 레벨: {user_data['level']} (다음 레벨까지 {calculate_xp_to_next_level(user_data['level']) - user_data['xp']} XP 필요)")
            await assign_role_on_level_up(message.channel, message.author, user_data['level'])

        await save_user_data(user_id, user_data)

    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def voice_activity_xp():
    now = datetime.now()
    for guild in bot.guilds:
        for member in guild.members:
            if member.voice is not None and member.voice.channel is not None:
                user_id = member.id
                user_data = await load_user_data(user_id)
                
                if not user_data:
                    user_data = {'xp': 0, 'level': 1, 'last_message_time': None, 'last_voice_time': None}

                if user_data['last_voice_time'] is None or (now - user_data['last_voice_time']) >= timedelta(minutes=10):
                    xp_gain = random.randint(10, 30)
                    user_data['xp'] += xp_gain
                    user_data['last_voice_time'] = now
                    xp_to_next_level = calculate_xp_to_next_level(user_data['level'])

                    if user_data['xp'] >= xp_to_next_level:
                        user_data['level'] += 1
                        user_data['xp'] -= xp_to_next_level
                        channel = member.guild.system_channel
                        if channel:
                            await channel.send(f"{member.mention}님, 음성 채팅 활동으로 레벨업 했습니다! 현재 레벨: {user_data['level']} (다음 레벨까지 {calculate_xp_to_next_level(user_data['level']) - user_data['xp']} XP 필요)")
                        await assign_role_on_level_up(channel, member, user_data['level'])

                    await save_user_data(user_id, user_data)

@bot.slash_command(name="레벨", description="현재 레벨을 확인합니다.")
async def level(ctx: discord.ApplicationContext):
    user_id = ctx.author.id
    user_data = await load_user_data(user_id)

    if not user_data:
        await ctx.respond(f"{ctx.author.mention}님, 아직 레벨이 없습니다.")
    else:
        current_level = user_data['level']
        current_xp = user_data['xp']
        xp_to_next_level = calculate_xp_to_next_level(current_level)
        await ctx.respond(f"{ctx.author.mention}님의 현재 레벨: {current_level}, 현재 XP: {current_xp}/{xp_to_next_level}")

@bot.slash_command(name="순위", description="서버 리더보드를 확인합니다.")
async def leaderboard(ctx: discord.ApplicationContext):
    guild = ctx.guild
    leaderboard_data = []

    for member in guild.members:
        if not member.bot:
            user_data = await load_user_data(member.id)
            if user_data:
                leaderboard_data.append((member.name, user_data['level'], user_data['xp']))

    leaderboard_data.sort(key=lambda x: (x[1], x[2]), reverse=True)

    top_users = leaderboard_data[:10]

    leaderboard_message = "서버 리더보드 (상위 10명):\n"
    for idx, (name, level, xp) in enumerate(top_users, 1):
        leaderboard_message += f"{idx}. {name} - 레벨 {level} ({xp} XP)\n"

    await ctx.respond(f"```{leaderboard_message}```")

@bot.slash_command(name="지급", description="XP를 지급합니다.")
async def give_xp(ctx: discord.ApplicationContext, member: discord.Member, xp_amount: int):
    if admin_role_id not in [role.id for role in ctx.author.roles]:
        await ctx.respond("이 명령어는 관리자만 사용할 수 있습니다.")
        return

    user_id = member.id
    user_data = await load_user_data(user_id)
    
    user_data['xp'] += xp_amount
    xp_to_next_level = calculate_xp_to_next_level(user_data['level'])

    level_ups = 0
    while user_data['xp'] >= xp_to_next_level:
        user_data['level'] += 1
        level_ups += 1
        user_data['xp'] -= xp_to_next_level
        xp_to_next_level = calculate_xp_to_next_level(user_data['level'])

    if level_ups > 0:
        await ctx.respond(f"{member.mention}님이 {level_ups}레벨 업 했습니다! 현재 레벨: {user_data['level']} (다음 레벨까지 {xp_to_next_level - user_data['xp']} XP 필요)")
        await assign_role_on_level_up(ctx.channel, member, user_data['level'])
    else:
        await ctx.respond(f"{member.mention}님에게 {xp_amount} XP가 추가되었습니다. 현재 XP: {user_data['xp']}/{xp_to_next_level}")

    await save_user_data(user_id, user_data)

@bot.slash_command(name="회수", description="XP를 회수합니다.")
async def remove_xp(ctx: discord.ApplicationContext, member: discord.Member, xp_amount: int):
    if admin_role_id not in [role.id for role in ctx.author.roles]:
        await ctx.respond("이 명령어는 관리자만 사용할 수 있습니다.")
        return

    user_id = member.id
    user_data = await load_user_data(user_id)

    user_data['xp'] -= xp_amount
    current_level = user_data['level']
    
    initial_level = current_level

    while user_data['xp'] < 0 and current_level > 1:
        current_level -= 1
        xp_to_previous_level = calculate_xp_to_next_level(current_level)
        user_data['xp'] += xp_to_previous_level

    if current_level != initial_level:
        user_data['level'] = current_level
        await remove_role_on_level_down(ctx.channel, member, user_data['level'])

    if user_data['xp'] < 0:
        user_data['xp'] = 0

    xp_to_next_level = calculate_xp_to_next_level(user_data['level'])
    
    await ctx.respond(f"{member.mention}님에게서 {xp_amount} XP를 회수했습니다. 현재 레벨: {user_data['level']} (현재 XP: {user_data['xp']}/{xp_to_next_level})")

    await save_user_data(user_id, user_data)

@bot.slash_command(name="훈남봇_설명", description="봇의 기능을 설명합니다.")
async def bot_description(ctx: discord.ApplicationContext):
    description = (
        "**훈남봇 기능 목록:**\n\n"
        "1. **레벨 확인**: `/레벨` 명령어로 자신의 현재 레벨과 경험치를 확인할 수 있습니다.\n"
        "2. **리더보드**: `/순위` 명령어로 서버의 상위 10명 레벨을 확인할 수 있습니다.\n"
        "3. **경험치 지급**: `/지급` 명령어로 특정 사용자에게 경험치를 지급할 수 있습니다. (관리자 전용)\n"
        "4. **경험치 회수**: `/회수` 명령어로 특정 사용자의 경험치를 회수할 수 있습니다. (관리자 전용)\n"
        "기능 추가 예정입니다. 기다려주세요!\n"
    )
    await ctx.respond(description)

@bot.event
async def on_ready():
    await init_db()
    await create_tables()
    print(f'Logged in as {bot.user}!')
    voice_activity_xp.start()

bot_token = os.getenv('DISCORD_BOT_TOKEN')
bot.run(bot_token)
