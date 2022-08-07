from io import BytesIO
import os
import aiohttp
import discord
import datetime
import warnings
from discord import app_commands
import requests
import pymongo
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

mongo = MongoClient(os.getenv('MONGODB_URI'))

testdb = mongo.test

db = mongo['meow']
banwords = db['banwords']
settings = db['settings']

intents = discord.Intents.default()
intents.message_content = True

wordlist = {}
def update_wordlist():
    wordlist.clear()
    for word in banwords.find().sort('word'):
        try:
            wordlist[word['guild']]
        except KeyError:
            wordlist[word['guild']] = []
        wordlist[word['guild']].append(word['word'])

    print("updated wordlist")


guildsettings = {}
def update_settings():
    for s in settings.find():
        guildsettings[s['guild']] = s

    print("updated settings")


update_wordlist()
update_settings()

MY_GUILD = discord.Object(id=787168726352003083)

class BotClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    
    async def setup_hook(self) -> None:
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync()

client = BotClient(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}.")
    print("---------------------------")

@client.tree.command(description="차단할 단어를 추가합니다.")
@app_commands.describe(
    word="차단할 단어를 입력하세요."
)
async def add_banword(interaction: discord.Interaction, word: str):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("권한이 없습니다.")
    word = word.strip()
    exists = banwords.find_one({"word": word, "guild": str(interaction.guild_id)})
    if exists != None:
        return await interaction.response.send_message(f"**[{word}]** 단어는 이미 차단 목록에 있습니다.")

    try:
        guildsettings[str(interaction.guild_id)]
    except KeyError:
        return await interaction.response.send_message("먼저 /set_timeout 명령어를 사용하여 타임아웃 시간을 먼저 등록해 주세요.")
    
    banwords.insert_one({
        'word': word,
        'by': str(interaction.user),
        'guild': str(interaction.guild_id)
    })
    update_wordlist()
    return await interaction.response.send_message(f"**[{word}]** 단어가 차단 목록에 추가되었습니다.")
    
@client.tree.command(description="차단 단어 목록을 삭제합니다.")
@app_commands.describe(word="차단을 해제할 단어를 입력하세요.")
async def delete_banword(interaction: discord.Interaction, word: str):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("권한이 없습니다.")
    word = word.strip()
    exists = banwords.find_one({"word": word})
    if exists == None:
        return await interaction.response.send_message(f"**[{word}]** 단어는 차단 목록에 없습니다.")
    
    banwords.delete_many({"guild": str(interaction.guild_id), "word": word})
    update_wordlist()
    return await interaction.response.send_message(f"**[{word}]** 단어가 차단 목록에서 제거되었습니다.")


@client.tree.command(description="타임아웃 시간을 설정합니다.")
@app_commands.describe(
    time="타임아웃 길이"
)
async def set_timeout(interaction: discord.Interaction, time: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("권한이 없습니다.")
    setting = settings.find_one({"guild": str(interaction.guild_id)})
    if not setting:
        setting = {
            "guild": str(interaction.guild_id),
        }
        setting['timeout'] = time
        settings.insert_one(setting)
        update_settings()
    else:
        setting['timeout'] = time
        settings.update_one({"guild": str(interaction.guild_id)}, {"$set": setting})
        update_settings()
    
    return await interaction.response.send_message(f"타임아웃이 {time}초로 설정되었습니다.")

@client.tree.command(description="차단 단어 목록을 표시합니다.")
async def ban_words(interaction: discord.Interaction):
    result = ""
    for w in banwords.find({"guild": str(interaction.guild_id)}).sort("word"):
        result += f"{w['word']} - by {w['by']}\n"
    if result == "":
        result = "차단 단어가 없습니다."
    return await interaction.response.send_message(file=discord.File(BytesIO(bytes(result, encoding='utf8')), "words.txt"))

@client.tree.command(description="초대 링크를 표시합니다.")
async def invite_link(interaction: discord.Interaction):
    return await interaction.response.send_message(f"https://discord.com/api/oauth2/authorize?client_id=749263283265077308&permissions=8&scope=bot%20applications.commands")

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    if message.content.startswith("$$"):
        try:
            num = int(message.content[2:].strip())
        except ValueError:
            return await message.reply("숫자여야합니다.")
        if num > 10:
            return await message.reply("최대 10개의 메시지를 선택할 수 있습니다.")
        if num<2:
            return await message.reply("2 이상으로 입력해주세요.")
        if message.reference is None:
            return await message.reply("답장하세요.")
        chats = []
        original = await message.channel.fetch_message(message.reference.message_id)
        if original.content != "":
            chats.append({
                "nickname": original.author.display_name,
                "content": original.content
            })
        async for m in message.channel.history(
            limit=num-1, oldest_first=True, 
            after=original.created_at
        ):
            if m.content == "":
                continue
            chats.append({
                "nickname": m.author.display_name,
                "content": m.content
            })
        with requests.post('http://localhost:5050/generate', json=chats) as r:
            r.raise_for_status()
            filename = f"{datetime.datetime.timestamp(datetime.datetime.now())}.mp4"
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        await message.channel.send(file=discord.File(filename))
        os.remove(filename)
        return

    try:
        for w in wordlist[str(message.guild.id)]:
            if w in message.content:
                await message.author.timeout(datetime.timedelta(seconds=guildsettings[str(message.guild.id)]['timeout']), reason=f"금지 단어 사용: {w}")
                return await message.reply(f"금지 단어 [**{w}**]을/를 사용하여 {guildsettings[str(message.guild.id)]['timeout']}초 동안 **{message.author}**님은 채팅이 금지됩니다.")
    except KeyError:
        return

        
client.run(os.getenv("DISCORD_TOKEN"))