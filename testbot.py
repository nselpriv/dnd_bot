import discord
from discord.ext import commands
import asyncio
import yt_dlp
from dotenv import load_dotenv
import os
from collections import deque
import random

discord.opus.load_opus('/lib/x86_64-linux-gnu/libopus.so.0')
print(discord.opus.is_loaded())

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Intents setup
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

class MyBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.audio_players = {}

    async def setup_hook(self):
        await self.tree.sync()

    def get_audio_player(self, guild_id):
        if guild_id not in self.audio_players:
            self.audio_players[guild_id] = AudioPlayer()
        return self.audio_players[guild_id]

client = MyBot(intents=intents)

class AudioPlayer:
    def __init__(self):
        self.queue = deque()
        self.voice_client = None
        self.current_source = None  # (url/path, title, is_local)
        self.volume = 0.2
        self.speed = 1.0
        self.playing = False
        self.paused = False

    async def play_next(self):
        if not self.queue or not self.voice_client:
            self.playing = False
            return  # Don't disconnect, just stop playing

        self.playing = True
        self.paused = False
        url, title, is_local = self.queue.popleft()
        self.current_source = (url, title, is_local)

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5' if not is_local else '',
            'options': f'-vn -filter:a "volume={self.volume},atempo={self.speed}"'
        }
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))
        return title

class SourceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="YouTube", value="youtube", description="Play from a YouTube URL"),
            discord.SelectOption(label="Direct URL", value="url", description="Play from a direct audio URL"),
            discord.SelectOption(label="Local File", value="local", description="Play a local audio file")
        ]
        super().__init__(placeholder="Choose source type", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.source_type = self.values[0]
        modal = PlayModal()
        await interaction.response.send_modal(modal)

class SourceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.source_type = None
        self.add_item(SourceSelect())

class PlayModal(discord.ui.Modal, title="Enter Audio Source"):
    source_input = discord.ui.TextInput(label="Enter URL or File Name", placeholder="e.g., https://youtube.com/... or sound.mp3", required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("Join a voice channel first!")
            return
        
        guild_id = interaction.guild.id
        player = client.get_audio_player(guild_id)
        
        if not player.voice_client:
            player.voice_client = await interaction.user.voice.channel.connect()

        source = self.source_input.value
        source_type = interaction.message.interaction.view.source_type  # Get source type from the view

        if source_type == "youtube":
            audio_url, title = await get_youtube_audio_url(source)
            is_local = False
        elif source_type == "url":
            audio_url, title = source, "Direct Audio"
            is_local = False
        elif source_type == "local":
            if not os.path.exists(source):
                await interaction.followup.send("Local file not found!")
                return
            audio_url, title = source, os.path.basename(source)
            is_local = True

        player.queue.append((audio_url, title, is_local))
        
        if not player.playing:
            next_title = await player.play_next()
            await interaction.followup.send(f"Now playing: **{next_title}**")
        else:
            await interaction.followup.send(f"Added to queue: **{title}** (Position: {len(player.queue)})")

@client.tree.command(name="play", description="Play audio from various sources")
async def play(interaction: discord.Interaction):
    view = SourceView()
    await interaction.response.send_message("Select a source type:", view=view, ephemeral=True)

async def get_youtube_audio_url(youtube_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return info['url'], info.get('title', 'Unknown Title')

@client.tree.command(name="queue", description="View the current audio queue")
async def queue(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.current_source and not player.queue:
        await interaction.response.send_message("The queue is empty!")
        return
    
    embed = discord.Embed(title="Audio Queue", color=discord.Color.blue())
    if player.current_source:
        _, title, _ = player.current_source
        embed.add_field(name="Now Playing", value=title, inline=False)
    for i, (_, title, _) in enumerate(player.queue, 1):
        embed.add_field(name=f"{i}.", value=title, inline=False)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="volume", description="Set the audio volume (0.0 to 1.0)")
async def volume(interaction: discord.Interaction, volume: float):
    if volume < 0.0 or volume > 1.0:
        await interaction.response.send_message("Volume must be between 0.0 and 1.0!", ephemeral=True)
        return
    
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    player.volume = volume
    if player.playing and not player.paused:
        player.voice_client.stop()
        await player.play_next()
    await interaction.response.send_message(f"Volume set to {volume * 100}%")

@client.tree.command(name="speed", description="Set playback speed (0.5 to 2.0)")
async def speed(interaction: discord.Interaction, speed: float):
    if speed < 0.5 or speed > 2.0:
        await interaction.response.send_message("Speed must be between 0.5 and 2.0!", ephemeral=True)
        return
    
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    player.speed = speed
    if player.playing and not player.paused:
        player.voice_client.stop()
        await player.play_next()
    await interaction.response.send_message(f"Playback speed set to {speed}x")

@client.tree.command(name="stop", description="Stop audio and clear the queue")
async def stop(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    player.voice_client.stop()
    player.queue.clear()
    player.current_source = None
    player.playing = False
    player.paused = False
    await player.voice_client.disconnect()
    player.voice_client = None
    await interaction.response.send_message("Stopped audio and cleared the queue!")

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

client.run(TOKEN)