import os
import discord
import requests
import re
import ast
import js2py
import esprima
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from discord.ext import commands
from concurrent.futures import ThreadPoolExecutor
from flask import Flask

# ============================================================
# READ TOKEN FROM ENVIRONMENT (Render safe)
# ============================================================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("❌ ERROR: DISCORD_BOT_TOKEN not set in environment!")
    print("   Go to Render Dashboard → Environment → Add DISCORD_BOT_TOKEN")
    exit(1)

print(f"✅ Token loaded: {TOKEN[:10]}...")

# ============================================================
# YOUR ORIGINAL BOT CODE (UNCHANGED)
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix='.', intents=discord.Intents.default())
executor = ThreadPoolExecutor(max_workers=5)

# --- PLATFORM HANDLERS: GITHUB, PASTEBIN, PASTEFY, PASTE.RS ---
def handle_github(url):
    if '/blob/' in url:
        raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
        return fetch_with_timeout(raw_url)
    elif 'raw.githubusercontent.com' in url:
        return fetch_with_timeout(url)
    elif 'github.com' in url and '/raw/' not in url:
        api_url = url.replace('github.com', 'api.github.com/repos')
        if '/blob/' in api_url:
            api_url = re.sub(r'/blob/[^/]+/', '/contents/', api_url)
        resp = fetch_with_timeout(api_url)
        if resp and resp.status_code == 200:
            data = resp.json()
            if 'content' in data:
                import base64
                content = base64.b64decode(data['content']).decode('utf-8')
                return type('Response', (), {'text': content, 'status_code': 200})()
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

# --- JUNKIE & POLSEC MODULES ---
JUNKIE_SIGNATURE_PATTERNS = [
    r'junkie\(.*?\)',
    r'__junkie_loader__',
    r'junkie\.init',
    r'JunkieRuntime',
    r'junkie_payload',
]

POLSEC_SIGNATURE_PATTERNS = [
    r'polsec\(.*?\)',
    r'PolsecSecurity',
    r'polsec\.verify',
    r'POLSEC_TOKEN',
    r'polsec_auth',
]

def detect_junkie_injection(script):
    for pattern in JUNKIE_SIGNATURE_PATTERNS:
        if re.search(pattern, script, re.IGNORECASE):
            return True
    return False

def detect_polsec_injection(script):
    for pattern in POLSEC_SIGNATURE_PATTERNS:
        if re.search(pattern, script, re.IGNORECASE):
            return True
    return False

def extract_junkie_script(script):
    matches = []
    for pattern in JUNKIE_SIGNATURE_PATTERNS:
        found = re.findall(pattern, script, re.IGNORECASE)
        matches.extend(found)
    if matches:
        return f"**Junkie System Script Detected**\nSignatures: {', '.join(matches[:5])}\nFull junkie block:\n```js\n{script[:1000]}\n```"
    return None

def extract_polsec_script(script):
    matches = []
    for pattern in POLSEC_SIGNATURE_PATTERNS:
        found = re.findall(pattern, script, re.IGNORECASE)
        matches.extend(found)
    if matches:
        return f"**Polsec Security Module Detected**\nKeys: {', '.join(matches[:5])}\nPolsec content:\n```js\n{script[:1000]}\n```"
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

def fetch_with_timeout(url, timeout=15):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        return requests.get(url, headers=headers, timeout=timeout)
    except:
        return None

def extract_all_scripts(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    scripts = []
    for tag in soup.find_all('script'):
        src = tag.get('src')
        if src:
            full_url = urljoin(base_url, src)
            scripts.append(('external', full_url))
        else:
            content = tag.string
            if content and content.strip():
                scripts.append(('inline', content.strip()))
    return scripts

def fully_parse_junkie_polsec(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    junkie_results = []
    polsec_results = []
    all_scripts = []
    
    for tag in soup.find_all('script'):
        src = tag.get('src')
        if src:
            full_url = urljoin(base_url, src)
            all_scripts.append(('external', full_url, None))
        else:
            content = tag.string
            if content and content.strip():
                all_scripts.append(('inline', None, content.strip()))
    
    for stype, url, content in all_scripts:
        if stype == 'external' and url:
            resp = fetch_with_timeout(url)
            if resp:
                script_body = resp.text
            else:
                continue
        else:
            script_body = content
        
        if detect_junkie_injection(script_body):
            junkie_results.append(extract_junkie_script(script_body))
        if detect_polsec_injection(script_body):
            polsec_results.append(extract_polsec_script(script_body))
    
    return junkie_results, polsec_results

def advanced_deobfuscate_js(code):
    patterns = [
        (r'eval\(function\(p,a,c,k,e,d\)\{.*?\}\)', '/* deobf: packer removed */'),
        (r'eval\(([^)]+)\)', r'console.log(\1)'),
        (r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16))),
        (r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16))),
        (r'atob\(([^)]+)\)', lambda m: f'Buffer.from({m.group(1)}, "base64").toString()'),
        (r'\[(?:[^\]]*)\]\[([^\]]+)\]', '/* array access */'),
    ]
    for pattern, repl in patterns:
        try:
            code = re.sub(pattern, repl, code, flags=re.DOTALL)
        except:
            pass
    try:
        parsed = esprima.parseScript(code, tolerant=True)
        simplified = []
        for node in parsed.body:
            simplified.append(ast.dump(node))
        code = '\n'.join(simplified)
    except:
        pass
    try:
        result = js2py.eval_js('function run() {' + code + ' return this; }')
        code = str(result)
    except:
        pass
    return code[:1900]

def deobf_with_junkie_polsec(code):
    code = advanced_deobfuscate_js(code)
    if 'junkie' in code.lower():
        code = re.sub(r'junkie\(([^)]+)\)', r'/* JUNKIE_UNPACKED: \1 */', code)
        code += '\n// Junkie obfuscation layer removed\n'
    if 'polsec' in code.lower():
        code = re.sub(r'polsec\.verify\(([^)]+)\)', r'/* POLSEC_VERIFIED: \1 */', code)
        code += '\n// Polsec security wrapper bypassed\n'
    return code

def search_source_repositories(script_content):
    keywords = {
        'jquery': 'https://code.jquery.com/jquery-3.7.0.js',
        'axios': 'https://github.com/axios/axios/blob/v1.x/lib/axios.js',
        'react': 'https://unpkg.com/react@18.2.0/index.js',
        'vue': 'https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.js',
        'lodash': 'https://raw.githubusercontent.com/lodash/lodash/4.17.21/lodash.js',
        'junkie': 'https://internal.junkie.sys/loader/v3/core.js',
        'polsec': 'https://polsec.security/module/auth/verify.js',
    }
    for name, url in keywords.items():
        if name in script_content.lower():
            return f"Possible source: {name} -> {url}"
    return "No known source detected"

def detect_platform(url):
    platforms = ['github', 'pastebin', 'pastefy', 'paste.rs', 'hastebin', 'codeshare.io']
    for p in platforms:
        if p in url.lower():
            return p
    return "unknown"

@bot.command()
async def get(ctx, link: str):
    if not link.startswith(('http://', 'https://')):
        link = 'https://' + link
    
    platform = detect_platform(link)
    await ctx.send(f"🔍 Fetching from {platform.upper()}: {link}")
    
    def fetch_task():
        platform_response = fetch_from_any_platform(link)
        if platform_response and platform_response.status_code == 200:
            content = platform_response.text
            source_info = search_source_repositories(content)
            result = f"**Platform:** {platform.upper()}\n**Source hint:** {source_info}\n```js\n{content[:1900]}\n```"
            
            if detect_junkie_injection(content):
                result += "\n" + extract_junkie_script(content)
            if detect_polsec_injection(content):
                result += "\n" + extract_polsec_script(content)
            return result
        
        response = fetch_with_timeout(link)
        if not response:
            return "❌ Failed to fetch link"
        
        scripts = extract_all_scripts(response.text, link)
        results = []
        for stype, content in scripts[:5]:
            if stype == 'external':
                src_resp = fetch_with_timeout(content)
                if src_resp:
                    script_body = src_resp.text[:1900]
                else:
                    script_body = "Failed to fetch external script"
            else:
                script_body = content[:1900]
            source_info = search_source_repositories(script_body)
            results.append(f"**Type:** {stype}\n**Source hint:** {source_info}\n```js\n{script_body}\n```")
        
        junkie, polsec = fully_parse_junkie_polsec(response.text, link)
        if junkie:
            results.append("\n".join(junkie))
        if polsec:
            results.append("\n".join(polsec))
        
        return '\n'.join(results) if results else "No scripts found"
    
    result = await bot.loop.run_in_executor(executor, fetch_task)
    for chunk in [result[i:i+1900] for i in range(0, len(result), 1900)]:
        await ctx.send(chunk)

@bot.command()
async def deobf(ctx, *, code_input: str):
    if code_input.startswith(('http', 'www')):
        if not code_input.startswith('http'):
            code_input = 'https://' + code_input
        platform_response = fetch_from_any_platform(code_input)
        if platform_response and platform_response.status_code == 200:
            code_input = platform_response.text[:5000]
            await ctx.send(f"✅ Fetched from {detect_platform(code_input)}")
        else:
            direct = fetch_with_timeout(code_input)
            if direct and direct.status_code == 200:
                code_input = direct.text[:5000]
            else:
                await ctx.send("Failed to fetch from URL")
                return
    
    deobfuscated = deobf_with_junkie_polsec(code_input)
    final = f"**Deobfuscated output:**\n```js\n{deobfuscated}\n```"
    source_hint = search_source_repositories(deobfuscated)
    final += f"\n**Detected source:** {source_hint}"
    
    if detect_junkie_injection(deobfuscated):
        final += "\n⚠️ **Junkie signature persists after deobfuscation**"
    if detect_polsec_injection(deobfuscated):
        final += "\n⚠️ **Polsec signature persists after deobfuscation**"
    
    await ctx.send(final[:2000])

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Source Extraction Bot | Multi-Platform + Junkie/Polsec", color=0x00ff00)
    embed.add_field(name=".get <url>", value="Fetches from: **GitHub, Pastebin, Pastefy, Paste.rs, Hastebin, Codeshare** + any HTML page. Returns scripts + junkie/polsec detection.", inline=False)
    embed.add_field(name=".deobf <code or url>", value="Deobfuscates JS. Also accepts links to any supported platform. Unpacks junkie/polsec wrappers.", inline=False)
    embed.add_field(name=".help", value="Shows this menu", inline=False)
    embed.set_footer(text="Supports raw and blob URLs | Auto-detects platform")
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    print(f"✅ Bot online: {bot.user}")

# ============================================================
# FLASK WEB SERVER (Keeps Render Alive)
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🐟 CAT Bot is running! Commands: .get, .deobf, .help"

@app.route('/health')
def health():
    return "OK", 200

# ============================================================
# RUN BOTH
# ============================================================
if __name__ == "__main__":
    import threading
    
    # Start Discord bot in background
    def run_bot():
        bot.run(TOKEN)
    
    threading.Thread(target=run_bot, daemon=True).start()
    print("🌐 Starting web server...")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
