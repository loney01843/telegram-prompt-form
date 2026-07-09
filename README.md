# Telegram Prompt Form Bot

A small **aiogram** bot that turns Telegram into a privacy-safe prompt intake form.

## What it does
- Multi-step prompt collection
- Exact model picker from the currently credential-backed models
- Auto mode that picks the best ChatGPT-subscription model for the job
- Profile-aware examples without exposing raw history
- Works in private chats only

## Commands
- `/start` — intro/help
- `/new` — start a new prompt form
- `/profile` — show the current profile for this chat
- `/profile technical` — bind the current chat to the `technical` profile
- `/profile creative` — bind the current chat to the `creative` profile
- `/models` — show the currently usable model list discovered at runtime

## Group behavior
- Disabled. This bot is now private-chat only.
- Use `/new` in a DM with the bot.

## Setup
1. Create a virtual environment
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Export the token:
   ```bash
   export TELEGRAM_BOT_TOKEN='...'
   ```
4. Run:
   ```bash
   python bot.py
   ```

## Web App
- Private tailnet URL: `https://brsvr.tail5967a1.ts.net`
- The page is only reachable from devices on your Tailscale network.
- The bot sends structured form data back via Telegram `web_app_data`.
- `/start` shows the Web App button in private chat.

