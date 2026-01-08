# Loam

Loam is a cultivated space for links, notes, and thoughts to grow over time.

You can send Loam fragments of thought — messages, discussions, web pages, PDFs — and it stores them in a way that preserves context and relationships. Rather than treating notes as isolated entries, Loam helps connections emerge gradually as your interests evolve.

Loam is designed for slow thinking. You can jot things in quickly, then return later to reflect, explore themes, and surface structure across what you've collected. Over time, the accumulation itself becomes meaningful.

Loam does not try to optimize or summarize everything immediately. It favors patience, continuity, and reuse. The goal is not to replace your thinking, but to support it by keeping a fertile ground where ideas can settle and recombine.

Loam works alongside Obsidian, but remains lightweight and conversational at the point of capture.

## How it works

- **Folders** organize your notes by topic (e.g., `philosophy`, `art/color_spaces`)
- **Sessions** are conversations within a folder — each session remembers context
- **Notes** are Obsidian-compatible markdown files

## Requirements

- A [Claude subscription](https://claude.ai) (Pro, Team, or Enterprise)
- [Obsidian](https://obsidian.md) (free)
- Telegram account
- Python 3.10+

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Claude Code CLI

Loam uses the Claude Code CLI to interact with Claude. Install it by following [these steps](https://docs.anthropic.com/en/docs/claude-code).

Then authenticate:

```bash
claude login
```

### 3. Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "Loam")
4. Choose a username (must end in `bot`, e.g., `my_loam_bot`)
5. BotFather will give you an API token

### 4. Find your Telegram user ID

You need your numeric user ID (not username). To find it:

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. It will reply with your user ID (a number like `123456789`)

### 5. Create config files

In the project root, create these files:

**`.api_telegram_bot`** — Your bot token from BotFather:
```
123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

**`.telegram_valid_user_ids`** — Users allowed to use the bot (one ID per line):
```
123456789
```

### 6. Set up Obsidian

Loam stores notes as plain markdown files. You can edit them directly in Obsidian alongside Loam.

**Option A: Use the built-in notes folder**

1. Open Obsidian
2. Click "Open folder as vault"
3. Select the `notes/` folder inside this project

**Option B: Use an existing vault**

Point Loam to your existing Obsidian vault:

```bash
export LOAM_VAULT_PATH=/path/to/your/obsidian/vault
```

Either way, you'll see the same files in both Telegram (via Loam) and Obsidian. Create folders in Obsidian and they appear in Loam's `/new` menu. Edit notes in Obsidian and Loam sees the changes.

### 7. Run

```bash
python -m src.start
```

## Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new session in a folder |
| `/switch` | Switch to another session |
| `/session` | Show current folder and session |
| `/rename` | Name the current session |
| `/star` | Star a session to keep it |
| `/unstar` | Remove star |
| `/create` | Create a new folder |
| `/list` | List notes in current folder |

## Keeping Loam running and Syncing notes across devices

Loam needs to run continuously to respond to Telegram messages: use a server (at home or online).

Your notes are plain markdown files. Sync them however you like: iCloud, Dropbox, Google Drive, Github, Obsidian Sync. 

## License

MIT
