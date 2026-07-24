import os
import discord
import requests
import re
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from discord.ext import commands
from concurrent.futures import ThreadPoolExecutor
from flask import Flask

# ============================================================
# READ TOKEN FROM ENVIRONMENT
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("❌ ERROR: DISCORD_BOT_TOKEN not set!")
    exit(1)

print(f"✅ Token loaded: {TOKEN[:10]}...")

# ============================================================
# BOT SETUP
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)
executor = ThreadPoolExecutor(max_workers=5)

# ============================================================
# FETCH ENGINE
# ============================================================
def fetch_with_timeout(url, timeout=15):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        return requests.get(url, headers=headers, timeout=timeout)
    except:
        return None

def handle_github(url):
    if '/blob/' in url:
        raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
        return fetch_with_timeout(raw_url)
    elif 'raw.githubusercontent.com' in url:
        return fetch_with_timeout(url)
    return None

def handle_pastebin(url):
    if 'pastebin.com' in url:
        if '/raw/' not in url:
            raw_id = url.split('/')[-1]
            raw_url = f'https://pastebin.com/raw/{raw_id}'
        else:
            raw_url = url
        return fetch_with_timeout(raw_url)
    return None

def handle_pastefy(url):
    if 'pastefy.app' in url:
        if '/raw/' in url:
            raw_url = url
        else:
            paste_id = url.rstrip('/').split('/')[-1]
            raw_url = f'https://pastefy.app/raw/{paste_id}'
        return fetch_with_timeout(raw_url)
    return None

def handle_pasters(url):
    if 'paste.rs' in url:
        if '/raw/' not in url:
            paste_id = url.rstrip('/').split('/')[-1]
            raw_url = f'https://paste.rs/raw/{paste_id}'
        else:
            raw_url = url
        return fetch_with_timeout(raw_url)
    return None

def handle_hastebin(url):
    if 'hastebin.com' in url:
        if '/raw/' not in url and '/share/' not in url:
            paste_id = url.rstrip('/').split('/')[-1]
            raw_url = f'https://hastebin.com/raw/{paste_id}'
        else:
            raw_url = url.replace('/share/', '/raw/')
        return fetch_with_timeout(raw_url)
    return None

def handle_codeshare(url):
    if 'codeshare.io' in url:
        code_id = url.rstrip('/').split('/')[-1]
        raw_url = f'https://codeshare.io/raw/{code_id}'
        return fetch_with_timeout(raw_url)
    return None

def fetch_from_any_platform(url):
    handlers = [
        handle_github,
        handle_pastebin,
        handle_pastefy,
        handle_pasters,
        handle_hastebin,
        handle_codeshare,
    ]
    for handler in handlers:
        response = handler(url)
        if response and response.status_code == 200:
            return response
    return fetch_with_timeout(url)

def detect_platform(url):
    platforms = ['github', 'pastebin', 'pastefy', 'paste.rs', 'hastebin', 'codeshare.io']
    for p in platforms:
        if p in url.lower():
            return p
    return "unknown"

# ============================================================
# JUNKIE & POLSEC DETECTORS
# ============================================================
JUNKIE_PATTERNS = [
    r'junkie\(.*?\)',
    r'__junkie_loader__',
    r'junkie\.init',
    r'JunkieRuntime',
    r'junkie_payload',
]

POLSEC_PATTERNS = [
    r'polsec\(.*?\)',
    r'PolsecSecurity',
    r'polsec\.verify',
    r'POLSEC_TOKEN',
    r'polsec_auth',
]

def detect_junkie(script):
    return any(re.search(p, script, re.IGNORECASE) for p in JUNKIE_PATTERNS)

def detect_polsec(script):
    return any(re.search(p, script, re.IGNORECASE) for p in POLSEC_PATTERNS)

def extract_junkie_script(script):
    matches = []
    for pattern in JUNKIE_PATTERNS:
        found = re.findall(pattern, script, re.IGNORECASE)
        matches.extend(found)
    if matches:
        return f"**Junkie System Detected**\nSignatures: {', '.join(matches[:5])}\n```js\n{script[:1000]}\n```"
    return None

def extract_polsec_script(script):
    matches = []
    for pattern in POLSEC_PATTERNS:
        found = re.findall(pattern, script, re.IGNORECASE)
        matches.extend(found)
    if matches:
        return f"**Polsec Module Detected**\nSignatures: {', '.join(matches[:5])}\n```js\n{script[:1000]}\n```"
    return None

def simple_deobfuscate(code):
    """Simple deobfuscation without js2py"""
    code = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), code)
    code = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), code)
    code = re.sub(r'eval\(([^)]+)\)', r'console.log(\1)', code)
    code = re.sub(r'atob\(([^)]+)\)', lambda m: f'Buffer.from({m.group(1)}, "base64").toString()', code)
    return code[:1900]

# ============================================================
# DISCORD COMMANDS
# ============================================================
@bot.command()
async def get(ctx, link: str = None):
    """Fetch code from URL and detect junkie/polsec"""
    if not link:
        await ctx.send("❌ Usage: `.get <url>`\nExample: `.get https://pastebin.com/raw/abc123`")
        return
    
    if not link.startswith(('http://', 'https://')):
        link = 'https://' + link
    
    platform = detect_platform(link)
    await ctx.send(f"🔍 Fetching from {platform.upper()}: {link}")
    
    def fetch_task():
        response = fetch_from_any_platform(link)
        if not response or response.status_code != 200:
            return "❌ Failed to fetch content"
        
        content = response.text
        result = f"**Platform:** {platform.upper()}\n```js\n{content[:1900]}\n```"
        
        if detect_junkie(content):
            result += "\n" + extract_junkie_script(content)
        if detect_polsec(content):
            result += "\n" + extract_polsec_script(content)
        
        return result
    
    result = await bot.loop.run_in_executor(executor, fetch_task)
    for chunk in [result[i:i+1900] for i in range(0, len(result), 1900)]:
        await ctx.send(chunk)

@bot.command()
async def l(ctx, *, code_input: str = None):
    """Deobfuscate JavaScript code or URL"""
    if not code_input:
        await ctx.send("❌ Usage: `.l <code or url>`\nExample: `.l https://pastebin.com/raw/abc123`\nOr: `.l eval('alert(1)')`")
        return
    
    if code_input.startswith(('http', 'www')):
        if not code_input.startswith('http'):
            code_input = 'https://' + code_input
        response = fetch_from_any_platform(code_input)
        if response and response.status_code == 200:
            code_input = response.text[:5000]
            await ctx.send(f"✅ Fetched from {detect_platform(code_input)}")
        else:
            await ctx.send("❌ Failed to fetch URL")
            return
    
    deobfuscated = simple_deobfuscate(code_input)
    final = f"**Deobfuscated output:**\n```js\n{deobfuscated}\n```"
    
    if detect_junkie(deobfuscated):
        final += "\n⚠️ **Junkie signature persists**"
    if detect_polsec(deobfuscated):
        final += "\n⚠️ **Polsec signature persists**"
    
    await ctx.send(final[:2000])

@bot.event
async def on_ready():
    logger.info(f"✅ Bot online: {bot.user}")
    print(f"✅ Bot online: {bot.user}")
    print(f"📝 Commands: .get <url> | .l <code or url>")

# ============================================================
# FLASK WEB SERVER
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🐟 CAT Bot is running! Commands: .get, .l"

@app.route('/health')
def health():
    return "OK", 200

# ============================================================
# RUN BOTH
# ============================================================
if __name__ == "__main__":
    import threading
    
    def run_bot():
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"❌ Bot error: {e}")
    
    threading.Thread(target=run_bot, daemon=True).start()
    print("🌐 Starting web server...")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
