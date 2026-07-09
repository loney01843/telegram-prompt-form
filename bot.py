"""Telegram prompt-form bot.

Features
- Multi-step prompt intake in private chats and groups.
- Group safety: requires @mention in group chats before starting.
- Profile-aware hints loaded from config.yaml.
- Privacy-safe examples only: no raw history, no private cross-profile leakage.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)
HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"
WEB_APP_URL = os.getenv("TELEGRAM_WEB_APP_URL", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("promptform")


class PromptForm(StatesGroup):
    waiting_for_field = State()
    review = State()


FIELDS = [
    ("goal", "Goal", "What are you trying to achieve?"),
    ("model", "Model", "Which model will receive this prompt?"),
    ("task_type", "Task Type", "What kind of task is this?"),
    ("input_prompt", "Input Prompt", "Paste the raw prompt or source material here."),
    ("context", "Context", "Any background information the model needs to know."),
    ("constraints", "Constraints", "List any length, tone, privacy, safety, budget, or latency limits."),
    ("audience", "Audience", "Who is the output for?"),
    ("desired_output_style", "Desired Output Style", "What should the response feel like?"),
    ("must_include", "Must Include", "Anything that must stay in the final prompt/output."),
    ("must_avoid", "Must Avoid", "Anything that must not appear."),
    ("quality_bar", "Quality Bar", "What does a good result look like?"),
    ("optional", "Optional", "Examples, fallback behavior, keywords to preserve, or notes."),
]


@dataclass
class BotConfig:
    command_name: str
    review_required: bool
    default_models: List[str]
    profiles: Dict[str, Dict[str, Any]]
    chat_profile_map: Dict[str, str]


class ConfigError(RuntimeError):
    pass


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError("config.yaml must contain a mapping at top level")
    return data


def _save_yaml(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def load_config() -> BotConfig:
    data = _load_yaml(CONFIG_PATH)
    bot = data.get("bot", {}) or {}
    models = data.get("models", {}) or {}
    profiles = data.get("profiles", {}) or {}
    chat_profile_map = data.get("chat_profile_map", {}) or {}

    default_models = models.get("default_list")
    if not isinstance(default_models, list) or not default_models:
        raise ConfigError("models.default_list must be a non-empty list")

    # Normalize profile model lists. If omitted, inherit the global default list.
    normalized_profiles: Dict[str, Dict[str, Any]] = {}
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        profile = dict(profile)
        if not profile.get("available_models"):
            profile["available_models"] = list(default_models)
        normalized_profiles[name] = profile

    if "default" not in normalized_profiles:
        normalized_profiles["default"] = {
            "label": "Default",
            "available_models": list(default_models),
            "tone_hint": "concise, neutral, privacy-safe",
            "example_style": "general",
            "defaults": {"task_type": "analysis", "desired_output_style": "concise, technical"},
            "example_hints": {},
        }

    return BotConfig(
        command_name=str(bot.get("command_name", "promptform")).strip(),
        review_required=bool(bot.get("review_required", True)),
        default_models=list(default_models),
        profiles=normalized_profiles,
        chat_profile_map={str(k): str(v) for k, v in chat_profile_map.items()},
    )


CONFIG = load_config()
BOT_USERNAME = ""
BOT_ID = 0


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        raise ConfigError("Set TELEGRAM_BOT_TOKEN in the environment before starting the bot")
    return token.strip()


async def get_bot_username(bot: Bot) -> str:
    me = await bot.get_me()
    return me.username or ""


def active_profile_for_chat(chat_id: int) -> str:
    return CONFIG.chat_profile_map.get(str(chat_id), "default")


def profile_for_chat(chat_id: int) -> Dict[str, Any]:
    name = active_profile_for_chat(chat_id)
    return CONFIG.profiles.get(name) or CONFIG.profiles["default"]


def profile_examples(profile: Dict[str, Any]) -> Dict[str, str]:
    return dict(profile.get("example_hints") or {})


def discover_usable_models() -> List[str]:
    """Return the currently usable model list.

    Priority:
    1) Hermes's configured + live-usable provider catalogs
    2) Config fallback list from config.yaml

    This refreshes on each call so the picker stays aligned with the current
    authenticated providers and their live catalogs.
    """
    if HERMES_AGENT_ROOT.exists():
        agent_root = str(HERMES_AGENT_ROOT)
        if agent_root not in sys.path:
            sys.path.insert(0, agent_root)
    try:
        from hermes_cli.inventory import build_models_payload, load_picker_context

        ctx = load_picker_context()
        payload = build_models_payload(
            ctx,
            explicit_only=True,
            refresh=True,
            probe_custom_providers=False,
            probe_current_custom_provider=True,
        )
        models: List[str] = []
        seen = set()
        for provider in payload.get("providers", []):
            for model in provider.get("models", []) or []:
                if model in seen:
                    continue
                seen.add(model)
                models.append(model)
        if models:
            logger.info("Discovered %d currently usable models", len(models))
            return models
    except Exception:
        logger.exception("Live model discovery failed; using fallback model list")
    return list(CONFIG.default_models)



def build_model_keyboard(models: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for model in models:
        row.append(InlineKeyboardButton(text=model, callback_data=f"pick:model:{model}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Other", callback_data="pick:model:Other")])
    rows.append([
        InlineKeyboardButton(text="Back", callback_data="nav:back"),
        InlineKeyboardButton(text="Skip", callback_data="nav:skip"),
        InlineKeyboardButton(text="Cancel", callback_data="nav:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_nav_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Back", callback_data="nav:back"),
                InlineKeyboardButton(text="Skip", callback_data="nav:skip"),
                InlineKeyboardButton(text="Cancel", callback_data="nav:cancel"),
            ]
        ]
    )


def build_force_reply() -> ForceReply:
    # ForceReply nudges Telegram to open the reply box anchored to the bot's message.
    return ForceReply(selective=True)


def build_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Generate Prompt", callback_data="review:generate")],
            [InlineKeyboardButton(text="Edit Goal", callback_data="review:edit:goal")],
            [InlineKeyboardButton(text="Edit Input Prompt", callback_data="review:edit:input_prompt")],
            [InlineKeyboardButton(text="Edit Constraints", callback_data="review:edit:constraints")],
            [InlineKeyboardButton(text="Cancel", callback_data="nav:cancel")],
        ]
    )


def build_webapp_keyboard() -> ReplyKeyboardMarkup | None:
    if not WEB_APP_URL:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Open Web App", web_app=WebAppInfo(url=WEB_APP_URL))]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def format_models_text(models: List[str]) -> str:
    """Render the currently usable model catalog as readable Markdown."""
    lines = [f"- `{m}`" for m in models]
    if not lines:
        return "No usable models were discovered."
    return "\n".join(lines)


def field_prompt(profile: Dict[str, Any], index: int) -> str:
    key, label, helper = FIELDS[index]
    examples = profile_examples(profile)
    hint = examples.get(key)
    message = [f"**{label}**", helper]
    if hint:
        message.append(f"_Example:_ {hint}")
    if key == "model":
        message.append("Choose from the exact model buttons below.")
    return "\n".join(message)


def render_prompt(data: Dict[str, str]) -> str:
    # Build a clean Markdown prompt that can be copy/pasted directly.
    sections = []
    for key, label, _ in FIELDS:
        value = data.get(key, "").strip()
        if not value:
            continue
        sections.append(f"## {label}\n{value}")
    sections.append("## Final Instruction\nRewrite / improve / answer the prompt above according to the requirements.")
    return "\n\n".join(sections)


async def start_form(message: Message, state: FSMContext, bot: Bot, preset: Optional[str] = None) -> None:
    chat = message.chat
    profile = profile_for_chat(chat.id)
    data = {
        "chat_id": chat.id,
        "chat_type": chat.type,
        "profile_name": active_profile_for_chat(chat.id),
        "profile_label": profile.get("label", "Default"),
        "field_index": 0,
        "answers": {},
    }
    if preset:
        data["preset"] = preset
    await state.set_state(PromptForm.waiting_for_field)
    await state.set_data(data)

    text = (
        f"**Prompt Form — {profile.get('label', 'Default')}**\n\n"
        f"Send each field one at a time. Reply directly to this chat; this bot is now private-chat only.\n"
        f"I refresh the model list at run time, so the **Model** step reflects what is currently usable.\n\n"
        f"{field_prompt(profile, 0)}"
    )
    reply_markup = build_force_reply()
    await message.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def ask_next_field(message_or_query: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile = profile_for_chat(int(data["chat_id"]))
    index = int(data.get("field_index", 0))
    if index >= len(FIELDS):
        await show_review(message_or_query, state)
        return

    key, label, helper = FIELDS[index]
    if key == "model":
        await message_or_query.answer(
            field_prompt(profile, index),
            reply_markup=build_model_keyboard(discover_usable_models()),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await message_or_query.answer(
            field_prompt(profile, index),
            reply_markup=build_force_reply(),
            parse_mode=ParseMode.MARKDOWN,
        )


async def show_review(message_or_query: Message, state: FSMContext) -> None:
    data = await state.get_data()
    answers = data.get("answers", {})
    text = render_prompt(answers)
    await state.set_state(PromptForm.review)
    await message_or_query.answer(
        f"**Review**\n\nHere is the filled template. If it looks good, generate the final prompt.\n\n```markdown\n{text}\n```",
        reply_markup=build_review_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def advance(state: FSMContext, message: Message) -> None:
    data = await state.get_data()
    index = int(data.get("field_index", 0)) + 1
    data["field_index"] = index
    await state.set_data(data)
    if index >= len(FIELDS):
        await show_review(message, state)
    else:
        await ask_next_field(message, state, message.bot)


async def store_answer(state: FSMContext, value: str) -> None:
    data = await state.get_data()
    index = int(data.get("field_index", 0))
    key, _, _ = FIELDS[index]
    answers = dict(data.get("answers", {}))
    answers[key] = value.strip()
    data["answers"] = answers
    data["field_index"] = index + 1
    await state.set_data(data)


async def cancel_form(state: FSMContext, message: Message) -> None:
    await state.clear()
    await message.answer("Cancelled. Send /new to start again.")


async def back_form(state: FSMContext, message: Message) -> None:
    data = await state.get_data()
    index = max(0, int(data.get("field_index", 0)) - 1)
    answers = dict(data.get("answers", {}))
    if index < len(FIELDS):
        answers.pop(FIELDS[index][0], None)
    data["field_index"] = index
    data["answers"] = answers
    await state.set_data(data)
    await ask_next_field(message, state, message.bot)


async def skip_form(state: FSMContext, message: Message) -> None:
    await advance(state, message)


async def on_start(message: Message, state: FSMContext, command: CommandObject, bot: Bot) -> None:
    if WEB_APP_URL:
        await message.answer(
            "Open the Web App to fill the form in a richer UI, or use /new for the chat wizard.",
            reply_markup=build_webapp_keyboard(),
        )
        return
    await message.answer("I’m ready to fill the prompt form. Use /new to start.")


async def on_new(message: Message, state: FSMContext, bot: Bot) -> None:
    await start_form(message, state, bot)


async def on_text(message: Message, state: FSMContext, bot: Bot) -> None:
    logger.info(
        "Incoming text chat_id=%s type=%s text=%r",
        message.chat.id,
        message.chat.type,
        (message.text or message.caption or "")[:200],
    )
    if not message.text:
        return
    current = await state.get_state()
    if current != PromptForm.waiting_for_field.state:
        return

    data = await state.get_data()
    index = int(data.get("field_index", 0))
    if index >= len(FIELDS):
        return

    key, _, _ = FIELDS[index]
    text = message.text.strip()
    if key == "model" and text not in profile_for_chat(message.chat.id).get("available_models", CONFIG.default_models):
        # Accept free text, but in practice the keyboard should guide the choice.
        await message.answer("Tip: the model field is best picked from the exact buttons, but I’ll accept your text.")
    await store_answer(state, text)
    await advance(state, message)


async def on_web_app_data(message: Message) -> None:
    raw = (message.web_app_data.data if message.web_app_data else "").strip()
    if not raw:
        await message.answer("I received an empty Web App payload.")
        return
    try:
        payload = yaml.safe_load(raw)
    except Exception:
        payload = raw

    if isinstance(payload, dict):
        prompt = render_prompt({k: str(v) for k, v in payload.items() if v is not None})
    else:
        prompt = str(payload)
    await message.answer(f"**Web App Submission**\n\n```markdown\n{prompt}\n```")


async def on_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = callback.data or ""
    message = callback.message
    if not message:
        await callback.answer()
        return

    if data == "nav:cancel":
        await callback.answer("Cancelled")
        await cancel_form(state, message)
        return
    if data == "nav:back":
        await callback.answer()
        await back_form(state, message)
        return
    if data == "nav:skip":
        await callback.answer()
        await skip_form(state, message)
        return

    if data.startswith("pick:model:"):
        await callback.answer()
        choice = data.split(":", 2)[2]
        if choice == "Other":
            await message.answer("Type the exact model name you want to use, or pick one from the list.")
            return
        await store_answer(state, choice)
        await advance(state, message)
        return

    if data == "review:generate":
        await callback.answer("Generated")
        form_data = (await state.get_data()).get("answers", {})
        prompt = render_prompt(form_data)
        await state.clear()
        await message.answer(f"**Final Prompt**\n\n```markdown\n{prompt}\n```", parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("review:edit:"):
        await callback.answer()
        field = data.split(":", 2)[2]
        data_state = await state.get_data()
        answers = dict(data_state.get("answers", {}))
        target_index = next((i for i, item in enumerate(FIELDS) if item[0] == field), 0)
        answers.pop(field, None)
        data_state["answers"] = answers
        data_state["field_index"] = target_index
        await state.set_data(data_state)
        await state.set_state(PromptForm.waiting_for_field)
        await ask_next_field(message, state, bot)
        return

    await callback.answer()


async def on_profile(message: Message, state: FSMContext, command: CommandObject) -> None:
    arg = (command.args or "").strip().lower()
    if not arg:
        current = active_profile_for_chat(message.chat.id)
        await message.answer(f"Current profile for this chat: `{current}`")
        return
    if arg not in CONFIG.profiles:
        available = ", ".join(sorted(CONFIG.profiles))
        await message.answer(f"Unknown profile `{arg}`. Available: {available}")
        return
    # Persist the chat->profile binding to config so shared groups keep their profile.
    CONFIG.chat_profile_map[str(message.chat.id)] = arg
    data = _load_yaml(CONFIG_PATH)
    data["chat_profile_map"] = CONFIG.chat_profile_map
    _save_yaml(CONFIG_PATH, data)
    await message.answer(f"Bound this chat to profile `{arg}`.")


async def on_models(message: Message) -> None:
    models = discover_usable_models()
    await message.answer(
        f"**Usable models right now ({len(models)})**\n\n```text\n{format_models_text(models)}\n```",
        parse_mode=ParseMode.MARKDOWN,
    )


async def main() -> None:
    token = get_bot_token()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    global BOT_USERNAME, BOT_ID
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    BOT_ID = me.id
    logger.info("Bot started as @%s", BOT_USERNAME)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.register(on_start, Command("start"))
    dp.message.register(on_new, Command("new"))
    dp.message.register(on_profile, Command("profile"))
    dp.message.register(on_models, Command("models"))
    dp.message.register(on_web_app_data, F.web_app_data)
    dp.message.register(on_text, F.text)
    dp.callback_query.register(on_callback)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
