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

class MyBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.audio_players = {}
        self.views = {}  # Store persistent views per guild

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
                self.voice_client.stop()
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))
            logger.info(f"Started playing: {title}")
            return title
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
            self.playing = False
            await self.play_next()

    def adjust_audio(self):
        """Apply volume/speed changes without interrupting playback"""
        if self.playing and not self.paused and self.voice_client and self.current_source:
            logger.info(f"Adjusting audio - Volume: {self.volume}, Speed: {self.speed}")
            # Note: FFmpegPCMAudio doesn't support mid-stream changes well
            # We'll re-queue the current track with new settings
            url, title, is_local = self.current_source
            self.queue.appendleft((url, title, is_local))
            self.voice_client.stop()
            asyncio.run_coroutine_threadsafe(self.play_next(), client.loop)

class ControlPanelView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Play/Pause", style=discord.ButtonStyle.primary, custom_id="control_play_pause")
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
            return

        if player.paused:
            player.voice_client.resume()
            player.paused = False
            await interaction.response.send_message("Audio resumed!")
            logger.info(f"Resume button - Playing: {player.playing}, Paused: {player.paused}")
        elif player.playing and not player.paused:
            if player.voice_client.is_playing():
                player.voice_client.pause()
                player.paused = True
                await interaction.response.send_message("Audio paused!")
                logger.info(f"Pause button - Playing: {player.playing}, Paused: {player.paused}")
            else:
                await interaction.response.send_message("Nothing is currently playing!")
        else:
            await interaction.response.send_message("Nothing is playing to pause/resume!")

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="control_skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        if player.queue:
            player.voice_client.stop()
            await interaction.response.send_message("Skipped to next track!")
        else:
            await interaction.response.send_message("No more tracks in queue to skip to!")
        logger.info(f"Skip button - Queue length: {len(player.queue)}")

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, custom_id="control_stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        player.voice_client.stop()
        player.queue.clear()
        player.current_source = None
        player.playing = False
        player.paused = False
        await player.voice_client.disconnect()
        player.voice_client = None
        await interaction.response.send_message("Stopped audio and cleared the queue!")
        logger.info("Stop button - Queue cleared")

    @discord.ui.button(label="Vol Up", style=discord.ButtonStyle.green, custom_id="control_vol_up")
    async def volume_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        old_volume = player.volume
        player.volume = min(1.0, player.volume + 0.1)
        player.adjust_audio()
        logger.info(f"Volume up button from {old_volume*100}% to {player.volume*100}% - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
        await interaction.response.send_message(f"Volume set to {player.volume * 100}%")

    @discord.ui.button(label="Vol Down", style=discord.ButtonStyle.red, custom_id="control_vol_down")
    async def volume_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        old_volume = player.volume
        player.volume = max(0.0, player.volume - 0.1)
        player.adjust_audio()
        logger.info(f"Volume down button from {old_volume*100}% to {player.volume*100}% - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
        await interaction.response.send_message(f"Volume set to {player.volume * 100}%")

    @discord.ui.button(label="Speed Up", style=discord.ButtonStyle.green, custom_id="control_speed_up")
    async def speed_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        old_speed = player.speed
        player.speed = min(2.0, player.speed + 0.1)
        player.adjust_audio()
        logger.info(f"Speed up button from {old_speed}x to {player.speed}x - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
        await interaction.response.send_message(f"Playback speed set to {player.speed}x")

    @discord.ui.button(label="Speed Down", style=discord.ButtonStyle.red, custom_id="control_speed_down")
    async def speed_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            await interaction.response.send_message("I'm not playing anything!", ephemeral=True)
            return

        old_speed = player.speed
        player.speed = max(0.5, player.speed - 0.1)
        player.adjust_audio()
        logger.info(f"Speed down button from {old_speed}x to {player.speed}x - Playing: {player.playing}, Paused: {player.paused}, Queue: {len(player.queue)}")
        await interaction.response.send_message(f"Playback speed set to {player.speed}x")

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

class SoundboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SoundboardSelect())

@client.tree.command(name="control", description="Show the control panel for the music bot")
async def control(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    view = ControlPanelView(guild_id)
    client.views[guild_id] = view  # Store the view for persistence
    embed = discord.Embed(title="Music Bot Control Panel", description="Use the buttons below to control the bot!", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, view=view)

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

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')
    # Add persistent views on startup
    for guild in client.guilds:
        client.views[guild.id] = ControlPanelView(guild.id)
    for view in client.views.values():
        client.add_view(view)

client.run(TOKEN)