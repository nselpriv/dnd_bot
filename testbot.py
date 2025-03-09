import discord
from discord.ext import commands
import asyncio
import yt_dlp
from dotenv import load_dotenv
import os
from collections import deque
import logging
import ffmpeg

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
        self.ffmpeg_process = None

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
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process = None

            stream = ffmpeg.input(url, reconnect=1, reconnect_streamed=1, reconnect_delay_max=5 if not is_local else None)
            stream = ffmpeg.filter(stream, 'volume', volume=self.volume)
            stream = ffmpeg.filter(stream, 'atempo', tempo=self.speed)
            stream = ffmpeg.output(stream, 'pipe:', format='s16le', acodec='pcm_s16le', ac=2, ar=48000)
            self.ffmpeg_process = ffmpeg.run_async(stream, pipe_stdout=True, pipe_stderr=True)

            source = discord.PCMAudio(self.ffmpeg_process.stdout)
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))
            logger.info(f"Started playing: {title}")
            return title
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
            self.playing = False
            await self.play_next()

    def adjust_audio(self):
        """Apply volume/speed changes to the current stream with error handling"""
        if self.playing and not self.paused and self.voice_client and self.current_source and self.ffmpeg_process:
            logger.info(f"Adjusting audio - Volume: {self.volume}, Speed: {self.speed}")
            try:
                self.ffmpeg_process.terminate()  # Stop current process
                asyncio.run_coroutine_threadsafe(self.play_next(), client.loop)  # Restart with new settings
            except Exception as e:
                logger.error(f"Failed to adjust audio: {e}")
                self.playing = False  # Reset state on failure

    def cleanup(self):
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
            self.ffmpeg_process = None
        if self.voice_client:
            self.voice_client.stop()
            self.voice_client = None

class AddYouTubeModal(discord.ui.Modal, title="Add YouTube"):
    url_input = discord.ui.TextInput(label="Enter YouTube URL", placeholder="e.g., https://youtube.com/watch?v=...", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild_id = interaction.guild.id
        player = client.get_audio_player(guild_id)
        
        if not player.voice_client and interaction.user.voice and interaction.user.voice.channel:
            player.voice_client = await interaction.user.voice.channel.connect()

        url = self.url_input.value.strip()
        if url:
            try:
                audio_url, title = await get_youtube_audio_url(url)
                is_local = False
                player.queue.append((audio_url, title, is_local))
                if not player.playing:
                    await player.play_next()
                logger.info(f"Added to queue via modal: {title}")
            except Exception as e:
                logger.error(f"Error processing YouTube URL: {e}")
                await interaction.followup.send("Failed to add song: Invalid URL or processing error.", ephemeral=True)

class DirectMusicLinkModal(discord.ui.Modal, title="Direct Music Link"):
    url_input = discord.ui.TextInput(label="Enter Direct URL", placeholder="e.g., http://example.com/audio.mp3", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild_id = interaction.guild.id
        player = client.get_audio_player(guild_id)
        
        if not player.voice_client and interaction.user.voice and interaction.user.voice.channel:
            player.voice_client = await interaction.user.voice.channel.connect()

        url = self.url_input.value.strip()
        if url:
            title = f"Direct Audio ({url})"  # Include the URL in the title for queue display
            is_local = False
            player.queue.append((url, title, is_local))
            if not player.playing:
                await player.play_next()
            logger.info(f"Added to queue via modal: {title}")

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
        
        guild_id = interaction.guild.id
        player = client.get_audio_player(guild_id)
        
        if not player.voice_client and interaction.user.voice and interaction.user.voice.channel:
            player.voice_client = await interaction.user.voice.channel.connect()

        sound_file = self.values[0]
        audio_url = sound_file
        title = sound_file.split('.')[0]
        is_local = True
        
        player.queue.append((audio_url, title, is_local))
        
        if not player.playing:
            await player.play_next()
        logger.info(f"Added to queue: {title}")

class SoundboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SoundboardSelect())

class ControlPanelView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Add YouTube", style=discord.ButtonStyle.green, custom_id="control_add_youtube", row=0)
    async def add_youtube(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddYouTubeModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Direct Music Link", style=discord.ButtonStyle.green, custom_id="control_direct_music_link", row=0)
    async def direct_music_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DirectMusicLinkModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Open Soundboard", style=discord.ButtonStyle.green, custom_id="control_open_soundboard", row=0)
    async def open_soundboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SoundboardView()
        await interaction.response.send_message("Select a sound:", view=view, ephemeral=True)

    @discord.ui.button(label="Show Queue", style=discord.ButtonStyle.secondary, custom_id="control_show_queue", row=1)
    async def show_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        embed = discord.Embed(title="Current Queue", color=discord.Color.blue())
        if player.current_source:
            _, title, _ = player.current_source
            embed.add_field(name="🎵 Now Playing", value=title, inline=False)
        if player.queue:
            for i, (_, title, _) in enumerate(player.queue, 1):
                embed.add_field(name=f"🔢 {i}.", value=title, inline=False)
        else:
            embed.add_field(name="🔍 Queue", value="No songs queued.", inline=False)
        embed.set_footer(text=f"Total queued: {len(player.queue)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Play/Pause", style=discord.ButtonStyle.primary, custom_id="control_play_pause", row=1)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return

        await asyncio.sleep(0.1)  # Small delay to ensure state update
        if player.paused:
            player.voice_client.resume()
            player.paused = False
            button.label = "Pause"
            logger.info(f"Resume button - Playing: {player.playing}, Paused: {player.paused}")
        elif player.playing and player.voice_client.is_playing():
            player.voice_client.pause()
            player.paused = True
            button.label = "Play"
            logger.info(f"Pause button - Playing: {player.playing}, Paused: {player.paused}")
        elif not player.playing and player.queue:
            await player.play_next()
            button.label = "Pause"
            logger.info(f"Play button - Starting next in queue")
        await interaction.response.edit_message(view=self)  # Update the view to reflect label change

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="control_skip", row=1)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client or not player.queue:
            return
        player.voice_client.stop()
        logger.info(f"Skip button - Queue length: {len(player.queue)}")

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, custom_id="control_stop", row=2)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return
        player.cleanup()
        logger.info("Stop button - Playback stopped and queue cleared.")

    @discord.ui.button(label="Vol +", style=discord.ButtonStyle.green, custom_id="control_vol_up", row=3)
    async def volume_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return
        player.volume = min(1.0, player.volume + 0.1)
        player.adjust_audio()
        logger.info(f"Volume up button to {player.volume*100}% - Playing: {player.playing}, Paused: {player.paused}")

    @discord.ui.button(label="Vol -", style=discord.ButtonStyle.red, custom_id="control_vol_down", row=3)
    async def volume_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return
        player.volume = max(0.0, player.volume - 0.1)
        player.adjust_audio()
        logger.info(f"Volume down button to {player.volume*100}% - Playing: {player.playing}, Paused: {player.paused}")

    @discord.ui.button(label="Speed +", style=discord.ButtonStyle.green, custom_id="control_speed_up", row=4)
    async def speed_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return
        player.speed = min(2.0, player.speed + 0.1)
        player.adjust_audio()
        logger.info(f"Speed up button to {player.speed}x - Playing: {player.playing}, Paused: {player.paused}")

    @discord.ui.button(label="Speed -", style=discord.ButtonStyle.red, custom_id="control_speed_down", row=4)
    async def speed_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = client.get_audio_player(interaction.guild.id)
        if not player.voice_client:
            return
        player.speed = max(0.5, player.speed - 0.1)
        player.adjust_audio()
        logger.info(f"Speed down button to {player.speed}x - Playing: {player.playing}, Paused: {player.paused}")

@client.tree.command(name="control", description="Show the control panel for the music bot")
async def control(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    view = ControlPanelView(guild_id)
    client.views[guild_id] = view
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
        await player.play_next()
        await interaction.followup.send(f"Now playing: **{title}**")
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
    title = f"Direct Audio ({url})"
    is_local = False
    
    player.queue.append((audio_url, title, is_local))
    
    if not player.playing:
        await player.play_next()
        await interaction.followup.send(f"Now playing: **{title}**")
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
    
    embed = discord.Embed(title="Current Queue", color=discord.Color.blue())
    if player.current_source:
        _, title, _ = player.current_source
        embed.add_field(name="🎵 Now Playing", value=title, inline=False)
    for i, (_, title, _) in enumerate(player.queue, 1):
        embed.add_field(name=f"🔢 {i}.", value=title, inline=False)
    embed.set_footer(text=f"Total queued: {len(player.queue)}")
    await interaction.response.send_message(embed=embed)

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')
    for guild in client.guilds:
        client.views[guild.id] = ControlPanelView(guild.id)
    for view in client.views.values():
        client.add_view(view)

client.run(TOKEN)