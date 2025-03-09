import discord
from discord.ext import commands
import asyncio
import yt_dlp
from dotenv import load_dotenv
import os
from collections import deque
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord_bot")

discord.opus.load_opus('/lib/x86_64-linux-gnu/libopus.so.0')
print(discord.opus.is_loaded())

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Intents setup
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True  # Needed for prefix commands if used

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
            logger.info("Queue empty or no voice client, stopping playback.")
            return

        self.playing = True
        self.paused = False
        url, title, is_local = self.queue.popleft()
        self.current_source = (url, title, is_local)
        logger.info(f"Playing next: {title} (URL: {url}, Local: {is_local})")

        try:
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5' if not is_local else '',
                'options': f'-vn -filter:a "volume={self.volume},atempo={self.speed}"'
            }
            source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()  # Stop only if something is playing
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))
            logger.info(f"Started playing: {title}")
            return title
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
            self.playing = False
            await self.play_next()

    def adjust_audio(self):
        """Attempt to adjust audio without full restart if possible"""
        if self.playing and not self.paused and self.voice_client and self.current_source:
            logger.info(f"Attempting to adjust audio - Volume: {self.volume}, Speed: {self.speed}")
            url, title, is_local = self.current_source
            # Note: Real-time adjustment isn't supported well with FFmpegPCMAudio
            # For now, we'll queue a restart with new settings
            if self.voice_client.is_playing():
                self.queue.appendleft((url, title, is_local))  # Re-queue current
                self.voice_client.stop()
                asyncio.run_coroutine_threadsafe(self.play_next(), client.loop)
            logger.info(f"Audio adjustment queued for {title}")

class SoundboardSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Airhorn", value="airhorn.mp3"),
            discord.SelectOption(label="Tada", value="tada.mp3"),
            discord.SelectOption(label="Crickets", value="crickets.mp3"),
            discord.SelectOption(label="Rimshot", value="rimshot.mp3"),
        ]
        super().__init__(placeholder="Choose a sound", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("Join a voice channel first!")
            return

        guild_id = interaction.guild.id
        player = client.get_audio_player(guild_id)
        
        if not player.voice_client:
            player.voice_client = await interaction.user.voice.channel.connect()
        
        sound_file = self.values[0]
        audio_url = sound_file
        title = sound_file.split('.')[0]
        is_local = True
        
        player.queue.append((audio_url, title, is_local))
        
        if not player.playing:
            next_title = await player.play_next()
            await interaction.followup.send(f"Now playing: **{next_title}**")
        else:
            await interaction.followup.send(f"Added to queue: **{title}** (Position: {len(player.queue)})")
        logger.info(f"Added to queue: {title}")

@client.tree.command(name="play-youtube", description="Play audio from YouTube")
async def play_youtube(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first!")
        return
    
    guild_id = interaction.guild.id
    player = client.get_audio_player(guild_id)
    
    if not player.voice_client:
        player.voice_client = await interaction.user.voice.channel.connect()
    
    try:
        audio_url, title = await get_youtube_audio_url(url)
        is_local = False
    except Exception as e:
        await interaction.followup.send(f"Error processing YouTube URL: {str(e)}")
        return
    
    player.queue.append((audio_url, title, is_local))
    
    if not player.playing:
        next_title = await player.play_next()
        await interaction.followup.send(f"Now playing: **{next_title}**")
    else:
        await interaction.followup.send(f"Added to queue: **{title}** (Position: {len(player.queue)})")
    logger.info(f"Added to queue: {title}")

@client.tree.command(name="play-url", description="Play audio from a direct URL")
async def play_url(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first!")
        return
    
    guild_id = interaction.guild.id
    player = client.get_audio_player(guild_id)
    
    if not player.voice_client:
        player.voice_client = await interaction.user.voice.channel.connect()
    
    audio_url = url
    title = "Direct Audio"
    is_local = False
    
    player.queue.append((audio_url, title, is_local))
    
    if not player.playing:
        next_title = await player.play_next()
        await interaction.followup.send(f"Now playing: **{next_title}**")
    else:
        await interaction.followup.send(f"Added to queue: **{title}** (Position: {len(player.queue)})")
    logger.info(f"Added to queue: {title}")

@client.tree.command(name="soundboard", description="Play a sound from the soundboard")
async def soundboard(interaction: discord.Interaction):
    view = SoundboardView()
    await interaction.response.send_message("Select a sound:", view=view, ephemeral=True)

class SoundboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SoundboardSelect())

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
    
    old_volume = player.volume
    player.volume = volume
    player.adjust_audio()
    logger.info(f"Volume changed from {old_volume*100}% to {volume*100}% - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
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
    
    old_speed = player.speed
    player.speed = speed
    player.adjust_audio()
    logger.info(f"Speed changed from {old_speed}x to {speed}x - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
    await interaction.response.send_message(f"Playback speed set to {speed}x")

@client.tree.command(name="skip", description="Skip to the next audio")
async def skip(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    if player.queue:
        player.voice_client.stop()  # This will trigger play_next
        await interaction.response.send_message("Skipped to next track!")
    else:
        await interaction.response.send_message("No more tracks in queue to skip to!")
    logger.info(f"Skip command executed - Queue length: {len(player.queue)}")

@client.tree.command(name="pause", description="Pause the current audio")
async def pause(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client or not player.playing or player.paused:
        await interaction.response.send_message("Nothing is playing or already paused!")
        return
    
    if player.voice_client.is_playing():
        player.voice_client.pause()
        player.paused = True
        await interaction.response.send_message("Audio paused!")
    else:
        await interaction.response.send_message("Nothing is currently playing!")
    logger.info(f"Pause command - Playing: {player.playing}, Paused: {player.paused}")

@client.tree.command(name="resume", description="Resume paused audio")
async def resume(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client or not player.paused:
        await interaction.response.send_message("Nothing is paused!")
        return
    
    player.voice_client.resume()
    player.paused = False
    await interaction.response.send_message("Audio resumed!")
    logger.info(f"Resume command - Playing: {player.playing}, Paused: {player.paused}")

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
    logger.info("Stop command executed - Queue cleared")

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

client.run(TOKEN)