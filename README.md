# Random WhatsApp Redirect Bot

## Render Environment Variables

Required:
- BOT_TOKEN = BotFather token
- ADMIN_ID = numeric Telegram user ID
- PUBLIC_URL = your Render service URL, e.g. https://your-service.onrender.com

Optional:
- DB_PATH = ./data/bot.db
  - For a Render Persistent Disk mounted at `/var/data`, use `/var/data/bot.db`.

## Commands

/start - admin panel
/add - bulk add numbers
/numbers - count/list saved numbers
/clear - clear numbers
/setlink - change simple redirect link
/random - get public random WhatsApp page
/simple - get public simple redirect page

The random page chooses a saved number randomly in the visitor's browser on each visit.
