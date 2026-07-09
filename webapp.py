"""Telegram Web App backend for the prompt form.

This app serves a single-page form that can be opened from a Telegram Web App
button. On submit it renders a Markdown preview and, when running inside Telegram,
sends the raw payload back to the bot via `Telegram.WebApp.sendData(...)`.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bot import FIELDS, discover_usable_models, render_prompt

load_dotenv(Path(__file__).resolve().parent / ".env")

APP_TITLE = "Telegram Prompt Form"
DEFAULT_PORT = int(os.getenv("WEBAPP_PORT", "8000"))
WEB_APP_NAME = os.getenv("TELEGRAM_WEB_APP_NAME", "Prompt Form")

app = FastAPI(title=APP_TITLE)


FIELD_ORDER = [key for key, _, _ in FIELDS]
FIELD_META = {key: {"label": label, "helper": helper} for key, label, helper in FIELDS}


def _escape(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _models_options() -> str:
    models = discover_usable_models()
    if not models:
        models = ["GPT-4.1", "Claude Sonnet 4", "Gemini 2.5 Pro"]
    return "\n".join(f'<option value="{_escape(model)}">{_escape(model)}</option>' for model in models)


def _render_html() -> str:
    inputs = []
    for key in FIELD_ORDER:
        meta = FIELD_META[key]
        if key == "model":
            control = f"""
            <select id="{_escape(key)}" name="{_escape(key)}" required>
              <option value="">Select a model</option>
              {_models_options()}
            </select>
            """
        else:
            control = f'<textarea id="{_escape(key)}" name="{_escape(key)}" rows="3" placeholder="{_escape(meta["helper"])}"></textarea>'
        inputs.append(
            f"""
            <label for="{_escape(key)}">{_escape(meta['label'])}</label>
            <div class="help">{_escape(meta['helper'])}</div>
            {control}
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(APP_TITLE)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #0b1020; color: #e8ecff; }}
    .wrap {{ max-width: 920px; margin: 0 auto; padding: 20px; }}
    .card {{ background: #121a33; border: 1px solid #26345f; border-radius: 16px; padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.25); }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    .sub {{ color: #b4bfdc; margin-bottom: 16px; }}
    form {{ display: grid; gap: 14px; }}
    label {{ font-weight: 700; display: block; margin-bottom: 4px; }}
    .help {{ color: #93a2cc; font-size: 13px; margin-bottom: 6px; }}
    textarea, select {{ width: 100%; box-sizing: border-box; border-radius: 12px; border: 1px solid #31406f; background: #0d1430; color: #e8ecff; padding: 12px; font-size: 15px; }}
    textarea {{ resize: vertical; min-height: 88px; }}
    .grid {{ display: grid; gap: 14px; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }}
    button {{ border: 0; border-radius: 12px; padding: 12px 16px; font-weight: 700; cursor: pointer; }}
    .primary {{ background: #7c5cff; color: white; }}
    .ghost {{ background: #21305a; color: #e8ecff; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #0a1024; border: 1px solid #27345d; border-radius: 12px; padding: 14px; }}
    .preview {{ margin-top: 18px; }}
    .badge {{ display: inline-block; margin-bottom: 12px; padding: 4px 10px; border-radius: 999px; background: #21305a; color: #d8e0ff; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="badge">{_escape(WEB_APP_NAME)}</div>
      <h1>{_escape(APP_TITLE)}</h1>
      <div class="sub">Fill the fields, preview the final prompt, and submit back to Telegram.</div>

      <form id="form">
        {''.join(inputs)}
        <div class="actions">
          <button class="primary" type="submit">Build prompt</button>
          <button class="ghost" type="button" id="fillDemo">Fill demo</button>
          <button class="ghost" type="button" id="clearBtn">Clear</button>
        </div>
      </form>

      <div class="preview" id="previewWrap" hidden>
        <h2>Preview</h2>
        <pre id="preview"></pre>
      </div>
    </div>
  </div>

  <script>
    const TELEGRAM = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (TELEGRAM) {{
      TELEGRAM.ready();
      TELEGRAM.expand();
    }}

    const fieldOrder = {json.dumps(FIELD_ORDER)};

    function payloadFromForm() {{
      const data = {{}};
      for (const key of fieldOrder) {{
        const el = document.getElementById(key);
        data[key] = el ? el.value.trim() : "";
      }}
      return data;
    }}

    function setForm(data) {{
      for (const key of fieldOrder) {{
        const el = document.getElementById(key);
        if (!el) continue;
        el.value = data[key] || "";
      }}
    }}

    async function buildPrompt(data) {{
      const res = await fetch('/api/submit', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data),
      }});
      if (!res.ok) throw new Error('submit failed');
      return await res.json();
    }}

    document.getElementById('form').addEventListener('submit', async (ev) => {{
      ev.preventDefault();
      const data = payloadFromForm();
      const out = await buildPrompt(data);
      document.getElementById('preview').textContent = out.prompt;
      document.getElementById('previewWrap').hidden = false;
      if (TELEGRAM) {{
        TELEGRAM.sendData(JSON.stringify(data));
      }}
    }});

    document.getElementById('fillDemo').addEventListener('click', () => {{
      setForm({{
        goal: 'Improve a prompt for clarity and reliability',
        model: 'GPT-4.1',
        task_type: 'analysis',
        input_prompt: 'Draft a better prompt from this rough idea',
        context: 'Private-chat bot, concise output, privacy-safe wording',
        constraints: 'No group features, keep it Telegram-friendly',
        audience: 'Busy operator',
        desired_output_style: 'concise and structured',
        must_include: 'copy-friendly final prompt',
        must_avoid: 'fluff, speculation',
        quality_bar: 'clear, actionable, ready to use',
        optional: 'Mention the exact model names only',
      }});
    }});

    document.getElementById('clearBtn').addEventListener('click', () => {{
      setForm({{}});
      document.getElementById('previewWrap').hidden = true;
      document.getElementById('preview').textContent = '';
    }});
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _render_html()


@app.get("/api/bootstrap")
async def bootstrap() -> JSONResponse:
    return JSONResponse(
        {
            "title": APP_TITLE,
            "name": WEB_APP_NAME,
            "fields": FIELDS,
            "models": discover_usable_models(),
        }
    )


@app.post("/api/submit")
async def submit(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Expected a JSON object"}, status_code=400)

    answers: Dict[str, str] = {k: str(v).strip() for k, v in payload.items() if v is not None}
    prompt = render_prompt(answers)
    return JSONResponse({"prompt": prompt, "answers": answers})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webapp:app", host="0.0.0.0", port=DEFAULT_PORT, reload=False)
