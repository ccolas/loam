from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional

from src.core.scope_manager import ScopeManager


# Callback data prefixes for scope navigation (legacy, kept for /create)
SCOPE_NAV = "scope_nav:"      # Navigate to folder in tree
SCOPE_SELECT = "scope_sel:"   # Select folder as active scope
SCOPE_BACK = "scope_back"     # Go to parent folder
SCOPE_CREATE = "scope_create" # Create new folder at current position
CREATE_CONFIRM = "create_ok:" # Confirm folder creation


# Callback data prefixes for note proposals
NOTE_APPROVE = "note_approve"
NOTE_EDIT = "note_edit"
NOTE_CANCEL = "note_cancel"


# Callback data for session management
SESSION_NAV = "snav:"           # Navigate to folder during /new or /switch
SESSION_SELECT_NEW = "snew:"    # Select scope for new session
SESSION_SELECT_RESUME = "sres:" # Select scope to show sessions
SESSION_PICK = "spick:"         # Pick a specific session to resume
SESSION_PICK_CROSS = "sxpick:"  # Pick session from cross-scope list (format: scope|session_id)
SESSION_SAVE = "ssave"          # Save current session before switching
SESSION_DISCARD = "sdiscard"    # Discard current session before switching
SESSION_BACK = "sback"          # Go back in navigation
SESSION_RECENT = "srecent"      # Show recent sessions across all scopes
SESSION_STARRED = "sstarred"    # Show starred sessions across all scopes
SESSION_CANCEL = "scancel"      # Cancel the /new or /switch flow


def build_folder_tree_keyboard(
    scope_manager: ScopeManager,
    user_id: int,
    current_path: str = '',
    active_scope: Optional[str] = None
) -> InlineKeyboardMarkup:
    """
    Build inline keyboard showing folder tree at current_path.
    (Legacy - used by /create flow)
    """
    buttons = []

    # Get subfolders at current path
    subfolders = scope_manager.list_folders(current_path)

    # Add folder buttons (2 per row for readability)
    row = []
    for folder in subfolders:
        full_path = f"{current_path}/{folder}" if current_path else folder

        # Mark folders with existing sessions
        has_session = scope_manager.has_session(user_id, full_path)
        is_active = (full_path == active_scope)

        if is_active:
            label = f"📂 {folder} ✓"
        elif has_session:
            label = f"📁 {folder} •"
        else:
            label = f"📁 {folder}"

        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"{SCOPE_NAV}{full_path}"
        ))

        if len(row) == 2:
            buttons.append(row)
            row = []

    # Add remaining buttons
    if row:
        buttons.append(row)

    # Navigation row
    nav_row = []

    # Back button (if not at root)
    if current_path:
        nav_row.append(InlineKeyboardButton(
            text="← Back",
            callback_data=SCOPE_BACK
        ))

    # Select this folder button
    select_label = "✓ Select here" if current_path != active_scope else "✓ Current"
    nav_row.append(InlineKeyboardButton(
        text=select_label,
        callback_data=f"{SCOPE_SELECT}{current_path}"
    ))

    if nav_row:
        buttons.append(nav_row)

    # Create folder button
    buttons.append([InlineKeyboardButton(
        text="+ Create new folder",
        callback_data=SCOPE_CREATE
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_create_position_keyboard(
    scope_manager: ScopeManager,
    current_path: str = ''
) -> InlineKeyboardMarkup:
    """
    Build keyboard for selecting where to create a new folder.
    Similar to tree navigation but with 'Create here' instead of 'Select'.
    """
    buttons = []

    # Get subfolders at current path
    subfolders = scope_manager.list_folders(current_path)

    # Add folder buttons
    row = []
    for folder in subfolders:
        full_path = f"{current_path}/{folder}" if current_path else folder
        label = f"📁 {folder}"

        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"create_nav:{full_path}"
        ))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Navigation row
    nav_row = []

    if current_path:
        nav_row.append(InlineKeyboardButton(
            text="← Back",
            callback_data="create_back"
        ))

    nav_row.append(InlineKeyboardButton(
        text="+ Create here",
        callback_data=f"create_here:{current_path}"
    ))

    if nav_row:
        buttons.append(nav_row)

    # Cancel button
    buttons.append([InlineKeyboardButton(
        text="✗ Cancel",
        callback_data="create_cancel"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_confirm_keyboard(action: str, data: str = '') -> InlineKeyboardMarkup:
    """Build simple confirm/cancel keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Yes", callback_data=f"{action}_confirm:{data}"),
            InlineKeyboardButton(text="× No", callback_data=f"{action}_cancel")
        ]
    ])


def build_note_proposal_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for note proposal confirmation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Save", callback_data=NOTE_APPROVE),
            InlineKeyboardButton(text="✎ Edit", callback_data=NOTE_EDIT),
            InlineKeyboardButton(text="× Cancel", callback_data=NOTE_CANCEL),
        ]
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Session management keyboards
# ─────────────────────────────────────────────────────────────────────────────

def build_session_nav_keyboard(
    scope_manager: ScopeManager,
    user_id: int,
    current_path: str = '',
    mode: str = "new",
    current_scope: Optional[str] = None,
    has_current_sessions: bool = False
) -> InlineKeyboardMarkup:
    """
    Build keyboard for navigating folders during /new or /switch.

    mode="new": Shows [Select] to create new session in folder
    mode="resume": Shows [Select] to see sessions in folder, plus Recent/Starred buttons
    """
    buttons = []

    # For /switch at root, show quick-access buttons first
    if mode == "resume" and current_path == '':
        # Row 1: Recent and Starred buttons
        quick_row = [
            InlineKeyboardButton(text="⏱ Recent", callback_data=SESSION_RECENT),
            InlineKeyboardButton(text="★ Starred", callback_data=SESSION_STARRED),
        ]
        buttons.append(quick_row)

        # Row 2: Current scope if it has sessions
        if has_current_sessions:
            scope_display = current_scope or "root"
            buttons.append([InlineKeyboardButton(
                text=f"● {scope_display}",
                callback_data=f"{SESSION_SELECT_RESUME}{current_scope}"
            )])

    # Get subfolders at current path
    subfolders = scope_manager.list_folders(current_path)

    # Add folder buttons (2 per row)
    row = []
    for folder in subfolders:
        full_path = f"{current_path}/{folder}" if current_path else folder

        # Check if folder has sessions
        history = scope_manager.get_session_history(user_id, full_path)
        has_sessions = bool(history)

        if has_sessions:
            label = f"{folder} ({len(history)})"
        else:
            label = folder

        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"{SESSION_NAV}{full_path}"
        ))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Navigation row
    nav_row = []

    # Back button (if not at root)
    if current_path:
        nav_row.append(InlineKeyboardButton(
            text="‹ Back",
            callback_data=SESSION_BACK
        ))

    # Select button - different behavior based on mode
    if mode == "new":
        nav_row.append(InlineKeyboardButton(
            text="+ New session here",
            callback_data=f"{SESSION_SELECT_NEW}{current_path}"
        ))
    else:  # resume
        # Show sessions in this folder
        history = scope_manager.get_session_history(user_id, current_path)
        if history:
            nav_row.append(InlineKeyboardButton(
                text=f"+ Sessions here ({len(history)})",
                callback_data=f"{SESSION_SELECT_RESUME}{current_path}"
            ))
        else:
            nav_row.append(InlineKeyboardButton(
                text="(no sessions)",
                callback_data="noop"
            ))

    if nav_row:
        buttons.append(nav_row)

    # Cancel button at the bottom
    buttons.append([InlineKeyboardButton(
        text="× Cancel",
        callback_data=SESSION_CANCEL
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_session_list_keyboard(
    history: list[dict],
    current_session_id: Optional[str] = None
) -> InlineKeyboardMarkup:
    """
    Build keyboard showing session history for resumption.
    """
    buttons = []

    for session in history:
        session_id = session['id']
        description = session.get('description') or "(unnamed)"
        starred = session.get('starred', False)

        # Truncate long descriptions
        if len(description) > 32:
            description = description[:30] + "…"

        # Build label with minimal prefix
        prefix = ""
        if session_id == current_session_id:
            prefix = "● "
        elif starred:
            prefix = "★ "

        label = f"{prefix}{description}"

        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"{SESSION_PICK}{session_id}"
        )])

    # Back button
    buttons.append([InlineKeyboardButton(
        text="‹ Back",
        callback_data=SESSION_BACK
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_save_discard_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for save/discard decision."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Save", callback_data=SESSION_SAVE),
            InlineKeyboardButton(text="❌ Discard", callback_data=SESSION_DISCARD),
        ]
    ])


def build_cross_scope_session_list_keyboard(
    sessions: list[dict],
    current_session_id: Optional[str] = None,
    title: str = "Sessions"
) -> InlineKeyboardMarkup:
    """
    Build keyboard showing sessions from multiple scopes.
    """
    buttons = []

    for session in sessions:
        session_id = session['id']
        description = session.get('description') or "(unnamed)"
        scope = session.get('scope', '')
        starred = session.get('starred', False)

        # Truncate
        scope_display = scope if scope else "root"
        if len(scope_display) > 10:
            scope_display = scope_display[:8] + "…"
        if len(description) > 18:
            description = description[:16] + "…"

        # Build label with minimal prefix
        prefix = ""
        if session_id == current_session_id:
            prefix = "● "
        elif starred:
            prefix = "★ "

        label = f"{prefix}{scope_display} › {description}"

        # Encode scope and session_id together
        callback_data = f"{SESSION_PICK_CROSS}{scope}|{session_id}"

        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=callback_data
        )])

    # Back button
    buttons.append([InlineKeyboardButton(
        text="‹ Back",
        callback_data=SESSION_BACK
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Callback data for route proposals
ROUTE_CONFIRM = "route_confirm:"  # Confirm routing to suggested scope
ROUTE_KEEP = "route_keep"         # Keep content in current scope


def build_route_proposal_keyboard(target_scope: str) -> InlineKeyboardMarkup:
    """Build keyboard for route proposal confirmation."""
    scope_display = target_scope if target_scope else "root"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"→ {scope_display}",
                callback_data=f"{ROUTE_CONFIRM}{target_scope}"
            ),
            InlineKeyboardButton(text="● Keep here", callback_data=ROUTE_KEEP),
        ]
    ])