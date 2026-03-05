from __future__ import annotations

import base64
import json
import os
import time
from urllib.parse import urlparse

import aiohttp

from .runtime import AppRuntime


def _load_cookie_header(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as file:
            auth = json.load(file)
        cookies = auth.get("cookies") or []
        parts = []
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        return "; ".join(parts)
    except Exception:
        return ""


async def download_and_attach(runtime: AppRuntime, session: aiohttp.ClientSession, attach_obj) -> str | None:
    os.makedirs(runtime.settings.attachments_dir, exist_ok=True)

    if isinstance(attach_obj, str):
        attach = {"baseUrl": attach_obj}
    elif isinstance(attach_obj, dict):
        attach = attach_obj
    else:
        return None

    preview = attach.get("previewData")
    preview_path = None
    if isinstance(preview, str) and preview.startswith("data:"):
        try:
            header, b64 = preview.split(",", 1)
            mime = header.split(";")[0].split(":")[1] if ":" in header else "application/octet-stream"
            ext = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/webp": ".webp",
                "image/gif": ".gif",
            }.get(mime, ".bin")
            filename = f"preview_{int(time.time() * 1000)}{ext}"
            preview_path = os.path.join(runtime.settings.attachments_dir, filename)
            with open(preview_path, "wb") as file:
                file.write(base64.b64decode(b64))
            print("[вложение] сохранён previewData ->", preview_path, flush=True)
        except Exception as exc:
            print("[вложение] ошибка сохранения previewData:", exc, flush=True)
            preview_path = None

    base_url = attach.get("baseUrl") or attach.get("url") or attach.get("file_url")
    if base_url:
        try:
            headers = {
                "User-Agent": runtime.settings.ws_user_agent,
                "Referer": runtime.settings.ws_referer,
            }
            cookie_header = _load_cookie_header(runtime.settings.ws_auth_file)
            if cookie_header:
                headers["Cookie"] = cookie_header

            async with session.get(base_url, headers=headers, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status == 200 and content_type.startswith("image"):
                    if "webp" in content_type:
                        ext = ".webp"
                    elif "png" in content_type:
                        ext = ".png"
                    elif "jpeg" in content_type or "jpg" in content_type:
                        ext = ".jpg"
                    else:
                        parsed_url = urlparse(base_url).path
                        ext = os.path.splitext(parsed_url)[1] or ".bin"

                    filename = f"attach_{int(time.time() * 1000)}{ext}"
                    out_path = os.path.join(runtime.settings.attachments_dir, filename)
                    with open(out_path, "wb") as out_file:
                        out_file.write(await response.read())
                    print("[вложение] скачано baseUrl ->", out_path, flush=True)
                    return out_path

                print(
                    f"[вложение] baseUrl вернул status={response.status}, content-type={content_type}",
                    flush=True,
                )
        except Exception as exc:
            print("[вложение] ошибка скачивания baseUrl:", exc, flush=True)

    if preview_path:
        return preview_path

    photo_token = attach.get("photoToken") or attach.get("token")
    if photo_token:
        print("[вложение] найден photoToken, но загрузка через Playwright не подключена", flush=True)

    return None
