import os
import discord
from discord.ext import commands
from flask import Flask

# Get token - if missing, use a default (you'll see error)
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("❌ ERROR: DISCORD_BOT_TOKEN not set!")
    print("Go to Render dashboard → Environment → Add DISCORD_BOT_TOKEN")
    exit(1)

print(f"✅ Token loaded: {TOKEN[:10]}...")

# Setup bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot is online! Logged in as {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@bot.command()
async def hello(ctx):
    await ctx.send("🐟 CAT says hello!")

# Flask web server
app = Flask(__name__)

@app.route('/')
def home():
    return "🐟 CAT Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# Run both
if __name__ == "__main__":
    import threading
    
    # Start bot in background
    def run_bot():
        bot.run(TOKEN)
    
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Start web server
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Web server on port {port}")
    app.run(host="0.0.0.0", port=port)
