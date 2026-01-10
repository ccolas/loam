"""
Loam

Loam is a cultivated space where links, notes, and thoughts grow over time.
It interfaces a Telegram bot with Claude Code sessions managing an Obsidian vault.
Each folder scope gets its own persistent Claude Code sessions.
"""
import asyncio
import logging
import os
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand

from src.utils import load_api_keys, get_repo_path
from src.core.scope_manager import ScopeManager
from src.core.claude_session import ClaudeSessionPool, NoteProposal, RouteProposal
from src.handlers.session_handlers import SessionHandlers
from src.ui.keyboards import (
    NOTE_APPROVE, NOTE_EDIT, NOTE_CANCEL,
    SESSION_NAV, SESSION_SELECT_NEW, SESSION_SELECT_RESUME, SESSION_PICK,
    SESSION_PICK_CROSS, SESSION_SAVE, SESSION_DISCARD, SESSION_BACK,
    SESSION_RECENT, SESSION_STARRED, SESSION_CANCEL,
    ROUTE_CONFIRM, ROUTE_KEEP,
    build_note_proposal_keyboard, build_route_proposal_keyboard
)

# Configure logging
logger = logging.getLogger('loam.bot')
logger.setLevel(logging.DEBUG)


class Loam:
    """Telegram bot for Obsidian vault management with Claude Code."""

    def __init__(self, params: dict):
        if 'TELEGRAM_BOT_KEY' not in os.environ:
            load_api_keys('telegram')

        self.params = params
        self.verbose = params.get('verbose', True)
        self.bot = Bot(token=os.environ['TELEGRAM_BOT_KEY'])
        self.dp = Dispatcher()
        self.repo_path = get_repo_path()

        # Initialize managers
        self.scope_manager = ScopeManager()
        self.session_handlers = SessionHandlers(self.scope_manager)
        self.claude_pool = ClaudeSessionPool(self.scope_manager)

        # Set up route callback for session handlers
        self.session_handlers.on_route_ready = self._on_route_ready

        # User message queues (for batching rapid messages)
        self.user_messages: dict[int, list] = defaultdict(list)
        self.user_tasks: dict[int, asyncio.Task] = {}

        # Pending note proposals per user
        self._pending_proposals: dict[int, NoteProposal] = {}
        # Users awaiting edit instructions
        self._awaiting_edit: set[int] = set()

        # Pending route proposals per user: {user_id: {"proposal": RouteProposal, "original_message": str}}
        self._pending_routes: dict[int, dict] = {}

        # # Load admin user
        # admin_path = os.path.join(self.repo_path, '.telegram_admin_user_id')
        # if os.path.exists(admin_path):
        #     with open(admin_path, 'r') as f:
        #         self.admin_user_id = int(f.read().strip())
        # else:
        #     raise ValueError('Please add your telegram user id in .telegram_admin_user_id')

        self._setup_handlers()

    def _setup_handlers(self):
        """Register all message and callback handlers."""

        @self.dp.message(CommandStart())
        async def handle_start(message: types.Message):
            """Handle /start command."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await self._add_user(user_id)

            scope = self.scope_manager.get_active_scope(user_id)
            session = self.scope_manager.get_current_session(user_id, scope)

            text = ("Hey! I'm Loam.\n"
                    "This is a cultivated space where links, notes, and thoughts grow over time.\n\n")

            text += "**Folders** organize your notes by topic.\n"
            text += "**Sessions** are conversations within a folder.\n\n"

            if session:
                scope_display = scope or "Notes (root)"
                name = session.get('description') or "(unnamed)"
                starred = " ⭐" if session.get('starred') else ""
                text += f"📂 Folder: `{scope_display}`\n"
                text += f"💬 Session: _{name}{starred}_\n\n"
            elif scope is not None:
                # User has an active scope but no session spawned yet (after /new, before first message)
                scope_display = scope or "Notes (root)"
                text += f"📂 Folder: `{scope_display}`\n"
                text += f"💬 Session: _(unnamed)_\n\n"
            else:
                text += "_No active session_\n\n"

            text += "**Commands:**\n"
            text += "`/new` — Start a new session\n"
            text += "`/switch` — Switch to another session\n"
            text += "`/session` — Show current folder & session\n"
            text += "`/create` — Create a new folder\n"
            text += "`/list` — List notes in current folder\n"
            text += "`/rename` `/star` `/unstar` — Manage sessions"

            await message.answer(text, parse_mode='Markdown')

        @self.dp.message(Command('session'))
        async def handle_session(message: types.Message):
            """Handle /session command - show current scope and session."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_session_command(message)

        @self.dp.message(Command('create'))
        async def handle_create(message: types.Message):
            """Handle /create command - shortcut to create folder."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            # Start create flow at notes (root)
            text = "Create new folder\n\n"
            text += "Navigate to the location where you want to create a folder:\n"

            from src.ui.keyboards import build_create_position_keyboard
            keyboard = build_create_position_keyboard(self.scope_manager, '')

            await message.answer(text, reply_markup=keyboard, parse_mode='Markdown')

        @self.dp.message(Command('list'))
        async def handle_list(message: types.Message):
            """Handle /list command - list notes in current scope."""
            user_id = message.chat.id
            active_scope = self.scope_manager.get_active_scope(user_id)
            scope_path = self.scope_manager.get_absolute_path(active_scope)

            if not os.path.exists(scope_path):
                await message.reply("Scope folder doesn't exist. Use /new to start a session.")
                return

            # List markdown files
            notes = []
            for item in sorted(os.listdir(scope_path)):
                if item.endswith('.md') and not item.startswith('.'):
                    notes.append(item)

            if notes:
                scope_display = active_scope or "Notes (root)"
                text = f"Notes in {scope_display}:\n\n"
                for note in notes[:20]:
                    text += f"• {note}\n"
                if len(notes) > 20:
                    text += f"\n_...and {len(notes) - 20} more_"
            else:
                text = "_No notes in this folder yet._"

            await message.answer(text, parse_mode='Markdown')

        @self.dp.message(Command('new'))
        async def handle_new(message: types.Message):
            """Handle /new command - start new session in current scope."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_new_command(message)

        @self.dp.message(Command('switch'))
        async def handle_switch(message: types.Message):
            """Handle /switch command - browse and switch to another session."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_switch_command(message)

        @self.dp.message(Command('rename'))
        async def handle_rename(message: types.Message):
            """Handle /rename command - rename current session."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_rename_command(message)

        @self.dp.message(Command('star'))
        async def handle_star(message: types.Message):
            """Handle /star command - star current session."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_star_command(message)

        @self.dp.message(Command('unstar'))
        async def handle_unstar(message: types.Message):
            """Handle /unstar command - unstar current session."""
            user_id = message.chat.id
            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            await self.session_handlers.handle_unstar_command(message)

        # Callback handlers for create flow
        @self.dp.callback_query(F.data.startswith('create_'))
        async def handle_create_callback(callback: types.CallbackQuery):
            await self._handle_create_callback(callback)

        # Callback handlers for note proposal confirmation
        @self.dp.callback_query(F.data.in_({NOTE_APPROVE, NOTE_EDIT, NOTE_CANCEL}))
        async def handle_note_proposal_callback(callback: types.CallbackQuery):
            await self._handle_note_proposal_callback(callback)

        # Callback handler for session navigation
        @self.dp.callback_query(F.data.startswith(SESSION_NAV) | (F.data == SESSION_BACK))
        async def handle_session_nav_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_nav_callback(callback)

        # Callback handler for selecting scope for new session
        @self.dp.callback_query(F.data.startswith(SESSION_SELECT_NEW))
        async def handle_session_select_new_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_select_new_callback(callback)

        # Callback handler for selecting scope to show sessions
        @self.dp.callback_query(F.data.startswith(SESSION_SELECT_RESUME))
        async def handle_session_select_resume_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_select_resume_callback(callback)

        # Callback handler for picking specific session to resume
        @self.dp.callback_query(F.data.startswith(SESSION_PICK))
        async def handle_session_pick_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_pick_session_callback(callback)

        # Callback handler for session save/discard
        @self.dp.callback_query(F.data.in_({SESSION_SAVE, SESSION_DISCARD}))
        async def handle_session_save_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_save_discard_callback(callback)

        # Callback handler for recent sessions
        @self.dp.callback_query(F.data == SESSION_RECENT)
        async def handle_session_recent_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_recent_callback(callback)

        # Callback handler for starred sessions
        @self.dp.callback_query(F.data == SESSION_STARRED)
        async def handle_session_starred_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_starred_callback(callback)

        # Callback handler for cancel
        @self.dp.callback_query(F.data == SESSION_CANCEL)
        async def handle_session_cancel_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_cancel_callback(callback)

        # Callback handler for cross-scope session pick
        @self.dp.callback_query(F.data.startswith(SESSION_PICK_CROSS))
        async def handle_session_pick_cross_callback(callback: types.CallbackQuery):
            await self.session_handlers.handle_pick_cross_callback(callback)

        # Callback handler for route proposals
        @self.dp.callback_query(F.data.startswith(ROUTE_CONFIRM) | (F.data == ROUTE_KEEP))
        async def handle_route_callback(callback: types.CallbackQuery):
            await self._handle_route_callback(callback)

        # Document handler (PDF, etc.) - must be before regular message handler
        @self.dp.message(F.document)
        async def handle_document(message: types.Message):
            """Handle document uploads (PDFs, etc.)."""
            await self._handle_document(message)

        # Regular message handler (must be last)
        # Known commands (for unknown command detection)
        known_commands = {
            '/start', '/session', '/new', '/switch', '/rename',
            '/star', '/unstar', '/create', '/list'
        }

        @self.dp.message()
        async def handle_message(message: types.Message):
            """Handle regular messages - route to Claude Code."""
            user_id = message.chat.id

            if not await self._is_valid_user(user_id):
                await message.reply("Please /start first.")
                return

            # Check for unknown commands
            if message.text and message.text.startswith('/'):
                cmd = message.text.split()[0].split('@')[0].lower()
                if cmd not in known_commands:
                    await message.reply(
                        f"Unknown command: `{cmd}`\n\nUse /start to see available commands.",
                        parse_mode='Markdown'
                    )
                    return

            # Check if awaiting session name input (save before switch)
            if await self.session_handlers.handle_session_name_input(message):
                return

            # Check if awaiting rename input
            if await self.session_handlers.handle_rename_input(message):
                return

            # Check if awaiting folder name for create flow
            if user_id in self._awaiting_create_name:
                await self._handle_create_name_input(message)
                return

            # Check if awaiting edit instructions for a proposal
            if user_id in self._awaiting_edit:
                await self._handle_edit_instructions(message)
                return

            # Route to Claude Code session
            await self._process_message(message)

    async def _handle_create_callback(self, callback: types.CallbackQuery):
        """Handle create folder navigation callbacks."""
        user_id = callback.from_user.id
        data = callback.data

        if data.startswith('create_nav:'):
            # Navigate into folder
            folder_path = data[len('create_nav:'):]
            self.scope_manager.set_nav_position(user_id, folder_path)

            folder_display = folder_path or "Notes (root)"
            text = f"{folder_display}\n\nSelect location or navigate deeper:"

            from src.ui.keyboards import build_create_position_keyboard
            keyboard = build_create_position_keyboard(self.scope_manager, folder_path)

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif data == 'create_back':
            current = self.scope_manager.get_nav_position(user_id)
            parent = self.scope_manager.get_parent_path(current)
            self.scope_manager.set_nav_position(user_id, parent)

            folder_display = parent or "Notes (root)"
            text = f"📁 {folder_display}\n\nSelect location:"

            from src.ui.keyboards import build_create_position_keyboard
            keyboard = build_create_position_keyboard(self.scope_manager, parent)

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif data.startswith('create_here:'):
            parent_path = data[len('create_here:'):]
            folder_display = parent_path or "Notes (root)"

            text = f"Creating in {folder_display}\n\n"
            text += "What should the folder be called?\n"
            text += "_Reply with the folder name:_"

            self._awaiting_create_name[user_id] = parent_path

            await callback.message.edit_text(text, parse_mode='Markdown')

        elif data == 'create_cancel':
            await callback.message.edit_text("❌ Cancelled folder creation.")

        await callback.answer()

    # Track users awaiting folder name for create
    _awaiting_create_name: dict[int, str] = {}

    async def _handle_create_name_input(self, message: types.Message):
        """Handle folder name input during create flow."""
        user_id = message.chat.id
        parent_path = self._awaiting_create_name.pop(user_id, '')
        folder_name = message.text.strip()

        # Validate
        if not folder_name or '/' in folder_name or folder_name.startswith('.'):
            await message.reply(
                "❌ Invalid folder name. Avoid `/`, `.` at start, and empty names.",
                parse_mode='Markdown'
            )
            return

        new_path = f"{parent_path}/{folder_name}" if parent_path else folder_name

        if self.scope_manager.folder_exists(new_path):
            await message.reply(f"❌ Folder {new_path} already exists.", parse_mode='Markdown')
            return

        if self.scope_manager.create_folder(new_path):
            self.scope_manager.set_active_scope(user_id, new_path)
            text = f"✓ Created {new_path}\n\nSwitched to this folder. Ready to chat!"
            await message.reply(text, parse_mode='Markdown')
        else:
            await message.reply("❌ Failed to create folder.")

    async def _handle_document(self, message: types.Message):
        """Handle document uploads - save to attachments and process with Claude."""
        user_id = message.chat.id

        if not await self._is_valid_user(user_id):
            await message.reply("Please /start first.")
            return

        active_scope = self.scope_manager.get_active_scope(user_id)

        if active_scope is None:
            await message.reply(
                "No active session. Use /new to start one.",
                parse_mode='Markdown'
            )
            return

        document = message.document
        if not document:
            return

        # Get file info
        file_name = document.file_name or f"document_{document.file_id}"
        file_size = document.file_size or 0
        mime_type = document.mime_type or "application/octet-stream"

        # Check file size (limit to 20MB)
        max_size = 20 * 1024 * 1024
        if file_size > max_size:
            await message.reply(f"❌ File too large. Max size is 20MB.")
            return

        # Determine if it's a supported type
        supported_types = {
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'text/markdown': '.md',
            'application/json': '.json',
        }

        # Also support by extension
        ext = os.path.splitext(file_name)[1].lower() if file_name else ''
        is_supported = mime_type in supported_types or ext in ['.pdf', '.txt', '.md', '.json']

        if not is_supported:
            await message.reply(
                f"⚠️ File type `{mime_type}` may not be fully readable.\n"
                f"Saving anyway - Claude will try to process it.",
                parse_mode='Markdown'
            )

        # Create attachments folder if needed
        scope_path = self.scope_manager.get_absolute_path(active_scope)
        attachments_path = os.path.join(scope_path, 'attachments')
        os.makedirs(attachments_path, exist_ok=True)

        # Generate safe filename
        safe_name = self._sanitize_filename(file_name)
        file_path = os.path.join(attachments_path, safe_name)

        # Handle duplicates
        base, ext = os.path.splitext(safe_name)
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(attachments_path, f"{base}_{counter}{ext}")
            counter += 1

        # Download and save file
        try:
            await message.reply(f"📥 Downloading `{file_name}`...", parse_mode='Markdown')

            file = await self.bot.get_file(document.file_id)
            await self.bot.download_file(file.file_path, file_path)

            # Get relative path for Claude (relative to scope)
            relative_path = f"attachments/{os.path.basename(file_path)}"

            logger.info(f"[User {user_id}] Saved document: {file_path}")

        except Exception as e:
            await message.reply(f"❌ Failed to download file: {str(e)[:100]}")
            return

        # Build message for Claude
        caption = message.caption or ""
        if caption:
            prompt = f"I've uploaded a file: `{relative_path}`\n\nUser note: {caption}\n\nPlease read and process this file."
        else:
            prompt = f"I've uploaded a file: `{relative_path}`\n\nPlease read this file and give me a summary. If it's a PDF or document, extract the key information."

        # Send to Claude with continuous typing
        typing_task = asyncio.create_task(self._keep_typing(user_id))

        try:
            response = await self.claude_pool.chat(user_id, prompt)
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if response.error:
            await message.reply(f"❌ Error processing file: {response.error[:200]}")
            return

        if response.text:
            # Prepend file saved confirmation
            full_response = f"📎 Saved to `{relative_path}`\n\n{response.text}"
            chunks = self._split_message(full_response, 4000)

            for chunk in chunks:
                await self.bot.send_message(
                    user_id,
                    chunk,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
        else:
            await message.reply(
                f"📎 Saved to `{relative_path}`\n\n_No response from Claude._",
                parse_mode='Markdown'
            )

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize a filename for safe storage."""
        # Remove or replace problematic characters
        import re
        # Keep alphanumeric, dots, underscores, hyphens
        safe = re.sub(r'[^\w\-_\.]', '_', filename)
        # Remove leading dots
        safe = safe.lstrip('.')
        # Ensure not empty
        if not safe:
            safe = "document"
        return safe

    async def _process_message(self, message: types.Message):
        """Process regular message - route to Claude Code."""
        user_id = message.chat.id
        active_scope = self.scope_manager.get_active_scope(user_id)

        # Check if user has set up a scope (via /new)
        # Session ID may be None if this is the first message after /new - that's OK,
        # Claude will create a new session
        if active_scope is None:
            await message.reply(
                "No active session. Use /new to start one.",
                parse_mode='Markdown'
            )
            return

        # Add message to queue
        self.user_messages[user_id].append(message.text)

        # Cancel any existing task for this user (they sent a new message)
        if user_id in self.user_tasks and self.user_tasks[user_id]:
            self.user_tasks[user_id].cancel()
            try:
                await self.user_tasks[user_id]
            except asyncio.CancelledError:
                pass

        # Start new processing task
        self.user_tasks[user_id] = asyncio.create_task(
            self._process_user_messages(user_id, message)
        )

    async def _process_user_messages(self, user_id: int, original_message: types.Message):
        """Process queued messages for a user through Claude Code."""
        # Small delay to batch rapid messages
        await asyncio.sleep(0.5)

        # Get all queued messages
        messages = self.user_messages[user_id].copy()
        self.user_messages[user_id].clear()

        if not messages:
            return

        # Combine messages
        combined_message = "\n".join(messages)
        active_scope = self.scope_manager.get_active_scope(user_id)

        logger.info(f"[User {user_id}] Processing message in scope '{active_scope}'")
        logger.debug(f"[User {user_id}] Message: {combined_message[:200]}...")

        # Start continuous typing indicator
        typing_task = asyncio.create_task(self._keep_typing(user_id))

        try:
            # Send to Claude
            response = await self.claude_pool.chat(user_id, combined_message)
        finally:
            # Stop typing indicator
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if response.error:
            error_text = f"❌ Error: {response.error[:200]}"
            await original_message.reply(error_text)
            return

        if response.text:
            # Split long messages (Telegram limit is 4096 chars)
            text = response.text
            chunks = self._split_message(text, 4000)

            for chunk in chunks:
                await self.bot.send_message(
                    user_id,
                    chunk,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )

        # Check if there's a route proposal
        if response.route_proposal:
            await self._show_route_proposal(user_id, response.route_proposal, combined_message)

        # Check if there's a note proposal to show
        if response.proposal:
            await self._show_proposal_preview(user_id, response.proposal)
        elif not response.text and not response.route_proposal:
            await original_message.reply("_No response from Claude._", parse_mode='Markdown')

        # Apply profile updates silently
        if response.profile_update:
            self.scope_manager.update_user_profile(response.profile_update.content)
            logger.info(f"[User {user_id}] Profile updated")

    async def _show_proposal_preview(self, user_id: int, proposal: NoteProposal):
        """Show a note proposal with approve/edit/cancel buttons."""
        # Store the pending proposal
        self._pending_proposals[user_id] = proposal

        # Build preview message
        action = "edit" if proposal.is_edit else "new"
        text = f"📄 `{proposal.filename}` _({action})_\n\n"

        # Truncate content preview if too long
        content_preview = proposal.content
        if len(content_preview) > 2000:
            content_preview = content_preview[:2000] + "\n…"

        text += f"```\n{content_preview}\n```"

        keyboard = build_note_proposal_keyboard()

        await self.bot.send_message(
            user_id,
            text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    async def _handle_note_proposal_callback(self, callback: types.CallbackQuery):
        """Handle approve/edit/cancel for note proposals."""
        user_id = callback.from_user.id
        data = callback.data

        proposal = self._pending_proposals.get(user_id)
        if not proposal:
            await callback.message.edit_text("❌ No pending proposal found.")
            await callback.answer()
            return

        if data == NOTE_APPROVE:
            # Tell Claude to create the note
            self._pending_proposals.pop(user_id, None)

            # Create folder structure if needed
            filename = proposal.filename.lstrip('/')
            if '/' in filename:
                folder_path = os.path.dirname(filename)
                active_scope = self.scope_manager.get_active_scope(user_id)
                full_folder_path = os.path.join(
                    self.scope_manager.get_absolute_path(active_scope),
                    folder_path
                )
                if not os.path.exists(full_folder_path):
                    os.makedirs(full_folder_path, exist_ok=True)
                    # Also create attachments subfolder
                    os.makedirs(os.path.join(full_folder_path, 'attachments'), exist_ok=True)
                    logger.info(f"[User {user_id}] Created folder structure: {folder_path}")

            await callback.message.edit_text(
                f"✓ Approved. Creating `{proposal.filename}`...",
                parse_mode='Markdown'
            )

            # Send approval to Claude
            typing_task = asyncio.create_task(self._keep_typing(user_id))
            try:
                response = await self.claude_pool.chat(
                    user_id,
                    f"Approved. Please create the file `{proposal.filename}` with the proposed content now."
                )
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

            if response.error:
                await self.bot.send_message(user_id, f"❌ Error: {response.error[:200]}")
            elif response.text:
                await self.bot.send_message(
                    user_id,
                    response.text,
                    parse_mode='Markdown'
                )

        elif data == NOTE_EDIT:
            # Ask for edit instructions
            self._awaiting_edit.add(user_id)

            await callback.message.edit_text(
                f"✏️ Editing `{proposal.filename}`\n\n"
                f"What changes would you like? Reply with your instructions:",
                parse_mode='Markdown'
            )

        elif data == NOTE_CANCEL:
            # Cancel the proposal
            self._pending_proposals.pop(user_id, None)

            await callback.message.edit_text("❌ Cancelled note creation.")

            # Notify Claude
            await self.claude_pool.chat(
                user_id,
                "The user cancelled the note creation. Don't create the file."
            )

        await callback.answer()

    async def _handle_edit_instructions(self, message: types.Message):
        """Handle edit instructions for a pending proposal."""
        user_id = message.chat.id
        self._awaiting_edit.discard(user_id)

        proposal = self._pending_proposals.get(user_id)
        if not proposal:
            await message.reply("No pending proposal to edit.")
            return

        edit_instructions = message.text

        # Send edit request to Claude
        typing_task = asyncio.create_task(self._keep_typing(user_id))

        try:
            response = await self.claude_pool.chat(
                user_id,
                f"Please revise the proposed note `{proposal.filename}` with these changes: {edit_instructions}\n\n"
                f"Show me the updated proposal using the same [PROPOSE_NOTE: ...] format."
            )
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if response.error:
            await message.reply(f"❌ Error: {response.error[:200]}")
            return

        if response.text:
            chunks = self._split_message(response.text, 4000)
            for chunk in chunks:
                await self.bot.send_message(
                    user_id,
                    chunk,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )

        # If Claude proposed a new version, show it
        if response.proposal:
            # Clear old proposal, show new one
            self._pending_proposals.pop(user_id, None)
            await self._show_proposal_preview(user_id, response.proposal)
        else:
            # No new proposal - maybe Claude made inline edits
            self._pending_proposals.pop(user_id, None)

    async def _show_route_proposal(self, user_id: int, proposal: RouteProposal, original_message: str):
        """Show a route proposal with confirm/keep buttons."""
        # Store the pending route
        self._pending_routes[user_id] = {
            "proposal": proposal,
            "original_message": original_message
        }

        current_scope = self.scope_manager.get_active_scope(user_id)
        current_display = current_scope or "Notes (root)"
        target_display = proposal.target_scope or "Notes (root)"

        text = f"📍 **Routing suggestion**\n\n"
        text += f"_{proposal.reason}_\n\n"
        text += f"Current: `{current_display}` → Suggested: `{target_display}`"

        keyboard = build_route_proposal_keyboard(proposal.target_scope)

        await self.bot.send_message(
            user_id,
            text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    async def _handle_route_callback(self, callback: types.CallbackQuery):
        """Handle route confirm/keep callbacks."""
        user_id = callback.from_user.id
        data = callback.data

        pending = self._pending_routes.get(user_id)
        if not pending:
            await callback.message.edit_text("❌ Route proposal expired.")
            await callback.answer()
            return

        proposal = pending["proposal"]
        original_message = pending["original_message"]

        if data == ROUTE_KEEP:
            # Keep in current scope - just clear the pending route
            self._pending_routes.pop(user_id, None)
            await callback.message.edit_text("✓ Keeping content in current scope.")
            await callback.answer()
            return

        if data.startswith(ROUTE_CONFIRM):
            target_scope = data[len(ROUTE_CONFIRM):]

            # Check if current session is unnamed - need to ask save/discard
            current_scope = self.scope_manager.get_active_scope(user_id)
            current_session = self.scope_manager.get_current_session(user_id, current_scope)

            if current_session and not current_session.get('description'):
                # Store route action as pending in session_handlers
                self.session_handlers.pending_actions[user_id] = {
                    "action": "route",
                    "target_scope": target_scope,
                    "original_message": original_message
                }
                # Clear our pending route
                self._pending_routes.pop(user_id, None)

                # Ask save/discard
                scope_display = current_scope or "Notes (root)"
                text = f"Your current session in **{scope_display}** is unnamed.\n\n"
                text += "Would you like to save it before switching?"

                from src.ui.keyboards import build_save_discard_keyboard
                keyboard = build_save_discard_keyboard()

                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
            else:
                # Current session is named - proceed directly
                self._pending_routes.pop(user_id, None)
                await self._execute_route(callback, user_id, target_scope, original_message)

        await callback.answer()

    async def _execute_route(self, callback: types.CallbackQuery, user_id: int,
                             target_scope: str, original_message: str):
        """Execute routing: switch to target scope (content already processed, no re-send needed)."""
        # Resume or create session in target scope
        history = self.scope_manager.get_session_history(user_id, target_scope)
        if history:
            # Resume most recent session
            self.scope_manager.resume_session(user_id, target_scope, history[0]['id'])
        else:
            # Create new session
            self.scope_manager.create_new_session(user_id, target_scope)

        target_display = target_scope or "Notes (root)"
        await callback.message.edit_text(
            f"✓ Routed to **{target_display}**. Any notes will be created there.",
            parse_mode='Markdown'
        )
        # Note: Content was already processed and shown to user.
        # Any pending note proposal will be created in the new scope when approved.

    async def _on_route_ready(self, user_id: int, target_scope: str, original_message: str, context):
        """Callback from session_handlers when route action is ready after save/discard."""
        # Resume or create session in target scope
        history = self.scope_manager.get_session_history(user_id, target_scope)
        if history:
            self.scope_manager.resume_session(user_id, target_scope, history[0]['id'])
        else:
            self.scope_manager.create_new_session(user_id, target_scope)

        target_display = target_scope or "Notes (root)"

        # Context can be a message or callback
        if hasattr(context, 'reply'):
            await context.reply(
                f"✓ Routed to **{target_display}**. Any notes will be created there.",
                parse_mode='Markdown'
            )
        elif hasattr(context, 'message'):
            await context.message.edit_text(
                f"✓ Routed to **{target_display}**. Any notes will be created there.",
                parse_mode='Markdown'
            )
        # Note: Content was already processed. No re-send needed.

    async def _send_to_scope(self, user_id: int, message: str):
        """Send a message to the user's current scope and display response."""
        typing_task = asyncio.create_task(self._keep_typing(user_id))

        try:
            response = await self.claude_pool.chat(user_id, message)
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if response.error:
            await self.bot.send_message(user_id, f"❌ Error: {response.error[:200]}")
            return

        if response.text:
            chunks = self._split_message(response.text, 4000)
            for chunk in chunks:
                await self.bot.send_message(
                    user_id,
                    chunk,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )

        if response.proposal:
            await self._show_proposal_preview(user_id, response.proposal)

    async def _keep_typing(self, user_id: int):
        """Keep sending typing indicator until cancelled."""
        try:
            while True:
                await self.bot.send_chat_action(user_id, 'typing')
                await asyncio.sleep(4)  # Telegram typing expires after ~5 seconds
        except asyncio.CancelledError:
            pass

    def _split_message(self, text: str, max_length: int = 4000) -> list[str]:
        """Split a long message into chunks."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            # Find a good break point (newline or space)
            break_point = text.rfind('\n', 0, max_length)
            if break_point == -1:
                break_point = text.rfind(' ', 0, max_length)
            if break_point == -1:
                break_point = max_length

            chunks.append(text[:break_point])
            text = text[break_point:].lstrip()

        return chunks

    async def _is_valid_user(self, user_id: int) -> bool:
        """Check if user is valid."""
        valid_users_path = os.path.join(self.repo_path, '.telegram_valid_user_ids')
        if not os.path.exists(valid_users_path):
            return False
        with open(valid_users_path, 'r') as f:
            content = f.read().strip()
        if not content:
            return False
        return user_id in [int(x) for x in content.split('\n') if x.strip()]

    async def _add_user(self, user_id: int):
        """Add a new valid user."""
        valid_users_path = os.path.join(self.repo_path, '.telegram_valid_user_ids')
        with open(valid_users_path, 'a') as f:
            f.write(f'\n{user_id}')

    async def _register_commands(self):
        """Register bot commands with Telegram for autocomplete."""
        commands = [
            BotCommand(command="session", description="Show current folder & session"),
            BotCommand(command="new", description="Start new session"),
            BotCommand(command="switch", description="Switch to another session"),
            BotCommand(command="rename", description="Name current session"),
            BotCommand(command="star", description="Add session to favorites"),
            BotCommand(command="unstar", description="Remove from favorites"),
            BotCommand(command="create", description="Create new folder"),
            BotCommand(command="list", description="List notes in folder"),
        ]
        await self.bot.set_my_commands(commands)
        logger.info("Bot commands registered with Telegram")

    async def start(self):
        """Start the bot."""
        await self._register_commands()
        await self.dp.start_polling(self.bot)

    def run(self):
        """Run the bot."""
        asyncio.run(self.start())