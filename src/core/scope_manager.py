import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils import get_repo_path


class ScopeManager:
    """
    Manages folder scopes and user session state for the Obsidian vault.

    Each user has:
    - An active scope (folder path relative to notes/)
    - A mapping of scope -> session_id for Claude Code sessions
    - Current navigation position (for tree browsing)
    """

    def __init__(self, notes_path: Optional[str] = None, vault_path: Optional[str] = None,
                 user_states_path: Optional[str] = None):
        """
        Initialize ScopeManager.

        Args:
            notes_path: Deprecated, use vault_path instead.
            vault_path: Path to the Obsidian vault (notes folder).
            user_states_path: Path to store user state files. If None, uses data/scope_states.
        """
        self.repo_path = get_repo_path()

        # Handle vault path (prefer vault_path over notes_path for clarity)
        if vault_path:
            self.notes_path = vault_path
        elif notes_path:
            self.notes_path = notes_path
        else:
            # Check for environment variable (useful for testing)
            self.notes_path = os.environ.get('LOAM_VAULT_PATH') or os.path.join(self.repo_path, 'notes')

        # Handle user states path (allow override for testing)
        if user_states_path:
            self.user_states_path = user_states_path
        else:
            self.user_states_path = os.path.join(self.repo_path, 'data', 'scope_states')

        os.makedirs(self.user_states_path, exist_ok=True)

    def get_user_state_path(self, user_id: int) -> str:
        return os.path.join(self.user_states_path, f'{user_id}.json')

    def load_user_state(self, user_id: int) -> dict:
        """Load user's scope state from disk."""
        path = self.get_user_state_path(user_id)
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {
            'active_scope': '',  # empty string = root
            'nav_position': '',  # current position in tree browser
            'sessions': {}       # scope -> session_id mapping
        }

    def save_user_state(self, user_id: int, state: dict):
        """Save user's scope state to disk."""
        path = self.get_user_state_path(user_id)
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)

    def get_active_scope(self, user_id: int) -> str:
        """Get user's current active scope."""
        state = self.load_user_state(user_id)
        return state.get('active_scope', '')

    def set_active_scope(self, user_id: int, scope: str):
        """Set user's active scope."""
        state = self.load_user_state(user_id)
        state['active_scope'] = scope
        self.save_user_state(user_id, state)

    def get_nav_position(self, user_id: int) -> str:
        """Get current navigation position in tree browser."""
        state = self.load_user_state(user_id)
        return state.get('nav_position', '')

    def set_nav_position(self, user_id: int, position: str):
        """Set navigation position in tree browser."""
        state = self.load_user_state(user_id)
        state['nav_position'] = position
        self.save_user_state(user_id, state)

    def get_absolute_path(self, relative_scope: str) -> str:
        """Convert relative scope to absolute path."""
        if relative_scope:
            return os.path.join(self.notes_path, relative_scope)
        return self.notes_path

    # Folders to hide from navigation
    HIDDEN_FOLDERS = {'attachments', '.obsidian', '.git'}

    def list_folders(self, relative_path: str = '') -> list[str]:
        """
        List immediate subfolders at the given path.
        Returns folder names (not full paths).
        Excludes hidden folders and special folders like attachments.
        """
        abs_path = self.get_absolute_path(relative_path)

        if not os.path.exists(abs_path):
            return []

        folders = []
        for item in sorted(os.listdir(abs_path)):
            item_path = os.path.join(abs_path, item)
            # Skip hidden folders, attachments, and other special folders
            if os.path.isdir(item_path) and not item.startswith('.') and item not in self.HIDDEN_FOLDERS:
                folders.append(item)

        return folders

    def get_all_folders_flat(self) -> list[str]:
        """
        Get all folder paths recursively as a flat list.
        Returns relative paths like ['philosophy', 'philosophy/epistemology', 'science'].
        """
        all_folders = []

        def recurse(path: str):
            subfolders = self.list_folders(path)
            for folder in subfolders:
                full_path = f"{path}/{folder}" if path else folder
                all_folders.append(full_path)
                recurse(full_path)

        recurse('')
        return all_folders

    def folder_exists(self, relative_path: str) -> bool:
        """Check if a folder exists."""
        abs_path = self.get_absolute_path(relative_path)
        return os.path.isdir(abs_path)

    def create_folder(self, relative_path: str) -> bool:
        """Create a new folder. Returns True if successful."""
        abs_path = self.get_absolute_path(relative_path)
        if os.path.exists(abs_path):
            return False
        os.makedirs(abs_path, exist_ok=True)
        # Create attachments subfolder
        os.makedirs(os.path.join(abs_path, 'attachments'), exist_ok=True)
        return True

    def get_parent_path(self, relative_path: str) -> str:
        """Get parent folder path. Returns '' for root."""
        if not relative_path or '/' not in relative_path:
            return ''
        return '/'.join(relative_path.split('/')[:-1])

    def get_folder_display_name(self, relative_path: str) -> str:
        """Get display name for a folder."""
        if not relative_path:
            return 'notes (root)'
        return relative_path.split('/')[-1]

    def get_all_folders_flat(self) -> list[str]:
        """Get all folders recursively as flat list of relative paths."""
        folders = []

        def walk(current_path: str):
            subfolders = self.list_folders(current_path)
            for folder in subfolders:
                full_rel_path = f"{current_path}/{folder}" if current_path else folder
                folders.append(full_rel_path)
                walk(full_rel_path)

        walk('')
        return folders

    def has_session(self, user_id: int, scope: str) -> bool:
        """Check if user has an existing session for this scope."""
        return self.get_session_id(user_id, scope) is not None

    # ─────────────────────────────────────────────────────────────────────────
    # Multi-session management (with descriptions and starring)
    # ─────────────────────────────────────────────────────────────────────────

    MAX_UNSTARRED_SESSIONS = 10  # Keep last N unstarred sessions per scope

    def _get_scope_sessions(self, user_id: int, scope: str) -> dict:
        """
        Get session data for a scope.
        Handles migration from old formats.

        Returns: {"active": session_id or None, "history": [...]}
        Session format: {"id", "description" (nullable), "starred", "created"}
        """
        state = self.load_user_state(user_id)
        sessions = state.get('sessions', {})
        scope_data = sessions.get(scope)

        # Handle old format: just a string session_id
        if isinstance(scope_data, str):
            return {
                "active": scope_data,
                "history": [{
                    "id": scope_data,
                    "description": None,
                    "starred": False,
                    "created": None
                }]
            }

        # New format - ensure all sessions have starred field
        if isinstance(scope_data, dict):
            history = scope_data.get('history', [])
            for session in history:
                if 'starred' not in session:
                    session['starred'] = False
                # Migrate "(no description)" to None
                if session.get('description') in ['(no description)', '(unnamed)', '(migrated session)']:
                    session['description'] = None
            return scope_data

        return {"active": None, "history": []}

    def _set_scope_sessions(self, user_id: int, scope: str, scope_data: dict):
        """Save session data for a scope."""
        state = self.load_user_state(user_id)
        if 'sessions' not in state:
            state['sessions'] = {}
        state['sessions'][scope] = scope_data
        self.save_user_state(user_id, state)

    def _evict_old_sessions(self, history: list[dict]) -> list[dict]:
        """
        Evict oldest unstarred sessions if over limit.
        Starred sessions are never evicted.
        """
        starred = [s for s in history if s.get('starred')]
        unstarred = [s for s in history if not s.get('starred')]

        # Keep only MAX_UNSTARRED_SESSIONS unstarred (they're ordered newest first)
        unstarred = unstarred[:self.MAX_UNSTARRED_SESSIONS]

        # Merge back, maintaining order (starred can be anywhere in timeline)
        # Simple approach: starred first, then unstarred
        # Better: interleave by created date, but for now keep it simple
        return starred + unstarred

    def get_session_id(self, user_id: int, scope: str) -> Optional[str]:
        """Get active Claude Code session ID for a scope."""
        scope_data = self._get_scope_sessions(user_id, scope)
        return scope_data.get('active')

    def get_current_session(self, user_id: int, scope: str) -> Optional[dict]:
        """Get the current active session object (with description, starred, etc.)."""
        scope_data = self._get_scope_sessions(user_id, scope)
        active_id = scope_data.get('active')
        if not active_id:
            return None

        for session in scope_data.get('history', []):
            if session['id'] == active_id:
                return session
        return None

    def is_current_session_named(self, user_id: int, scope: str) -> bool:
        """Check if the current session has a name (description)."""
        session = self.get_current_session(user_id, scope)
        return session is not None and session.get('description') is not None

    def set_session_id(self, user_id: int, scope: str, session_id: str):
        """
        Save Claude Code session ID for a scope.
        If this is a new session (different from current active), add to history.
        New sessions start unnamed (description=None).
        """
        scope_data = self._get_scope_sessions(user_id, scope)
        current_active = scope_data.get('active')

        # If same session, just ensure it's active
        if session_id == current_active:
            return

        # Update active session and scope
        scope_data['active'] = session_id

        # Also update user's active scope
        state = self.load_user_state(user_id)
        state['active_scope'] = scope

        # Add to history if not already present
        history = scope_data.get('history', [])
        existing_ids = {h['id'] for h in history}

        if session_id not in existing_ids:
            history.insert(0, {
                "id": session_id,
                "description": None,  # Unnamed until user names it
                "starred": False,
                "created": datetime.now().isoformat()
            })
            # Evict old unstarred sessions
            scope_data['history'] = self._evict_old_sessions(history)

        state['sessions'][scope] = scope_data
        self.save_user_state(user_id, state)

    def get_session_history(self, user_id: int, scope: str) -> list[dict]:
        """
        Get session history for a scope.
        Returns list of {"id", "description", "starred", "created"}
        Most recent first.
        """
        scope_data = self._get_scope_sessions(user_id, scope)
        return scope_data.get('history', [])

    def create_new_session(self, user_id: int, scope: str) -> None:
        """
        Prepare to start a new session in a scope.
        Clears active session so next message creates a fresh one.
        Also updates active_scope.
        """
        state = self.load_user_state(user_id)
        state['active_scope'] = scope

        # Clear active session for this scope (but keep history)
        if 'sessions' not in state:
            state['sessions'] = {}
        scope_data = self._get_scope_sessions(user_id, scope)
        scope_data['active'] = None
        state['sessions'][scope] = scope_data

        self.save_user_state(user_id, state)

    def resume_session(self, user_id: int, scope: str, session_id: str) -> bool:
        """
        Resume a session from history.
        Also updates active_scope.
        Returns True if session was found and activated.
        """
        scope_data = self._get_scope_sessions(user_id, scope)
        history = scope_data.get('history', [])

        # Find session in history
        for session in history:
            if session['id'] == session_id:
                scope_data['active'] = session_id
                self._set_scope_sessions(user_id, scope, scope_data)
                # Update active scope
                self.set_active_scope(user_id, scope)
                return True

        return False

    def rename_session(self, user_id: int, scope: str, session_id: str, description: str):
        """Rename a session (set its description)."""
        scope_data = self._get_scope_sessions(user_id, scope)
        history = scope_data.get('history', [])

        for session in history:
            if session['id'] == session_id:
                session['description'] = description
                self._set_scope_sessions(user_id, scope, scope_data)
                return

    def star_session(self, user_id: int, scope: str, session_id: str) -> bool:
        """Star a session (won't be evicted). Returns True if found."""
        scope_data = self._get_scope_sessions(user_id, scope)
        history = scope_data.get('history', [])

        for session in history:
            if session['id'] == session_id:
                session['starred'] = True
                self._set_scope_sessions(user_id, scope, scope_data)
                return True
        return False

    def unstar_session(self, user_id: int, scope: str, session_id: str) -> bool:
        """Unstar a session. Returns True if found."""
        scope_data = self._get_scope_sessions(user_id, scope)
        history = scope_data.get('history', [])

        for session in history:
            if session['id'] == session_id:
                session['starred'] = False
                # Re-run eviction in case we're now over limit
                scope_data['history'] = self._evict_old_sessions(history)
                self._set_scope_sessions(user_id, scope, scope_data)
                return True
        return False

    def discard_current_session(self, user_id: int, scope: str):
        """
        Discard (remove) the current session from history.
        Used when user chooses not to save an unnamed session.
        """
        scope_data = self._get_scope_sessions(user_id, scope)
        active_id = scope_data.get('active')

        if active_id:
            history = scope_data.get('history', [])
            scope_data['history'] = [s for s in history if s['id'] != active_id]
            scope_data['active'] = None
            self._set_scope_sessions(user_id, scope, scope_data)

    # ─────────────────────────────────────────────────────────────────────────
    # Cross-scope session queries
    # ─────────────────────────────────────────────────────────────────────────

    def get_recent_sessions_all_scopes(self, user_id: int, limit: int = 5) -> list[dict]:
        """
        Get the most recently created sessions across all scopes.

        Returns list of {"id", "description", "starred", "created", "scope"}
        Sorted by created date, most recent first.
        """
        state = self.load_user_state(user_id)
        sessions_data = state.get('sessions', {})

        all_sessions = []
        for scope, scope_data in sessions_data.items():
            # Handle old format (just a string)
            if isinstance(scope_data, str):
                all_sessions.append({
                    "id": scope_data,
                    "description": None,
                    "starred": False,
                    "created": None,
                    "scope": scope
                })
            elif isinstance(scope_data, dict):
                for session in scope_data.get('history', []):
                    all_sessions.append({
                        **session,
                        "scope": scope
                    })

        # Sort by created date (most recent first), None dates go last
        def sort_key(s):
            created = s.get('created')
            if created is None:
                return ''
            return created

        all_sessions.sort(key=sort_key, reverse=True)

        return all_sessions[:limit]

    def get_starred_sessions_all_scopes(self, user_id: int) -> list[dict]:
        """
        Get all starred sessions across all scopes.

        Returns list of {"id", "description", "starred", "created", "scope"}
        Sorted by scope name for grouping.
        """
        state = self.load_user_state(user_id)
        sessions_data = state.get('sessions', {})

        starred = []
        for scope, scope_data in sessions_data.items():
            if isinstance(scope_data, dict):
                for session in scope_data.get('history', []):
                    if session.get('starred'):
                        starred.append({
                            **session,
                            "scope": scope
                        })

        # Sort by scope name for easy reading
        starred.sort(key=lambda s: s.get('scope', ''))

        return starred