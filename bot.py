import os
import random
import discord
from discord.ext.commands import Bot
from discord.ui import Select, View
from dotenv import load_dotenv
import string


load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD') 

intents = discord.Intents.default()
intents.guilds = True

class MyBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.death_rolls = {}  

    async def setup_hook(self):

        g = discord.Object(id=503949236325580801)
        await self.tree.sync(guild=g)

client = MyBot(intents=intents)

# Slash command
@client.tree.command(name="roll", description="Roll a random number between 0 and the given number")
async def roll(interaction: discord.Interaction, number: int):
    if number <= 0:
        await interaction.response.send_message("Please provide a positive number!", ephemeral=True)
        return
    result = random.randint(1, number)
    embed = discord.Embed(
        title="Roll 🎲",
        description=f"{interaction.user.display_name} rolled: **{result}** on a d{number}",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Standard roll")
    await interaction.response.send_message(embed=embed)


# Slash command for Jungle Rest
@client.tree.command(name="jungle-rest", description="Take a rest in the jungle and receive a surprise!")
async def jungle_rest(interaction: discord.Interaction):

    number = random.randint(1, 2)

    # Different responses based on the number
    if number == 1:
        message = "1 hit die, long rest resource or spell slot restored"
    elif number == 2:
        message = "2 hit die, long rest resource or spell slot restored"

    # Send the response as an embedded message
    embed = discord.Embed(
        title="Jungle Rest 🌴",
        description=message,
        color=discord.Color.green()
    )
    thingy = f'Jungle rest rolled {number}!'
    embed.set_footer(text=thingy)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="death-roll", description="Roll death saves")
async def death_roll(interaction: discord.Interaction):
    user = interaction.user
    number = random.randint(1, 20)
    
    # Ensure we have a death roll state for the user
    if user.id not in client.death_rolls:
        client.death_rolls[user.id] = {"successes": 0, "failures": 0}
    
    # Determine the result of the death roll
    message = selectionLogic(number, user)

    death_state = client.death_rolls[user.id]

        # Check if the player is dead or up after the roll
    if death_state["failures"] >= 3:
        message = f"{user.mention} has died! 💀 You failed 3 death saves."
        client.death_rolls[user.id] = {"successes": 0, "failures": 0}
    if death_state["successes"] >= 3:
        message = f"{user.mention} is stabilized! 😴 You succeeded 3 death saves."
        client.death_rolls[user.id] = {"successes": 0, "failures": 0}

    embed = discord.Embed(
        title="Death roll ☠️",
        description=message,
        color=discord.Color.red()
    )


    thingy = f'Death roll on a {number}!'
    embed.set_footer(text=thingy)
    await interaction.response.send_message(embed=embed)

def selectionLogic(n: int, user) -> str:
    # Access the user's death roll state
    death_state = client.death_rolls[user.id]
    
    # Handle the different roll outcomes
    if n == 1:
        death_state["failures"] += 2
        return f"Two failed death saves! {user.mention}, you now have {death_state['failures']} failure(s)."
    
    if n == 20:
        death_state["successes"] += 3
        client.death_rolls[user.id] = {"successes": 0, "failures": 0}
        return f"Regain one health, you're up! 🍀🍀🍀 {user.mention}."
    
    if 2 <= n <= 9: # Failure
        death_state["failures"] += 1
         # Failure
        return f"One failed death save! {user.mention}, you now have {death_state['failures']} failure(s)."
    
    if 10 <= n <= 19:  # Success
        death_state["successes"] += 1
        return f"One succeeded death save! {user.mention}, you now have {death_state['successes']} success(es)."

# Slash command to reset the player's state to "up" manually
@client.tree.command(name="up", description="Revive yourself if you have 3 success rolls or you somehow figured out how not to die!")
async def up(interaction: discord.Interaction):
    user = interaction.user
    
    if user.id not in client.death_rolls:
        client.death_rolls[user.id] = {"successes": 0, "failures": 0}
    
    death_state = client.death_rolls[user.id]
    
    death_state["successes"] = 0
    death_state["failures"] = 0

    await interaction.response.send_message(f"{user.mention}, you're back up! You're fully revived and ready to fight! 💪")


@client.tree.command(name="clear-bot-posts", description="Delete all posts made by the bot in this channel")
async def clear_bot_posts(interaction: discord.Interaction):
    # Ensure the bot has permission to delete messages
    channel = interaction.channel

    if not channel.permissions_for(interaction.guild.me).manage_messages:
        await interaction.response.send_message("I don't have permission to delete messages in this channel.", ephemeral=True)
        return

    # Fetch the bot's previous messages
    deleted_count = 0
    async for message in channel.history(limit=250):  # Adjust limit if needed
        if message.author == client.user:
            await message.delete()
            deleted_count += 1

    # Respond to the user
    if deleted_count > 0:
        await interaction.response.send_message(f"Deleted {deleted_count} messages made by the bot.", ephemeral=True)
    else:
        await interaction.response.send_message("No messages from the bot found in this channel.", ephemeral=True)

# Gibberish message generator
def gibberish_message(message: str) -> str:
    return ''.join(random.choice(string.ascii_letters + string.digits) if random.random() < 0.7 else c for c in message)

# Dropdown select for languages
class LanguageSelect(Select):
    def __init__(self):
        # Options for the dropdown (languages)
        options = [
            discord.SelectOption(label="Undercommon", value="Undercommon"),
            discord.SelectOption(label="Celestial", value="Celestial"),
            discord.SelectOption(label="Giant", value="Giant"),
            discord.SelectOption(label="Elvish", value="Elvish"),
            discord.SelectOption(label="Dwarvish", value="Dwarvish"),
            discord.SelectOption(label="Goblin", value="Goblin"),
            discord.SelectOption(label="Thieves' Cant", value="Thieves' Cant"),
            discord.SelectOption(label="Common Sign Language", value="Common Sign Language"),
            discord.SelectOption(label="Old Omuan", value="Old Omuan"),

        ]
        super().__init__(placeholder="Choose a language...", min_values=1, max_values=1, options=options)


    async def callback(self, interaction: discord.Interaction):
        language = self.values[0]  # Get selected language
        content = self.message.content  # Get the message content (the secret message)

        titl = f'{language} Message'

        # Send the message to the entire guild, checking the role of each member
        for member in interaction.guild.members:
            required_role_name = language
            user_has_role = False
            
            if("Spiller" not in member.roles):
                continue

            # Check if the user has the required role
            for role in member.roles:
                if role.name.lower() == required_role_name.lower():
                    user_has_role = True
                    break
            
            # Prepare the message based on role
            if user_has_role:
                message = f"**{content}**"  # Show original message if they have the role
            else:
                message = gibberish_message(content)  # Show gibberish if they don't have the role

            # Send the personalized message
            embed = discord.Embed(
                title=titl,
                description=message,
                color=discord.Color.blue() if user_has_role else discord.Color.red()
            )
            try:
                await member.send(embed=embed)  # Send the message via DM to each member
            except discord.Forbidden:
                # Handle case where DMs are disabled for a user
                print(f"Couldn't DM {member.name}, they may have DMs disabled.")
        
        # Acknowledge the command was executed
        await interaction.response.send_message("The message has been sent to everyone in the guild (via DM).")

# Command to post a secret message
@client.tree.command(name="switch-language", description="Post a secret message that only specific users can read")
async def reveal_message(interaction: discord.Interaction, content: str):
    # Create a dropdown view
    view = View(timeout=None)  # Set timeout as None for the dropdown to stay open
    select = LanguageSelect()
    view.add_item(select)

    # Set the content of the message to display in the dropdown
    select.message = content  # Store the content on the select dropdown
    
    # Send a prompt message to the channel with the dropdown
    await interaction.response.send_message("Choose a language to send the message in:", view=view)

@client.event
async def on_ready():
    for guild in client.guilds:
        if guild.name == GUILD:  # Match by server name
            print(
                f'{client.user} is connected to the following guild:\n'
                f'{guild.name} (id: {guild.id})'
            )
            break
    else:
        print(f"{client.user} is not connected to the specified guild: {GUILD}")

client.run(TOKEN)