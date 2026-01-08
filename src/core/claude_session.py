"""
Claude Code Session Manager

Manages Claude Code CLI sessions - spawning, resuming, and communicating.
Each scope folder gets its own persistent session.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from src.core.scope_manager import ScopeManager

# Configure logging
logger = logging.getLogger('loam.claude_session')
logger.setLevel(logging.DEBUG)


@dataclass
class NoteProposal:
    """A proposed note creation/edit."""
    filename: str
    content: str
    is_edit: bool = False  # True if editing existing, False if new


@dataclass
class RouteProposal:
    """A proposed route to a different scope."""
    target_scope: str
    reason: str


@dataclass
class ClaudeResponse:
    """Response from Claude Code session."""
    text: str
    session_id: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None
    proposal: Optional[NoteProposal] = None  # If Claude proposed a note
    route_proposal: Optional[RouteProposal] = None  # If Claude suggests routing elsewhere


class ClaudeSessionManager:
    """
    Manages Claude Code CLI sessions.

    Each user+scope combination gets a persistent session that can be resumed.
    Sessions are run with cwd set to the scope folder for file isolation.
    """

    def __init__(self, scope_manager: ScopeManager):
        self.scope_manager = scope_manager
        self.verbose = True

    async def send_message(
        self,
        user_id: int,
        message: str,
        scope: str = ''
    ) -> ClaudeResponse:
        """
        Send a message to the Claude Code session for this user+scope.

        Creates a new session if none exists, or resumes the existing one.
        """
        # Get or create session ID for this scope
        session_id = self.scope_manager.get_session_id(user_id, scope)

        # Get absolute path for working directory
        cwd = self.scope_manager.get_absolute_path(scope)

        # Ensure the directory exists
        if not os.path.exists(cwd):
            return ClaudeResponse(
                text="",
                error=f"Scope folder does not exist: {scope}"
            )

        # Build the command
        cmd = self._build_command(message, session_id, scope, user_id)

        logger.info(f"[User {user_id}] Sending message to scope '{scope}'")
        logger.debug(f"[User {user_id}] Message: {message[:200]}{'...' if len(message) > 200 else ''}")
        logger.debug(f"[User {user_id}] Working dir: {cwd}")
        logger.debug(f"[User {user_id}] Session ID: {session_id or 'new'}")
        logger.debug(f"[User {user_id}] Command: {' '.join(cmd[:6])}...")

        try:
            # Run Claude CLI
            result = await self._run_claude(cmd, cwd, user_id)

            # Save session ID if we got one (new sessions start unnamed)
            if result.session_id and result.session_id != session_id:
                self.scope_manager.set_session_id(user_id, scope, result.session_id)
                logger.info(f"[User {user_id}] New session created: {result.session_id}")

            logger.info(f"[User {user_id}] Response received: {len(result.text)} chars, cost=${result.cost_usd:.4f}")
            if result.error:
                logger.error(f"[User {user_id}] Error: {result.error}")
            if result.proposal:
                logger.info(f"[User {user_id}] Note proposal: {result.proposal.filename}")

            return result

        except Exception as e:
            logger.exception(f"[User {user_id}] Exception running Claude")
            return ClaudeResponse(
                text="",
                error=f"Failed to run Claude: {str(e)}"
            )

    # Tools to allow for Claude Code sessions
    ALLOWED_TOOLS = [
        'Read', 'Write', 'Edit', 'Glob', 'Grep',
        'WebFetch', 'WebSearch'
    ]

    def _build_command(
        self,
        message: str,
        session_id: Optional[str],
        scope: str,
        user_id: int
    ) -> list[str]:
        """Build the claude CLI command."""
        cmd = [
            'claude',
            '-p', message,  # Print mode (non-interactive)
            '--output-format', 'stream-json',  # Structured output
            '--verbose',  # Required for stream-json with -p
            '--dangerously-skip-permissions',  # Skip permission prompts
        ]

        # Add allowed tools
        cmd.extend(['--allowedTools', ','.join(self.ALLOWED_TOOLS)])

        # Resume existing session if we have one
        if session_id:
            cmd.extend(['--resume', session_id])

        # Add system prompt for context
        scope_display = scope if scope else 'notes (root)'
        all_scopes = self.scope_manager.get_all_folders_flat()
        system_prompt = self._build_system_prompt(scope_display, all_scopes)
        cmd.extend(['--system-prompt', system_prompt])

        return cmd

    def _build_system_prompt(self, scope_display: str, all_scopes: list[str]) -> str:
        """Build the system prompt for the Claude session."""
        # Format scope list
        if all_scopes:
            scopes_list = ", ".join(all_scopes)
        else:
            scopes_list = "(only root)"

        return f"""You are a personal assistant empowering a user to explore their interests and helping them manage a database of corresponding notes via an Obsidian vault. You interact with the user via Telegram.

Current folder: {scope_display}
Available folders: {scopes_list}

You have read access to notes in this folder and subfolders. You can read files freely.

## Default Behaviors

### When receiving a URL:
1. IMMEDIATELY use WebFetch to fetch and read the content
2. Consider how it relates to existing notes in the folder
3. Summarize the key points in light of the folder's context
4. If not already specified in the message, ask the user: "Would you like me to create a note from this, or append to an existing note?"

### When receiving a PDF or document (file path like `attachments/...`):
1. IMMEDIATELY use Read to open and read the file content
2. Extract and summarize the key information - DO NOT quote large sections verbatim
3. For large documents: summarize the structure first, then key points from each section
4. Contextualize it within the current folder (check other notes)
5. If not already specified in the message, ask the user: "Would you like me to create a note from this, append to an existing note, or just keep this summary?"

IMPORTANT: Never dump or quote entire documents. Always summarize and extract insights. If the user needs specific sections, they'll ask.

### When the user sends just a link or file with no instructions:
- Don't ask what to do first - ALWAYS fetch/read it first, then offer options
- Be proactive: the user shared it for a reason

### When just chatting
- Use existing notes to infer implicit context: model the user, what they want or are interested in
- Answer the user in normal text

## Content Routing

When the user shares content (URL, file, or topic) that seems MORE relevant to a DIFFERENT folder than the current one, suggest routing it there using this format:

[SUGGEST_ROUTE: target_folder_name]
Your explanation of why this content fits better in that folder.
[/SUGGEST_ROUTE]

For example, if user shares a philosophy article while in "science" folder:
[SUGGEST_ROUTE: philosophy]
This article on epistemology would fit better in your philosophy notes.
[/SUGGEST_ROUTE]

Only suggest routing when there's a clear mismatch. If content fits the current folder reasonably well, just process it here.

## Note Creation/Editing Protocol

When you want to CREATE or SIGNIFICANTLY EDIT a note, you must PROPOSE it first using this exact format:

[PROPOSE_NOTE: /path/to/filename.md]
---
title: "Note Title"
tags:
  - tag1
created: YYYY-MM-DD
source: https://example.com/article (or attachments/document.pdf)
---

Your note content here...
[/PROPOSE_NOTE]

**Source tracking:** ALWAYS include the `source:` field in frontmatter with the original URL or file path (e.g., `attachments/paper.pdf`). This preserves provenance.

**Appending to existing notes:** When adding content to an existing note, separate the new section with `---` and include a source line:

```
---
*Source: https://example.com — added YYYY-MM-DD*

New content here...
```

The path can include NEW folders that don't exist yet - they will be created automatically on approval.
Examples:
- `note.md` - in current folder
- `/subfolder/note.md` - in subfolder of current folder
- `/new_topic/subtopic/note.md` - creates new_topic/subtopic/ folders

If content doesn't fit the current folder structure, propose a new logical path. The user will see where it will be created and can approve or adjust.

The user will then approve, request edits, or cancel. Only after approval should you actually write the file.

For MINOR edits (fixing typos, small additions), you can proceed directly.

## Guidelines
- Use Obsidian-compatible markdown with YAML frontmatter
- Keep responses concise (Telegram format)
- Make sure you're attuned to the user, know about their goals and interests so you can truly empower them
- Don't hesitate to search for relevant notes and read them so you have the right context
- When reading notes, summarize key points
- Suggest relevant connections between notes
- For new notes, propose descriptive filenames (snake_case.md)
- Be proactive about fetching, reading and contextualizing content the user shares"""

    async def _run_claude(self, cmd: list[str], cwd: str, user_id: int = 0,
                          timeout: int = 120) -> ClaudeResponse:
        """Run claude CLI and parse the response."""
        logger.debug(f"[User {user_id}] Starting Claude subprocess...")
        logger.debug(f"[User {user_id}] Full command: {' '.join(cmd[:8])}...")

        # Run as subprocess
        # IMPORTANT: Set stdin=DEVNULL to prevent hanging when run from IDE
        # (IDE stdin might be unavailable or blocking)
        # Use larger buffer limit (10MB) to handle large PDF content in stream-json output
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,  # Don't inherit stdin
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            limit=10 * 1024 * 1024  # 10MB buffer limit
        )

        logger.debug(f"[User {user_id}] Waiting for Claude response (timeout: {timeout}s)...")

        # Stream stdout in real-time while collecting it
        stdout_lines = []

        try:
            # Read stdout line by line with real-time logging
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"[User {user_id}] Timeout waiting for next line after {timeout}s")
                    process.kill()
                    await process.wait()
                    return ClaudeResponse(
                        text="",
                        error=f"Claude timed out after {timeout} seconds waiting for next line."
                    )
                except asyncio.LimitOverrunError:
                    logger.error(f"[User {user_id}] Response too large - buffer limit exceeded")
                    process.kill()
                    await process.wait()
                    return ClaudeResponse(
                        text="The document is too large for me to process in full. Could you tell me which specific sections or pages you're interested in? Or I can try to give you a high-level summary of just the key points.",
                        error=None  # Not an error, just a graceful message
                    )

                if not line:
                    # EOF reached
                    break

                line_str = line.decode().strip()
                if line_str:
                    stdout_lines.append(line_str)

                    # Log interesting events in real-time
                    try:
                        import json
                        data = json.loads(line_str)
                        msg_type = data.get('type', '')

                        if msg_type == 'assistant':
                            content = data.get('message', {}).get('content', [])
                            for block in content:
                                if block.get('type') == 'tool_use':
                                    tool_name = block.get('name', 'unknown')
                                    logger.info(f"[User {user_id}] Claude using tool: {tool_name}")
                                elif block.get('type') == 'text':
                                    text = block.get('text', '')[:100].split('\n')[0]
                                    if text:
                                        logger.debug(f"[User {user_id}] Claude: {text}...")
                        elif msg_type == 'user' and 'tool_use_result' in data:
                            result = data.get('tool_use_result', {})
                            if isinstance(result, dict):
                                duration = result.get('durationMs', 0)
                                logger.debug(f"[User {user_id}] Tool completed in {duration}ms")
                        elif msg_type == 'result':
                            cost = data.get('total_cost_usd', 0)
                            logger.info(f"[User {user_id}] Request complete, cost: ${cost:.4f}")
                    except json.JSONDecodeError:
                        pass

            # Process has closed stdout, now read stderr and wait for completion
            stderr_data = await process.stderr.read()
            returncode = await process.wait()

        except Exception as e:
            import traceback
            logger.error(f"[User {user_id}] Exception reading Claude output: {e}")
            logger.error(f"[User {user_id}] Traceback: {traceback.format_exc()}")
            try:
                process.kill()
                await process.wait()
            except:
                pass
            return ClaudeResponse(
                text="",
                error=f"Failed to read Claude output: {str(e)}"
            )

        logger.debug(f"[User {user_id}] Claude subprocess completed with code {returncode}")

        if stderr_data:
            stderr_text = stderr_data.decode()
            if stderr_text.strip():
                logger.warning(f"[User {user_id}] Claude stderr: {stderr_text[:500]}")

        if returncode != 0:
            error_msg = stderr_data.decode() if stderr_data else f"Exit code {returncode}"
            logger.error(f"[User {user_id}] Claude failed: {error_msg}")
            return ClaudeResponse(text="", error=error_msg)

        stdout_text = '\n'.join(stdout_lines)
        logger.debug(f"[User {user_id}] Raw output length: {len(stdout_text)} chars")

        # Parse the stream-json output
        return self._parse_stream_json(stdout_text, user_id)

    def _parse_stream_json(self, output: str, user_id: int = 0) -> ClaudeResponse:
        """
        Parse stream-json output from Claude CLI.

        Each line is a JSON object. We collect text from 'assistant' messages
        and extract metadata like session_id.
        """
        text_parts = []
        session_id = None
        cost_usd = 0.0
        tool_uses = []

        for line in output.strip().split('\n'):
            if not line.strip():
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # Might be plain text output
                text_parts.append(line)
                continue

            msg_type = data.get('type', '')

            # Extract session ID from init or result message
            if msg_type == 'system' and 'session_id' in data:
                session_id = data['session_id']

            # Handle different message types
            if msg_type == 'assistant':
                # Assistant message with content
                content = data.get('message', {}).get('content', [])
                for block in content:
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        tool_name = block.get('name', 'unknown')
                        tool_uses.append(tool_name)
                        logger.debug(f"[User {user_id}] Tool use: {tool_name}")

            elif msg_type == 'result':
                # Final result with metadata
                session_id = data.get('session_id', session_id)
                cost_usd = data.get('total_cost_usd', 0.0)
                # Note: 'result' field duplicates assistant content, so we don't append it

        if tool_uses:
            logger.info(f"[User {user_id}] Tools used: {', '.join(tool_uses)}")

        full_text = '\n'.join(text_parts).strip()

        # Check for note proposal
        proposal = self._extract_proposal(full_text)

        # Check for route proposal
        route_proposal = self._extract_route_proposal(full_text)

        # Clean the text - remove proposal blocks from displayed text
        display_text = full_text

        if proposal:
            display_text = re.sub(
                r'\[PROPOSE_NOTE:.*?\].*?\[/PROPOSE_NOTE\]',
                '',
                display_text,
                flags=re.DOTALL
            ).strip()
            if display_text:
                display_text += "\n\n_[Proposed note below for your approval]_"
            else:
                display_text = "_I've prepared a note for your approval._"

        if route_proposal:
            display_text = re.sub(
                r'\[SUGGEST_ROUTE:.*?\].*?\[/SUGGEST_ROUTE\]',
                '',
                display_text,
                flags=re.DOTALL
            ).strip()
            # The route reason will be shown separately with buttons

        return ClaudeResponse(
            text=display_text,
            session_id=session_id,
            cost_usd=cost_usd,
            proposal=proposal,
            route_proposal=route_proposal
        )

    def _extract_proposal(self, text: str) -> Optional[NoteProposal]:
        """Extract a note proposal from Claude's response if present."""
        # Pattern: [PROPOSE_NOTE: filename.md]...content...[/PROPOSE_NOTE]
        pattern = r'\[PROPOSE_NOTE:\s*([^\]]+)\](.*?)\[/PROPOSE_NOTE\]'
        match = re.search(pattern, text, re.DOTALL)

        if not match:
            return None

        filename = match.group(1).strip()
        content = match.group(2).strip()

        # Determine if this is an edit (filename contains path separator or exists check would go here)
        # For simplicity, assume new unless explicitly stated
        is_edit = 'edit' in text.lower()[:100] or 'update' in text.lower()[:100]

        return NoteProposal(
            filename=filename,
            content=content,
            is_edit=is_edit
        )

    def _extract_route_proposal(self, text: str) -> Optional[RouteProposal]:
        """Extract a route proposal from Claude's response if present."""
        # Pattern: [SUGGEST_ROUTE: scope_name]...reason...[/SUGGEST_ROUTE]
        pattern = r'\[SUGGEST_ROUTE:\s*([^\]]+)\](.*?)\[/SUGGEST_ROUTE\]'
        match = re.search(pattern, text, re.DOTALL)

        if not match:
            return None

        target_scope = match.group(1).strip()
        reason = match.group(2).strip()

        return RouteProposal(
            target_scope=target_scope,
            reason=reason
        )

    def get_session_info(self, user_id: int, scope: str) -> dict:
        """Get info about a session."""
        session_id = self.scope_manager.get_session_id(user_id, scope)
        return {
            'scope': scope,
            'session_id': session_id,
            'has_session': session_id is not None,
            'path': self.scope_manager.get_absolute_path(scope)
        }


class ClaudeSessionPool:
    """
    Manages multiple Claude sessions across users and scopes.

    Provides high-level interface for the bot to interact with Claude.
    """

    def __init__(self, scope_manager: ScopeManager):
        self.scope_manager = scope_manager
        self.session_manager = ClaudeSessionManager(scope_manager)

        # Track active requests to prevent concurrent calls for same user
        self._active_requests: set[int] = set()

    async def chat(self, user_id: int, message: str) -> ClaudeResponse:
        """
        Send a chat message from a user.

        Uses their active scope to determine which session to use.
        """
        # Get user's active scope
        scope = self.scope_manager.get_active_scope(user_id)

        # Prevent concurrent requests for same user
        if user_id in self._active_requests:
            return ClaudeResponse(
                text="Please wait, still processing your previous message...",
                error="concurrent_request"
            )

        self._active_requests.add(user_id)

        try:
            response = await self.session_manager.send_message(
                user_id=user_id,
                message=message,
                scope=scope
            )
            return response
        finally:
            self._active_requests.discard(user_id)

    def get_user_sessions(self, user_id: int) -> list[dict]:
        """Get all sessions for a user."""
        state = self.scope_manager.load_user_state(user_id)
        sessions = state.get('sessions', {})

        return [
            {
                'scope': scope,
                'session_id': session_id,
                'is_active': scope == state.get('active_scope')
            }
            for scope, session_id in sessions.items()
        ]