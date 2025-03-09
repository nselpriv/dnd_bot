import discord
from discord.ext import commands
import asyncio
import yt_dlp
from dotenv import load_dotenv
from discord.ui import Select, View
from discord.ext.commands import Bot
import os
from collections import deque
import asyncio

discord.opus.load_opus('/lib/x86_64-linux-gnu/libopus.so.0')

print(discord.opus.is_loaded())

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD') 

# Intents setup
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

class AudioPlayer:
    """Manages audio playback state for a guild."""
    def __init__(self):
        self.queue = deque()  # Queue of (URL, title) tuples
        self.voice_client = None
        self.current_url = None
        self.volume = 0.2  # Default volume (0.0 to 1.0)
        self.speed = 1.0  # Default speed (1.0 = normal)
        self.playing = False
        self.paused = False

    async def play_next(self):
        """Plays the next item in the queue."""
        if not self.queue or not self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None
            self.playing = False
            return
                
        self.playing = True
        self.paused = False
        url, title = self.queue.popleft()
        self.current_url = url

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': f'-vn -filter:a "volume={self.volume},atempo={self.speed}"'  # Volume and speed
        }
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))
        return title

class MyBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.death_rolls = {}
        self.audio_players = {}  # Guild ID -> AudioPlayer

    async def setup_hook(self):
        await self.tree.sync()

    def get_audio_player(self, guild_id):
        """Get or create an AudioPlayer for a guild."""
        if guild_id not in self.audio_players:
            self.audio_players[guild_id] = AudioPlayer()
        return self.audio_players[guild_id]

client = MyBot(intents=intents)

async def get_youtube_audio_url(youtube_url):
    """Extract a streamable audio URL and title from a YouTube link."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return info['url'], info.get('title', 'Unknown Title')

@client.tree.command(name="play", description="Add a YouTube URL to the audio queue and play it")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first!")
        return
    
    guild_id = interaction.guild.id
    player = client.get_audio_player(guild_id)
    
    # Connect to voice channel if not already connected
    if not player.voice_client:
        player.voice_client = await interaction.user.voice.channel.connect()
    
    # Get the audio URL and title
    audio_url, title = await get_youtube_audio_url(url)
    player.queue.append((audio_url, title))
    
    if not player.playing:
        next_title = await player.play_next()
        await interaction.followup.send(f"Now playing: **{next_title}**")
    else:
        await interaction.followup.send(f"Added to queue: **{title}** (Position: {len(player.queue)})")

@client.tree.command(name="queue", description="View the current audio queue")
async def queue(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.queue and not player.current_url:
        await interaction.response.send_message("The queue is empty!")
        return
    
    embed = discord.Embed(title="Audio Queue", color=discord.Color.blue())
    if player.current_url:
        embed.add_field(name="Now Playing", value=player.queue[0][1] if player.queue else "Unknown", inline=False)
    for i, (_, title) in enumerate(player.queue, 1):
        embed.add_field(name=f"{i}.", value=title, inline=False)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="volume", description="Set the audio volume (0.0 to 1.0)")
async def volume(interaction: discord.Interaction, volume: float):
    if volume < 0.0:
        await interaction.response.send_message("Volume must be at least 0.0!", ephemeral=True)
        return
    if volume > 1.0:
        await interaction.response.send_message("Volume must be at most 1.0!", ephemeral=True)
        return
    
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    player.volume = volume
    if player.playing and not player.paused:
        # Restart current song with new volume
        player.voice_client.stop()
        await player.play_next()
    await interaction.response.send_message(f"Volume set to {volume * 100}%")

@client.tree.command(name="pause", description="Pause the current audio")
async def pause(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.playing or player.paused:
        await interaction.response.send_message("Nothing is playing or it's already paused!")
        return
    
    player.voice_client.pause()
    player.paused = True
    await interaction.response.send_message("Paused the audio!")

@client.tree.command(name="resume", description="Resume paused audio")
async def resume(interaction: discord.Interaction):
    player = client.get_audio_player(interaction.guild.id)
    if not player.paused:
        await interaction.response.send_message("Audio is not paused!")
        return
    
    player.voice_client.resume()
    player.paused = False
    await interaction.response.send_message("Resumed the audio!")

@client.tree.command(name="speed", description="Set playback speed (0,5 to 2,0)")
async def speed(interaction: discord.Interaction, speed: float):
    if speed < 0.5:
        await interaction.response.send_message("Speed must be at least 0.5!", ephemeral=True)
        return
    if speed > 2.0:
        await interaction.response.send_message("Speed must be at most 2.0!", ephemeral=True)
        return
    
    player = client.get_audio_player(interaction.guild.id)
    if not player.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return
    
    player.speed = speed
    if player.playing and not player.paused:
        # Restart current song with new speed
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
    player.playing = False
    player.paused = False
    await player.voice_client.disconnect()
    await interaction.response.send_message("Stopped audio and cleared the queue!")

# Integrate with jungle-rest
@client.tree.command(name="jungle-rest", description="Take a rest with jungle sounds from YouTube!")
async def jungle_rest(interaction: discord.Interaction):
    number = random.randint(1, 2)
    message = "1 hit die, long rest resource or spell slot restored" if number == 1 else "2 hit die, long rest resource or spell slot restored"
    
    embed = discord.Embed(
        title="Jungle Rest 🌴",
        description=message,
        color=discord.Color.green()
    )
    embed.set_footer(text=f'Jungle rest rolled {number}!')
    
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(embed=embed, content="Join a voice channel to hear jungle sounds!")
        return
    
    guild_id = interaction.guild.id
    player = client.get_audio_player(guild_id)
    
    if not player.voice_client:
        player.voice_client = await interaction.user.voice.channel.connect()
    
    youtube_url = "https://www.youtube.com/watch?v=KEI4qSrkPAs"  # Jungle ambiance
    audio_url, title = await get_youtube_audio_url(youtube_url)
    player.queue.append((audio_url, title))
    
    if not player.playing:
        next_title = await player.play_next()
        await interaction.response.send_message(embed=embed, content=f"Now playing: **{next_title}**")
    else:
        await interaction.response.send_message(embed=embed, content=f"Added to queue: **{title}**")

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

client.run(TOKEN)