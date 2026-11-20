# Telegram Bot with python-telegram-bot v21+

A production-ready Telegram bot template featuring:

- **python-telegram-bot v21+** with async/await
- **SQLAlchemy 2.0** + SQLite (easily swappable to PostgreSQL)
- **APScheduler** + PTB JobQueue for scheduled tasks
- **Inline keyboards** with callback data handling
- **External API client** with retries (tenacity)
- **Structured logging** with structlog (JSON/console)
- **Webhook & Polling** modes
- **Docker** support

## Quick Start

### 1. Create a Bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Run `/newbot` and follow instructions
3. Copy the **Bot Token**

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your token and settings
```

Required variables:
```env
BOT_TOKEN=your_bot_token_here
BOT_USERNAME=your_bot_username
```

### 3. Run Locally
```bash
# Install dependencies
pip install -e .

# Run in polling mode (development)
python -m bot.main
```

### 4. Run with Docker
```bash
# Build and run
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Project Structure

```
├── bot/
│   ├── __init__.py
│   ├── config.py          # Pydantic settings
│   ├── database.py        # SQLAlchemy models & repositories
│   ├── external_api.py    # HTTP client with retries
│   ├── handlers.py        # Command, message, callback handlers
│   ├── jobs.py            # Scheduled jobs (APScheduler + JobQueue)
│   ├── keyboards.py       # Inline keyboard builders
│   ├── logging_config.py  # Structlog setup
│   └── main.py            # Entry point
├── data/                  # SQLite database (created at runtime)
├── .env.example           # Environment template
├── pyproject.toml         # Dependencies & tool config
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Features Included

### Commands
| Command | Description |
|---------|-------------|
| `/start` | Show main menu with inline keyboard |
| `/help` | Show help message |
| `/ping` | Measure bot latency |
| `/settings` | Toggle notifications |
| `/stats` | Show your message statistics |

### Inline Keyboards
- Main menu with feature buttons
- Settings toggle
- Help screen
- Admin panel (restricted)
- Confirmation dialogs
- Pagination example

### Database Models
- **User** - Telegram user info
- **Chat** - Private/group/channel chats
- **MessageLog** - All messages for analytics
- **BotState** - Key-value persistence

### Scheduled Jobs
| Job | Schedule | Description |
|-----|----------|-------------|
| Daily Cleanup | 03:00 UTC | Remove logs > 30 days |
| Hourly Stats | Every hour | Log user/chat/message counts |
| API Health Check | Every 5 min | Monitor external API |
| Daily Engagement | 09:00 UTC | Active users, new users, messages |
| Weekly DB Maintenance | Sun 04:00 UTC | SQLite VACUUM |

### External API Client
- Async HTTP with aiohttp
- Automatic retries with exponential backoff
- Configurable timeout
- Bearer token auth
- Health check endpoint

## Customization

### Add New Commands
1. Create handler in `bot/handlers.py`
2. Register in `register_handlers()`

### Add New Callback Actions
1. Add to `CallbackAction` enum in `bot/keyboards.py`
2. Handle in `handle_callback_query()`

### Add Database Models
1. Define in `bot/database.py` inheriting from `Base`
2. Run migrations (or auto-create on startup)

### Change Database to PostgreSQL
Update `.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

### Add Webhook (Production)
```env
WEBHOOK_URL=https://your-domain.com/webhook
WEBHOOK_SECRET=your_secret_token
WEBHOOK_PORT=8080
```

Then deploy with a reverse proxy (nginx, Caddy) handling SSL.

## Development

### Code Quality
```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy bot/

# Tests
pytest
```

### Database Migrations (Alembic)
```bash
# Initialize (first time)
alembic init migrations

# Create migration
alembic revision --autogenerate -m "description"

# Apply
alembic upgrade head
```

## Deployment Options

### Docker Compose (Recommended)
```bash
docker-compose up -d
```

### Systemd Service
Create `/etc/systemd/system/telegram-bot.service`:
```ini
[Unit]
Description=Telegram Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/telegram-bot
EnvironmentFile=/opt/telegram-bot/.env
ExecStart=/opt/telegram-bot/.venv/bin/python -m bot.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Kubernetes
Use the Docker image with a Deployment + ConfigMap/Secret for env vars.

## License
MIT