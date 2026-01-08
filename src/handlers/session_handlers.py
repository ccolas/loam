"""
Handlers for session management commands: /session, /new, /switch, /rename, /star, /unstar
"""
from aiogram import types
from aiogram.types import CallbackQuery

from src.core.scope_manager import ScopeManager


# Callback data prefixes
SESSION_NAV = "snav:"          # Navigate to folder during /new or /switch
SESSION_SELECT_NEW = "snew:"   # Select scope for new session
SESSION_SELECT_RESUME = "sres:" # Select scope to show sessions
SESSION_PICK = "spick:"        # Pick a specific session to resume
SESSION_PICK_CROSS = "sxpick:" # Pick session from cross-scope list (format: scope|session_id)
SESSION_SAVE = "ssave"         # Save current session before switching
SESSION_DISCARD = "sdiscard"   # Discard current session before switching
SESSION_BACK = "sback"         # Go back in navigation
SESSION_RECENT = "srecent"     # Show recent sessions across all scopes
SESSION_STARRED = "sstarred"   # Show starred sessions across all scopes
SESSION_CANCEL = "scancel"     # Cancel the /new or /switch flow


class SessionHandlers:
    """Handles session management commands."""

    def __init__(self, scope_manager: ScopeManager):
        self.scope_manager = scope_manager

        # Track pending actions after save/discard decision
        # user_id -> {"action": "new"|"resume"|"route", "target_scope": str, ...}
        self.pending_actions: dict[int, dict] = {}

        # Track users awaiting text input for /rename
        self.awaiting_rename: dict[int, str] = {}  # user_id -> scope

        # Track users awaiting session name for save
        self.awaiting_session_name: dict[int, str] = {}  # user_id -> scope

        # Track navigation mode: user_id -> "new" | "resume"
        self.nav_mode: dict[int, str] = {}

        # Callback for when a route action is ready to execute
        # Set by the bot: async def(user_id, target_scope, original_message)
        self.on_route_ready = None

    # ─────────────────────────────────────────────────────────────────────────
    # /session command - show current scope + session
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_session_command(self, message: types.Message):
        """Handle /session - show current scope and session info."""
        user_id = message.chat.id
        scope = self.scope_manager.get_active_scope(user_id)
        scope_display = scope if scope else "root"

        session = self.scope_manager.get_current_session(user_id, scope)

        if session:
            name = session.get('description') or "(unnamed)"
            starred = " ⭐" if session.get('starred') else ""
            text = f"📂 `{scope_display}`\n"
            text += f"💬 _{name}{starred}_"
        else:
            text = f"📂 `{scope_display}`\n"
            text += f"💬 _no active session_"

        await message.answer(text, parse_mode='Markdown')

    # ─────────────────────────────────────────────────────────────────────────
    # /new command - navigate to scope, then create new session
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_new_command(self, message: types.Message):
        """Handle /new - show folder tree to pick scope for new session."""
        user_id = message.chat.id

        # Reset nav position to root and set mode
        self.scope_manager.set_nav_position(user_id, '')
        self.nav_mode[user_id] = "new"

        text = "📍 _Select folder for new session_"

        from src.ui.keyboards import build_session_nav_keyboard
        keyboard = build_session_nav_keyboard(self.scope_manager, user_id, '', mode="new")

        await message.answer(text, reply_markup=keyboard, parse_mode='Markdown')

    # ─────────────────────────────────────────────────────────────────────────
    # /switch command - navigate to scope, pick session
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_switch_command(self, message: types.Message):
        """Handle /switch - show current scope + folder tree to pick scope."""
        user_id = message.chat.id

        # Reset nav position to root and set mode
        self.scope_manager.set_nav_position(user_id, '')
        self.nav_mode[user_id] = "resume"

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_history = self.scope_manager.get_session_history(user_id, current_scope)

        text = "🔀 _Switch session_"

        from src.ui.keyboards import build_session_nav_keyboard
        keyboard = build_session_nav_keyboard(
            self.scope_manager, user_id, '',
            mode="resume",
            current_scope=current_scope,
            has_current_sessions=bool(current_history)
        )

        await message.answer(text, reply_markup=keyboard, parse_mode='Markdown')

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation callbacks
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_nav_callback(self, callback: CallbackQuery):
        """Handle folder navigation during /new or /resume."""
        user_id = callback.from_user.id
        data = callback.data

        if data.startswith(SESSION_NAV):
            # Navigate into folder
            folder_path = data[len(SESSION_NAV):]
            self.scope_manager.set_nav_position(user_id, folder_path)

            mode = self.nav_mode.get(user_id, "new")
            current_scope = self.scope_manager.get_active_scope(user_id)
            current_history = self.scope_manager.get_session_history(user_id, current_scope)

            folder_display = folder_path or "root"
            text = f"📂 `{folder_display}`"

            from src.ui.keyboards import build_session_nav_keyboard
            keyboard = build_session_nav_keyboard(
                self.scope_manager, user_id, folder_path,
                mode=mode,
                current_scope=current_scope,
                has_current_sessions=bool(current_history)
            )

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif data == SESSION_BACK:
            # Go back to parent folder (or to root if coming from recent/starred view)
            current = self.scope_manager.get_nav_position(user_id)
            parent = self.scope_manager.get_parent_path(current)
            self.scope_manager.set_nav_position(user_id, parent)

            mode = self.nav_mode.get(user_id, "new")
            # If mode is "recent" or "starred", reset to resume mode at root
            if mode in ("recent", "starred"):
                mode = "resume"
                self.nav_mode[user_id] = mode
                parent = ''

            current_scope = self.scope_manager.get_active_scope(user_id)
            current_history = self.scope_manager.get_session_history(user_id, current_scope)

            folder_display = parent or "root"
            text = f"📂 `{folder_display}`"

            from src.ui.keyboards import build_session_nav_keyboard
            keyboard = build_session_nav_keyboard(
                self.scope_manager, user_id, parent,
                mode=mode,
                current_scope=current_scope,
                has_current_sessions=bool(current_history)
            )

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')

        await callback.answer()

    async def handle_recent_callback(self, callback: CallbackQuery):
        """Handle showing recent sessions across all scopes."""
        user_id = callback.from_user.id

        self.nav_mode[user_id] = "recent"

        recent_sessions = self.scope_manager.get_recent_sessions_all_scopes(user_id, limit=5)

        if not recent_sessions:
            await callback.message.edit_text(
                "_No recent sessions_",
                parse_mode='Markdown'
            )
            await callback.answer()
            return

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_session_id = self.scope_manager.get_session_id(user_id, current_scope)

        text = "⏱ _Recent_"

        from src.ui.keyboards import build_cross_scope_session_list_keyboard
        keyboard = build_cross_scope_session_list_keyboard(
            recent_sessions,
            current_session_id=current_session_id
        )

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
        await callback.answer()

    async def handle_starred_callback(self, callback: CallbackQuery):
        """Handle showing starred sessions across all scopes."""
        user_id = callback.from_user.id

        self.nav_mode[user_id] = "starred"

        starred_sessions = self.scope_manager.get_starred_sessions_all_scopes(user_id)

        if not starred_sessions:
            await callback.message.edit_text(
                "_No starred sessions_",
                parse_mode='Markdown'
            )
            await callback.answer()
            return

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_session_id = self.scope_manager.get_session_id(user_id, current_scope)

        text = "★ _Starred_"

        from src.ui.keyboards import build_cross_scope_session_list_keyboard
        keyboard = build_cross_scope_session_list_keyboard(
            starred_sessions,
            current_session_id=current_session_id
        )

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
        await callback.answer()

    async def handle_cancel_callback(self, callback: CallbackQuery):
        """Handle cancelling the /new or /resume flow."""
        user_id = callback.from_user.id

        # Clear any pending state
        self.nav_mode.pop(user_id, None)
        self.pending_actions.pop(user_id, None)

        await callback.message.edit_text("_Cancelled_", parse_mode='Markdown')
        await callback.answer()

    async def handle_pick_cross_callback(self, callback: CallbackQuery):
        """Handle picking a session from cross-scope list (recent/starred)."""
        user_id = callback.from_user.id
        data = callback.data[len(SESSION_PICK_CROSS):]

        # Parse scope|session_id
        if '|' not in data:
            await callback.message.edit_text("Invalid session selection.")
            await callback.answer()
            return

        target_scope, target_session_id = data.split('|', 1)

        # Store for session picking flow
        self.nav_mode[user_id] = f"resume:{target_scope}"

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_session = self.scope_manager.get_current_session(user_id, current_scope)

        # Check if current session is unnamed - need to ask save/discard
        if current_session and not current_session.get('description'):
            self.pending_actions[user_id] = {
                "action": "resume",
                "target_scope": target_scope,
                "target_session": target_session_id
            }
            await self._ask_save_discard(callback, current_scope)
        else:
            # Current session is named (or none) - proceed directly
            await self._execute_resume_session(callback, user_id, target_scope, target_session_id)

        await callback.answer()

    async def handle_select_new_callback(self, callback: CallbackQuery):
        """Handle scope selection for new session."""
        user_id = callback.from_user.id
        target_scope = callback.data[len(SESSION_SELECT_NEW):]

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_session = self.scope_manager.get_current_session(user_id, current_scope)

        # Check if current session is unnamed - need to ask save/discard
        if current_session and not current_session.get('description'):
            self.pending_actions[user_id] = {
                "action": "new",
                "target_scope": target_scope,
                "target_session": None
            }
            await self._ask_save_discard(callback, current_scope)
        else:
            # Current session is named (or none) - proceed directly
            await self._execute_new_session(callback, user_id, target_scope)

        await callback.answer()

    async def handle_select_resume_callback(self, callback: CallbackQuery):
        """Handle scope selection for resume - show sessions in that scope."""
        user_id = callback.from_user.id
        target_scope = callback.data[len(SESSION_SELECT_RESUME):]

        history = self.scope_manager.get_session_history(user_id, target_scope)
        scope_display = target_scope or "root"

        if not history:
            await callback.message.edit_text(
                f"_No sessions in_ `{scope_display}`",
                parse_mode='Markdown'
            )
            await callback.answer()
            return

        # Store target scope for when user picks a session
        self.nav_mode[user_id] = f"resume:{target_scope}"

        text = f"📂 `{scope_display}`"

        current_session_id = self.scope_manager.get_session_id(user_id, target_scope)

        from src.ui.keyboards import build_session_list_keyboard
        keyboard = build_session_list_keyboard(history, current_session_id)

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
        await callback.answer()

    async def handle_pick_session_callback(self, callback: CallbackQuery):
        """Handle picking a specific session to resume."""
        user_id = callback.from_user.id
        target_session_id = callback.data[len(SESSION_PICK):]

        # Get target scope from nav_mode
        mode = self.nav_mode.get(user_id, "")
        if not mode.startswith("resume:"):
            await callback.message.edit_text("Session expired. Please try /switch again.")
            await callback.answer()
            return

        target_scope = mode[len("resume:"):]

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_session = self.scope_manager.get_current_session(user_id, current_scope)

        # Check if current session is unnamed - need to ask save/discard
        if current_session and not current_session.get('description'):
            self.pending_actions[user_id] = {
                "action": "resume",
                "target_scope": target_scope,
                "target_session": target_session_id
            }
            await self._ask_save_discard(callback, current_scope)
        else:
            # Current session is named (or none) - proceed directly
            await self._execute_resume_session(callback, user_id, target_scope, target_session_id)

        await callback.answer()

    # ─────────────────────────────────────────────────────────────────────────
    # Save/Discard flow
    # ─────────────────────────────────────────────────────────────────────────

    async def _ask_save_discard(self, callback: CallbackQuery, current_scope: str):
        """Ask user whether to save or discard current unnamed session."""
        scope_display = current_scope or "root"

        text = f"💬 _Unnamed session in_ `{scope_display}`\n\nSave before switching?"

        from src.ui.keyboards import build_save_discard_keyboard
        keyboard = build_save_discard_keyboard()

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')

    async def handle_save_discard_callback(self, callback: CallbackQuery):
        """Handle save/discard decision."""
        user_id = callback.from_user.id
        data = callback.data

        pending = self.pending_actions.get(user_id)
        if not pending:
            await callback.message.edit_text("Session expired. Please try again.")
            await callback.answer()
            return

        current_scope = self.scope_manager.get_active_scope(user_id)

        if data == SESSION_SAVE:
            # User wants to name/save the session
            self.awaiting_session_name[user_id] = current_scope

            await callback.message.edit_text(
                "What would you like to call this session?\n\n"
                "_Reply with a short description:_",
                parse_mode='Markdown'
            )

        elif data == SESSION_DISCARD:
            # Discard the session
            self.scope_manager.discard_current_session(user_id, current_scope)

            # Execute pending action
            await self._execute_pending_action(callback, user_id)

        await callback.answer()

    async def handle_session_name_input(self, message: types.Message) -> bool:
        """Handle session name input. Returns True if handled."""
        user_id = message.chat.id

        if user_id not in self.awaiting_session_name:
            return False

        scope = self.awaiting_session_name.pop(user_id)
        name = message.text.strip()

        if not name:
            await message.reply("_Name required_", parse_mode='Markdown')
            self.awaiting_session_name[user_id] = scope
            return True

        # Truncate if too long
        if len(name) > 100:
            name = name[:97] + "…"

        # Save the session with this name
        session_id = self.scope_manager.get_session_id(user_id, scope)
        if session_id:
            self.scope_manager.rename_session(user_id, scope, session_id, name)

        await message.reply(f"✓ _{name}_", parse_mode='Markdown')

        # Execute pending action if any
        pending = self.pending_actions.get(user_id)
        if pending:
            action = pending.get("action")
            target_scope = pending.get("target_scope")
            target_session = pending.get("target_session")
            self.pending_actions.pop(user_id, None)

            if action == "new":
                self.scope_manager.create_new_session(user_id, target_scope)
                scope_display = target_scope or "root"
                await message.reply(
                    f"📂 `{scope_display}` › _new session_",
                    parse_mode='Markdown'
                )
            elif action == "resume" and target_session:
                success = self.scope_manager.resume_session(user_id, target_scope, target_session)
                if success:
                    history = self.scope_manager.get_session_history(user_id, target_scope)
                    desc = next((s.get('description') for s in history if s['id'] == target_session), None)
                    scope_display = target_scope or "root"
                    await message.reply(
                        f"📂 `{scope_display}` › _{desc or '(unnamed)'}_",
                        parse_mode='Markdown'
                    )
                else:
                    await message.reply("_Session no longer exists_", parse_mode='Markdown')
            elif action == "route":
                original_msg = pending.get("original_message", "")
                if self.on_route_ready:
                    await self.on_route_ready(user_id, target_scope, original_msg, message)

        return True

    async def _execute_pending_action(self, callback: CallbackQuery, user_id: int):
        """Execute the pending action after save/discard."""
        pending = self.pending_actions.pop(user_id, None)
        if not pending:
            return

        action = pending.get("action")
        target_scope = pending.get("target_scope")
        target_session = pending.get("target_session")

        if action == "new":
            await self._execute_new_session(callback, user_id, target_scope)
        elif action == "resume" and target_session:
            await self._execute_resume_session(callback, user_id, target_scope, target_session)
        elif action == "route":
            original_msg = pending.get("original_message", "")
            if self.on_route_ready:
                await self.on_route_ready(user_id, target_scope, original_msg, callback)

    async def _execute_new_session(self, callback: CallbackQuery, user_id: int, target_scope: str):
        """Create new session in target scope."""
        self.scope_manager.create_new_session(user_id, target_scope)
        scope_display = target_scope or "root"

        await callback.message.edit_text(
            f"✓ 📂 `{scope_display}` › _new session_",
            parse_mode='Markdown'
        )

    async def _execute_resume_session(self, callback: CallbackQuery, user_id: int,
                                       target_scope: str, target_session_id: str):
        """Resume a specific session."""
        success = self.scope_manager.resume_session(user_id, target_scope, target_session_id)

        if success:
            history = self.scope_manager.get_session_history(user_id, target_scope)
            desc = next((s.get('description') for s in history if s['id'] == target_session_id), None)
            scope_display = target_scope or "root"

            await callback.message.edit_text(
                f"✓ 📂 `{scope_display}` › _{desc or '(unnamed)'}_",
                parse_mode='Markdown'
            )
        else:
            await callback.message.edit_text(
                "_Session no longer exists_",
                parse_mode='Markdown'
            )

    # ─────────────────────────────────────────────────────────────────────────
    # /rename command
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_rename_command(self, message: types.Message):
        """Handle /rename - rename current session."""
        user_id = message.chat.id
        scope = self.scope_manager.get_active_scope(user_id)
        session = self.scope_manager.get_current_session(user_id, scope)

        if not session:
            await message.reply("_No active session_", parse_mode='Markdown')
            return

        current_name = session.get('description')
        if current_name:
            text = f"Current: _{current_name}_\n\nNew name?"
        else:
            text = "Name this session:"

        self.awaiting_rename[user_id] = scope
        await message.reply(text, parse_mode='Markdown')

    async def handle_rename_input(self, message: types.Message) -> bool:
        """Handle rename input. Returns True if handled."""
        user_id = message.chat.id

        if user_id not in self.awaiting_rename:
            return False

        scope = self.awaiting_rename.pop(user_id)
        name = message.text.strip()

        if not name:
            await message.reply("_Name required_", parse_mode='Markdown')
            self.awaiting_rename[user_id] = scope
            return True

        if len(name) > 100:
            name = name[:97] + "…"

        session_id = self.scope_manager.get_session_id(user_id, scope)
        if session_id:
            self.scope_manager.rename_session(user_id, scope, session_id, name)
            await message.reply(f"✓ _{name}_", parse_mode='Markdown')
        else:
            await message.reply("_No active session_", parse_mode='Markdown')

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # /star and /unstar commands
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_star_command(self, message: types.Message):
        """Handle /star - star current session."""
        user_id = message.chat.id
        scope = self.scope_manager.get_active_scope(user_id)
        session = self.scope_manager.get_current_session(user_id, scope)

        if not session:
            await message.reply("_No active session_", parse_mode='Markdown')
            return

        if session.get('starred'):
            await message.reply("_Already starred_", parse_mode='Markdown')
            return

        session_id = self.scope_manager.get_session_id(user_id, scope)
        self.scope_manager.star_session(user_id, scope, session_id)

        name = session.get('description') or "(unnamed)"
        await message.reply(f"★ _{name}_", parse_mode='Markdown')

    async def handle_unstar_command(self, message: types.Message):
        """Handle /unstar - unstar current session."""
        user_id = message.chat.id
        scope = self.scope_manager.get_active_scope(user_id)
        session = self.scope_manager.get_current_session(user_id, scope)

        if not session:
            await message.reply("_No active session_", parse_mode='Markdown')
            return

        if not session.get('starred'):
            await message.reply("_Not starred_", parse_mode='Markdown')
            return

        session_id = self.scope_manager.get_session_id(user_id, scope)
        self.scope_manager.unstar_session(user_id, scope, session_id)

        name = session.get('description') or "(unnamed)"
        await message.reply(f"☆ _{name}_", parse_mode='Markdown')

    # ─────────────────────────────────────────────────────────────────────────
    # Check if awaiting input
    # ─────────────────────────────────────────────────────────────────────────

    def is_awaiting_input(self, user_id: int) -> bool:
        """Check if user is awaiting text input."""
        return user_id in self.awaiting_rename or user_id in self.awaiting_session_name