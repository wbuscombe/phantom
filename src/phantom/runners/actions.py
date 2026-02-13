"""Action executor for Playwright-based runners.

Translates manifest action definitions into Playwright page operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from phantom.models import (
    ClickAction,
    ConditionalAction,
    EvaluateAction,
    HoverAction,
    KeyboardShortcutAction,
    NavigateAction,
    PressAction,
    RouteAction,
    ScrollAction,
    ScrollToAction,
    SetCookieAction,
    SetThemeAction,
    SetViewportAction,
    TypeAction,
    WaitAction,
    WaitForAction,
    WaitForNetworkAction,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

    from phantom.models import Action

logger = structlog.get_logger()


async def execute_action(page: Page, action: Action, context: BrowserContext) -> None:
    """Execute a single action against a Playwright page.

    Args:
        page: The Playwright page to act on.
        action: The action definition from the manifest.
        context: The browser context (for cookie operations).
    """
    action_type = action.type
    logger.debug("action_execute", type=action_type)

    match action:
        case NavigateAction():
            await page.goto(action.url, wait_until="domcontentloaded")

        case RouteAction():
            base_url = page.url.split("/")[0:3]
            url = "/".join(base_url) + action.path
            await page.goto(url, wait_until="domcontentloaded")

        case ClickAction():
            if action.selector:
                locator = page.locator(action.selector)
                await locator.click(
                    button=action.button,
                    click_count=action.count,
                )
            else:
                assert action.x is not None and action.y is not None
                await page.mouse.click(
                    action.x,
                    action.y,
                    button=action.button,
                    click_count=action.count,
                )

        case HoverAction():
            await page.locator(action.selector).hover()

        case ScrollToAction():
            await page.locator(action.selector).scroll_into_view_if_needed()

        case ScrollAction():
            await page.mouse.wheel(action.x, action.y)

        case TypeAction():
            if action.selector:
                await page.locator(action.selector).click()
            await page.keyboard.type(action.text, delay=action.delay)

        case PressAction():
            await page.keyboard.press(action.key)

        case KeyboardShortcutAction():
            await page.keyboard.press(action.keys)

        case WaitAction():
            await page.wait_for_timeout(action.ms)

        case WaitForAction():
            await page.locator(action.selector).first.wait_for(
                state=action.state,
                timeout=action.timeout * 1000,
            )

        case WaitForNetworkAction():
            timeout_ms = action.timeout * 1000
            if action.state == "idle":
                await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            else:
                await page.wait_for_load_state("load", timeout=timeout_ms)

        case SetThemeAction():
            await page.emulate_media(color_scheme=action.theme)

        case SetViewportAction():
            await page.set_viewport_size({"width": action.width, "height": action.height})

        case EvaluateAction():
            await page.evaluate(action.js)

        case SetCookieAction():
            await context.add_cookies(
                [
                    {
                        "name": action.name,
                        "value": action.value,
                        "domain": action.domain,
                        "path": "/",
                    }
                ]
            )

        case ConditionalAction():
            condition_met = await _evaluate_condition(page, action)
            actions_to_run = action.then if condition_met else (action.else_ or [])
            for sub_action in actions_to_run:
                await execute_action(page, sub_action, context)

        case _:
            logger.warning("action_unsupported", type=action_type)


async def execute_actions(
    page: Page,
    actions: list[Action],
    context: BrowserContext,
) -> None:
    """Execute a sequence of actions."""
    for i, action in enumerate(actions):
        logger.debug("action_step", index=i, type=action.type)
        await execute_action(page, action, context)


async def _evaluate_condition(page: Page, action: ConditionalAction) -> bool:
    """Evaluate a conditional action's condition."""
    conditions = action.if_
    if "selector_exists" in conditions:
        selector = conditions["selector_exists"]
        count = await page.locator(selector).count()
        return count > 0
    logger.warning("condition_unknown", conditions=conditions)
    return False


# JavaScript injected before every capture for deterministic rendering.
DETERMINISM_SCRIPT = """
() => {
    // Freeze CSS animations and transitions
    document.querySelectorAll('*').forEach(el => {
        el.style.animationPlayState = 'paused';
        el.style.transitionDuration = '0s';
    });

    // Deterministic time
    const PHANTOM_NOW = new Date('2026-01-15T10:30:00Z');
    const OriginalDate = Date;
    window.Date = class extends OriginalDate {
        constructor(...args) {
            super(...(args.length ? args : [PHANTOM_NOW]));
        }
        static now() { return PHANTOM_NOW.getTime(); }
    };

    // Deterministic random (seedable PRNG)
    let _seed = 42;
    Math.random = () => {
        _seed = (_seed * 16807) % 2147483647;
        return (_seed - 1) / 2147483646;
    };

    // Disable cursor blink
    document.querySelectorAll('input, textarea').forEach(el => {
        el.style.caretColor = 'transparent';
    });

    // Disable scrollbars for clean captures
    const style = document.createElement('style');
    style.textContent = '::-webkit-scrollbar { display: none !important; } * { scrollbar-width: none !important; }';
    document.head.appendChild(style);
}
"""
