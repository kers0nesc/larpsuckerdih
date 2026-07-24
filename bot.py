#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAT v4.1 - ULTRA DEBUG
"""

import os
import sys
import traceback
import logging

# ============================================================
# STEP 1: SHOW ALL ENVIRONMENT VARIABLES
# ============================================================
print("=" * 60)
print("ENVIRONMENT VARIABLES CHECK:")
print("=" * 60)

# Show ALL env vars (masked for security)
for key in sorted(os.environ.keys()):
    value = os.environ[key]
    if "TOKEN" in key.upper() or "KEY" in key.upper() or "SECRET" in key.upper():
        print(f"  {key}: {value[:10]}... (length: {len(value)})")
    else:
        print(f"  {key}: {value[:30]}{'...' if len(value) > 30 else ''}")

print("=" * 60)

# ============================================================
# STEP 2: TRY MULTIPLE TOKEN SOURCES
# ============================================================
BOT_TOKEN = None

# Try every possible token variable name
token_vars = [
    "DISCORD_BOT_TOKEN",
    "DISCORD_TOKEN", 
    "TOKEN",
    "BOT_TOKEN",
    "DISCORD_BOT_SECRET",
    "DISCORD_SECRET"
]

for var in token_vars:
    val = os.environ.get(var)
    if val:
        print(f"✅ Found token in {var}: {val[:10]}... (length: {len(val)})")
        BOT_TOKEN = val
        break

if not BOT_TOKEN:
    print("❌ NO TOKEN FOUND in any environment variable!")
    print("   Tried:", ", ".join(token_vars))
    print("")
    print("   Please set DISCORD_BOT_TOKEN in Render Environment Variables")
    print("   Then click 'Manual Deploy' -> 'Deploy latest commit'")
    sys.exit(1)

print("=" * 60)

# ============================================================
# STEP 3: CONTINUE WITH IMPORTS
# ============================================================
try:
    import re
    import requests
    from flask import Flask, request, jsonify, render_template_string
    from discord.ext import commands
    import discord
    from concurrent.futures import ThreadPoolExecutor
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# STEP 4: CONFIGURATION
# ============================================================
COMMAND_PREFIX = os.environ.get("BOT_PREFIX", ".")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 8))
FETCH_TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", 15))
MAX_CHUNK_SIZE = 1900
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("PORT", 5000))

# ============================================================
# STEP 5: LOGGING
# ============================================================
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("CAT_BOT")
logger.info("=== CAT BOT STARTING ===")

# ============================================================
# STEP 6: FLASK APP
# ============================================================
app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# ============================================================
# STEP 7: FETCH ENGINE
# ============================================================
def fetch_text_sync(url: str):
    try:
        resp = requests.get(url, headers={"User-Agent": "CAT-Bot/4.1"}, timeout=FETCH_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.error(f"Fetch error {url}: {e}")
    return None

# ============================================================
# STEP 8: URL NORMALIZERS
# ============================================================
def normalize_url(url: str) -> str:
    if "raw.githubusercontent.com" in url:
        return url
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    if "pastebin.com" in url and "/raw/" not in url:
        pid = url.rstrip("/").split("/")[-1]
        return f"https://pastebin.com/raw/{pid}"
    if "pastefy.app" in url and "/raw/" not in url:
        pid = url.rstrip("/").split("/")[-1]
        return f"https://pastefy.app/raw/{pid}"
    if "paste.rs" in url and "/raw/" not in url:
        pid = url.rstrip("/").split("/")[-1]
        return f"https://paste.rs/raw/{pid}"
    if "hastebin.com" in url:
        if "/raw/" not in url and "/share/" not in url:
            pid = url.rstrip("/").split("/")[-1]
            return f"https://hastebin.com/raw/{pid}"
        return url.replace("/share/", "/raw/")
    if "codeshare.io" in url:
        pid = url.rstrip("/").split("/")[-1]
        return f"https://codeshare.io/raw/{pid}"
    return url

# ============================================================
# STEP 9: JUNKIE / POLSEC DETECTORS
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

def detect_junkie(code: str) -> bool:
    return any(re.search(p, code, re.IGNORECASE) for p in JUNKIE_PATTERNS)

def detect_polsec(code: str) -> bool:
    return any(re.search(p, code, re.IGNORECASE) for p in POLSEC_PATTERNS)

def static_deobfuscate(code: str) -> str:
    code = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), code)
    code = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), code)
    code = re.sub(r'eval\(([^)]+)\)', r'console.log(\1)', code)
    code = re.sub(r'atob\(([^)]+)\)', lambda m: f'Buffer.from({m.group(1)}, "base64").toString()', code)
    if detect_junkie(code):
        code = re.sub(r'junkie\(([^)]+)\)', r'/* JUNKIE_UNPACKED: \1 */', code)
    if detect_polsec(code):
        code = re.sub(r'polsec\.verify\(([^)]+)\)', r'/* POLSEC_VERIFIED: \1 */', code)
    return code

def extract_from_url(url: str) -> dict:
    raw_url = normalize_url(url)
    content = fetch_text_sync(raw_url)
    if not content:
        content = fetch_text_sync(url)
        if not content:
            return {"error": "Failed to fetch content"}

    result = {
        "raw": content[:MAX_CHUNK_SIZE],
        "junkie": detect_junkie(content),
        "polsec": detect_polsec(content),
        "deobfuscated": static_deobfuscate(content)[:MAX_CHUNK_SIZE],
        "source_hint": search_source_repo(content),
    }
    return result

def search_source_repo(code: str) -> str:
    keywords = {
        'jquery': 'jQuery (cdnjs)',
        'axios': 'Axios (GitHub)',
        'react': 'React (unpkg)',
        'vue': 'Vue.js (cdnjs)',
        'lodash': 'Lodash (GitHub)',
        'junkie': '⚠️ Junkie internal loader',
        'polsec': '⚠️ Polsec security module',
    }
    for name, label in keywords.items():
        if name in code.lower():
            return f"Possible: {label}"
    return "Unknown source"

# ============================================================
# STEP 10: DISCORD BOT
# ============================================================
try:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
    print("✅ Discord bot instance created")
except Exception as e:
    print(f"❌ Failed to create bot: {e}")
    traceback.print_exc()
    sys.exit(1)

@bot.event
async def on_ready():
    logger.info(f"✅ Bot logged in as {bot.user}")
    print(f"✅ Bot logged in as {bot.user}")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Error in {event}: {traceback.format_exc()}")
    print(f"❌ Error in {event}")

@bot.command()
async def get(ctx, link: str):
    if not link.startswith(('http://', 'https://')):
        link = 'https://' + link
    await ctx.send(f"🔍 Fetching: {link}")
    result = await bot.loop.run_in_executor(executor, extract_from_url, link)
    if "error" in result:
        await ctx.send(f"❌ {result['error']}")
        return
    msg = f"**Source:** {result['source_hint']}\n"
    msg += f"**Junkie:** {'⚠️ YES' if result['junkie'] else '✅ NO'}\n"
    msg += f"**Polsec:** {'⚠️ YES' if result['polsec'] else '✅ NO'}\n"
    msg += f"```js\n{result['raw'][:1500]}\n```"
    await ctx.send(msg[:2000])

@bot.command()
async def l(ctx, *, code_input: str):
    if code_input.startswith(('http://', 'https://', 'www.')):
        if not code_input.startswith('http'):
            code_input = 'https://' + code_input
        content = fetch_text_sync(normalize_url(code_input))
        if not content:
            content = fetch_text_sync(code_input)
        if content:
            code_input = content
        else:
            await ctx.send("❌ Failed to fetch URL")
            return
    deobf = static_deobfuscate(code_input)
    await ctx.send(f"```js\n{deobf[:1900]}\n```")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="🐟 CAT Bot v4.1", color=0x00ff88)
    embed.add_field(name=".get <url>", value="Fetch & detect junkie/polsec", inline=False)
    embed.add_field(name=".l <code or url>", value="Static deobfuscate", inline=False)
    embed.add_field(name=".help", value="This menu", inline=False)
    await ctx.send(embed=embed)

# ============================================================
# STEP 11: FLASK ROUTES
# ============================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>CAT v4.1</title>
<style>
body{font-family:monospace;background:#0d0d0d;color:#00ff88;padding:20px}
.container{max-width:1000px;margin:auto}
textarea,input{width:100%;padding:10px;background:#1a1a1a;color:#00ff88;border:1px solid #00ff88}
button{background:#00ff88;color:#0d0d0d;padding:10px 20px;border:none;cursor:pointer;margin:5px}
.result{background:#1a1a1a;padding:15px;margin-top:20px;white-space:pre-wrap;overflow:auto;max-height:600px}
</style>
</head>
<body>
<div class=container>
<h1>🐟 CAT v4.1 — Deobfuscator</h1>
<form id=fetchForm>
<input type=text id=urlInput placeholder="URL (GitHub, Pastebin, etc.)">
<button type=submit>Fetch & Detect</button>
</form>
<hr>
<form id=deobfForm>
<textarea id=codeInput rows=8 placeholder="Paste code or URL..."></textarea>
<button type=submit>⚡ Deobfuscate</button>
</form>
<div id=result class=result>Results will appear here...</div>
</div>
<script>
async function apiCall(endpoint,data){
const res=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
return res.json();}
document.getElementById('fetchForm').onsubmit=async(e)=>{
e.preventDefault();
const url=document.getElementById('urlInput').value;
const res=await apiCall('/api/fetch',{url});
document.getElementById('result').textContent=JSON.stringify(res,null,2);};
document.getElementById('deobfForm').onsubmit=async(e)=>{
e.preventDefault();
const code=document.getElementById('codeInput').value;
const res=await apiCall('/api/l',{code});
document.getElementById('result').textContent=res.deobfuscated||res.error||'No result';};
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "Missing url"}), 400
    return jsonify(extract_from_url(url))

@app.route('/api/l', methods=['POST'])
def api_l():
    data = request.get_json()
    code = data.get('code', '')
    if code.startswith(('http://', 'https://', 'www.')):
        if not code.startswith('http'):
            code = 'https://' + code
        content = fetch_text_sync(normalize_url(code))
        if not content:
            content = fetch_text_sync(code)
        if content:
            code = content
    return jsonify({"deobfuscated": static_deobfuscate(code)[:MAX_CHUNK_SIZE]})

# ============================================================
# STEP 12: RUN BOTH
# ============================================================
def run_bot():
    try:
        print("🚀 Starting bot with token:", BOT_TOKEN[:10] + "...")
        bot.run(BOT_TOKEN)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        import threading
        
        print("=" * 60)
        print("🐟 CAT BOT v4.1 - Starting...")
        print("=" * 60)
        
        # Start bot in background thread
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("✅ Bot thread started")
        
        # Start Flask web server
        print(f"🌐 Starting web server on {WEB_HOST}:{WEB_PORT}")
        app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
        
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
