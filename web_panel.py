import os
import secrets
import sqlite3

from flask import Flask, redirect, render_template_string, request, session, url_for

# Путь к базе — рядом с этим файлом (та же база, что у бота)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

ORE_NAMES = {
    "stone": "Камень",
    "iron": "Железная руда",
    "copper": "Медная руда",
    "gold": "Золотая руда",
}
PICK_NAMES = {
    "wood": "Деревянная", "stone": "Каменная", "iron": "Железная",
    "gold": "Золотая", "diamond": "Алмазная",
}
DEFAULT_SETTINGS = {
    "mine_cooldown": "60",
    "bonus_amount": "5000",
    "bonus_hours": "12",
    "roulette_min_level": "20",
    "roulette_cooldown": "30",
    "roulette_min_bet": "10",
    "roulette_max_bet": "100000",
}
DEFAULT_PRICES = {"stone": 2, "iron": 8, "copper": 20, "gold": 60}

def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def ensure_tables():
    """Создаёт таблицы настроек, если бот ещё не создал их сам."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (ore_key TEXT PRIMARY KEY, price INTEGER)")
    for k, v in DEFAULT_SETTINGS.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    for k, v in DEFAULT_PRICES.items():
        cur.execute("INSERT OR IGNORE INTO prices (ore_key, price) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def load_all():
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    settings = dict(cur.fetchall())
    cur.execute("SELECT ore_key, price FROM prices")
    prices = dict(cur.fetchall())
    cur.execute("""SELECT user_id, username, balance, level, pickaxe_key,
                          ore_stone, ore_iron, ore_copper, ore_gold
                   FROM users ORDER BY balance DESC""")
    players = cur.fetchall()
    conn.close()
    return settings, prices, players

def do_give(user_id, resource, amount):
    """Возвращает (успех, сообщение)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        return False, f"Игрок {user_id} не найден."
    if resource == "coins":
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    else:
        col = f"ore_{resource}"
        cur.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True, f"Выдано {amount} игроку {user_id}."

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Вход</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;display:flex;justify-content:center;padding-top:80px}
form{background:#2b2b3d;padding:30px;border-radius:12px}
input{padding:8px;width:200px}button{padding:8px 20px;margin-top:10px}</style></head>
<body><form method="post">
<h2>🔑 Вход в панель</h2>
<p style="color:#f66">{{ error }}</p>
<input type="password" name="password" placeholder="Пароль" autofocus><br>
<button>Войти</button>
</form></body></html>"""

PANEL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Панель шахты</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:820px;margin:30px auto;padding:0 15px}
input{padding:6px;width:110px}button{padding:8px 20px;margin-top:12px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h3{margin-top:25px}
.box{background:#2b2b3d;padding:15px 20px;border-radius:10px;margin-top:15px}
.msg{color:#7fd57f;margin-top:10px}
.msg-err{color:#f66;margin-top:10px}
select{padding:6px;background:#3a3a4d;color:#eee;border:1px solid #555}
code{color:#8ab}
</style></head><body>
<h2>⚙️ Панель шахты</h2>

<div class="box">
<h3 style="margin-top:0">🎁 Выдать игроку</h3>
<form method="post" action="/give">
ID игрока: <input name="user_id" placeholder="например 5636309834"><br>
Что выдать: <select name="resource">
<option value="coins">Монеты</option>
<option value="stone">Камень</option>
<option value="iron">Железная руда</option>
<option value="copper">Медная руда</option>
<option value="gold">Золотая руда</option>
</select><br>
Количество: <input name="amount" placeholder="например 100"><br>
<button>Выдать</button>
</form>
{% if give_msg %}<p class="msg">{{ give_msg }}</p>{% endif %}
{% if give_err %}<p class="msg-err">{{ give_err }}</p>{% endif %}
</div>

<div class="box">
<h3 style="margin-top:0">🔄 Сбросить баланс игроку</h3>
<form method="post" action="/reset" onsubmit="return confirm('Точно сбросить баланс?')">
ID игрока: <input name="user_id" placeholder="ID игрока"><br>
<button>Сбросить баланс</button>
</form>
{% if reset_msg %}<p class="msg">{{ reset_msg }}</p>{% endif %}
{% if reset_err %}<p class="msg-err">{{ reset_err }}</p>{% endif %}
</div>

<form method="post" action="/save">
<h3>Настройки шахты</h3>
Кулдаун накопания (сек): <input name="mine_cooldown" value="{{ settings.mine_cooldown }}"><br>
Бонус (монет): <input name="bonus_amount" value="{{ settings.bonus_amount }}"><br>
Бонус раз в (часов): <input name="bonus_hours" value="{{ settings.bonus_hours }}"><br>
<h3>Цены руды</h3>
{% for key, price in prices.items() %}{{ names[key] }}: <input name="price_{{ key }}" value="{{ price }}"><br>{% endfor %}
<h3>Настройки рулетки</h3>
Мин. уровень для рулетки: <input name="roulette_min_level" value="{{ settings.roulette_min_level }}"><br>
Кулдаун рулетки (сек): <input name="roulette_cooldown" value="{{ settings.roulette_cooldown }}"><br>
Мин. ставка: <input name="roulette_min_bet" value="{{ settings.roulette_min_bet }}"><br>
Макс. ставка: <input name="roulette_max_bet" value="{{ settings.roulette_max_bet }}"><br>
<button>💾 Сохранить настройки</button>
</form>

<h3>Игроки</h3>
<table><tr><th>ID</th><th>Игрок</th><th>Монеты</th><th>Уровень</th><th>Кирка</th><th>Рюкзак</th></tr>
{% for p in players %}<tr>
<td><code>{{ p[0] }}</code></td><td>{{ p[1] }}</td><td>{{ p[2] }}</td><td>{{ p[3] }}</td><td>{{ picks[p[4]] }}</td>
<td>🪨{{ p[5] }} ⚙️{{ p[6] }} 🥉{{ p[7] }} 💎{{ p[8] }}</td>
</tr>{% endfor %}</table>
<p><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""

def render_panel(settings, prices, players, give_msg, give_err, reset_msg, reset_err):
    return render_template_string(
        PANEL_PAGE, settings=settings, prices=prices, players=players,
        names=ORE_NAMES, picks=PICK_NAMES,
        give_msg=give_msg, give_err=give_err,
        reset_msg=reset_msg, reset_err=reset_err,
    )

@app.route("/healthz")
def healthz():
    return "ok"

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if not PANEL_PASSWORD:
        return "Панель не настроена: задай переменную PANEL_PASSWORD перед запуском", 500
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_PAGE, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, "", "", "", "")

@app.route("/give", methods=["POST"])
def give():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        user_id = int(request.form.get("user_id", ""))
        amount = int(request.form.get("amount", ""))
    except ValueError:
        settings, prices, players = load_all()
        return render_panel(settings, prices, players, "", "ID и количество должны быть числами.", "", "")

    resource = request.form.get("resource", "coins")
    if resource not in ["coins", "stone", "iron", "copper", "gold"]:
        settings, prices, players = load_all()
        return render_panel(settings, prices, players, "", "Неизвестный ресурс.", "", "")

    if amount <= 0:
        settings, prices, players = load_all()
        return render_panel(settings, prices, players, "", "Количество должно быть больше 0.", "", "")

    ok, msg = do_give(user_id, resource, amount)
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, msg if ok else "", "" if ok else msg, "", "")

@app.route("/reset", methods=["POST"])
def reset():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        user_id = int(request.form.get("user_id", ""))
    except ValueError:
        settings, prices, players = load_all()
        return render_panel(settings, prices, players, "", "", "", "ID должен быть числом.")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    found = cur.fetchone()
    if found:
        cur.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        msg, err = f"Баланс игрока {user_id} сброшен до 0.", ""
    else:
        msg, err = "", f"Игрок {user_id} не найден."
    conn.close()
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, "", "", msg, err)

@app.route("/save", methods=["POST"])
def save():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    conn = get_conn()
    cur = conn.cursor()
    for key in DEFAULT_SETTINGS:
        val = request.form.get(key)
        if val is not None and val.isdigit():
            cur.execute("UPDATE settings SET value = ? WHERE key = ?", (val, key))
    for key in DEFAULT_PRICES:
        val = request.form.get(f"price_{key}")
        if val is not None and val.isdigit():
            cur.execute("UPDATE prices SET price = ? WHERE ore_key = ?", (int(val), key))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
