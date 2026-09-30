"""Playwright 컨텍스트 팩토리: 기기 프로필, 요청 차단, 팝업·다이얼로그·다운로드 처리."""
from __future__ import annotations

import asyncio

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route

from .config import Settings

BLOCKED_RESOURCE_TYPES = frozenset({"media", "font"})
USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Mobile Safari/537.36"


async def open_browser(pw: Playwright) -> Browser:
    return await pw.chromium.launch(headless=True)


async def _block_resources(route: Route) -> None:
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


async def _close_popup(page: Page) -> None:
    try:
        if await page.opener() is not None:
            await page.close()
    except Exception:
        pass


def _dismiss_dialog(dialog) -> None:
    asyncio.ensure_future(dialog.dismiss())


async def new_context(pw: Playwright, browser: Browser, settings: Settings) -> BrowserContext:
    device = dict(pw.devices[settings.device])
    context = await browser.new_context(
        **device, locale="ko-KR", timezone_id="Asia/Seoul",
        accept_downloads=False, ignore_https_errors=True,
    )
    context.set_default_timeout(settings.page_timeout_ms)
    await context.route("**/*", _block_resources)
    context.on("page", lambda p: asyncio.ensure_future(_close_popup(p)))
    return context


def attach_page_guards(page: Page) -> None:
    page.on("dialog", _dismiss_dialog)
