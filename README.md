# Telegram Prompt Form Bot

A small **aiogram** bot that turns Telegram into a privacy-safe prompt intake form.

## What it does
- Multi-step prompt collection
- Exact model picker from a curated allow-list
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
- Live URL: https://loney01843.github.io/telegram-prompt-form/
- This is the richer Telegram Web App UI.
- The page sends structured form data back to the bot via Telegram `web_app_data`.
- If Telegram refuses to open it, set the bot domain in BotFather to `loney01843.github.io`.

