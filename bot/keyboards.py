"""Inline keyboard builders and callback data handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class CallbackAction(str, Enum):
    """Supported callback actions."""

    # Main menu
    MAIN_MENU = "main_menu"
    HELP = "help"
    SETTINGS = "settings"

    # Example features
    EXAMPLE_API_CALL = "example_api_call"
    EXAMPLE_DB_QUERY = "example_db_query"
    TOGGLE_NOTIFICATIONS = "toggle_notifications"

    # Pagination
    PREV_PAGE = "prev_page"
    NEXT_PAGE = "next_page"

    # Confirmation
    CONFIRM_YES = "confirm_yes"
    CONFIRM_NO = "confirm_no"

    # Admin
    ADMIN_STATS = "admin_stats"
    ADMIN_BROADCAST = "admin_broadcast"


@dataclass
class CallbackData:
    """Structured callback data."""

    action: CallbackAction
    payload: str = ""

    def pack(self) -> str:
        """Serialize to string for callback_data."""
        if self.payload:
            return f"{self.action.value}:{self.payload}"
        return self.action.value

    @classmethod
    def unpack(cls, data: str) -> CallbackData:
        """Deserialize from callback_data string."""
        parts = data.split(":", 1)
        action = CallbackAction(parts[0])
        payload = parts[1] if len(parts) > 1 else ""
        return cls(action=action, payload=payload)


def build_main_keyboard() -> InlineKeyboardMarkup:
    """Build main menu keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔧 Example API Call", callback_data=CallbackData(CallbackAction.EXAMPLE_API_CALL).pack()),
            InlineKeyboardButton("💾 Example DB Query", callback_data=CallbackData(CallbackAction.EXAMPLE_DB_QUERY).pack()),
        ],
        [
            InlineKeyboardButton("🔔 Toggle Notifications", callback_data=CallbackData(CallbackAction.TOGGLE_NOTIFICATIONS).pack()),
            InlineKeyboardButton("❓ Help", callback_data=CallbackData(CallbackAction.HELP).pack()),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data=CallbackData(CallbackAction.SETTINGS).pack()),
        ],
    ])


def build_help_keyboard() -> InlineKeyboardMarkup:
    """Build help keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("« Back to Menu", callback_data=CallbackData(CallbackAction.MAIN_MENU).pack()),
        ],
    ])


def build_settings_keyboard(notifications_enabled: bool = True) -> InlineKeyboardMarkup:
    """Build settings keyboard."""
    notif_text = "🔔 Notifications: ON" if notifications_enabled else "🔕 Notifications: OFF"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(notif_text, callback_data=CallbackData(CallbackAction.TOGGLE_NOTIFICATIONS).pack()),
        ],
        [
            InlineKeyboardButton("« Back to Menu", callback_data=CallbackData(CallbackAction.MAIN_MENU).pack()),
        ],
    ])


def build_confirmation_keyboard(
    confirm_action: CallbackAction,
    cancel_action: CallbackAction = CallbackAction.MAIN_MENU,
    payload: str = "",
) -> InlineKeyboardMarkup:
    """Build confirmation dialog keyboard."""
    confirm_data = CallbackData(confirm_action, payload).pack()
    cancel_data = CallbackData(cancel_action).pack()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=confirm_data),
            InlineKeyboardButton("❌ No", callback_data=cancel_data),
        ],
    ])


def build_pagination_keyboard(
    current_page: int,
    total_pages: int,
    base_action: CallbackAction,
    payload: str = "",
) -> InlineKeyboardMarkup:
    """Build pagination keyboard."""
    buttons = []

    if current_page > 1:
        prev_payload = f"{payload}:page={current_page - 1}" if payload else f"page={current_page - 1}"
        buttons.append(
            InlineKeyboardButton("« Prev", callback_data=CallbackData(base_action, prev_payload).pack())
        )

    buttons.append(
        InlineKeyboardButton(f"Page {current_page}/{total_pages}", callback_data="noop")
    )

    if current_page < total_pages:
        next_payload = f"{payload}:page={current_page + 1}" if payload else f"page={current_page + 1}"
        buttons.append(
            InlineKeyboardButton("Next »", callback_data=CallbackData(base_action, next_payload).pack())
        )

    return InlineKeyboardMarkup([buttons])


def build_admin_keyboard() -> InlineKeyboardMarkup:
    """Build admin panel keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data=CallbackData(CallbackAction.ADMIN_STATS).pack()),
            InlineKeyboardButton("📢 Broadcast", callback_data=CallbackData(CallbackAction.ADMIN_BROADCAST).pack()),
        ],
        [
            InlineKeyboardButton("« Back to Menu", callback_data=CallbackData(CallbackAction.MAIN_MENU).pack()),
        ],
    ])