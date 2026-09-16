"""
Inventario QR — Silicom
Flask + SQLite (local/.exe) | PostgreSQL (Vercel + Supabase)
Todos los endpoints POST retornan {"success": true} con HTTP 200.
Todos los errores (incluso inesperados) retornan JSON, nunca HTML.
"""
import os, sys, json, socket, decimal, datetime
from datetime import timedelta
from flask import Flask, jsonify, request, g, render_template

# ── Paths ─────────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    BASE_DIR   = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR   = BUNDLE_DIR

TEMPLATE_DIR = os.path.join(BUNDLE_DIR, "templates")
STATIC_DIR   = os.path.join(BUNDLE_DIR, "static")
SEED_PATH    = os.path.join(BUNDLE_DIR, "seed.json")
DB_PATH      = os.path.join(BASE_DIR,   "inventario.db")

# ── Database mode ─────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL)

app = Flask(__name__,
            template_folder=TEMPLATE_DIR,
            static_folder=STATIC_DIR,
            static_url_path="/static")


# ── JSON safety: nunca dejar pasar un error como HTML ─────────────────────────
class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status

@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({"success": False, "error": e.message}), e.status

@app.errorhandler(Exception)
def handle_any_error(e):
    """Red de seguridad: cualquier excepción no controlada se devuelve como
    JSON (nunca como página HTML de error), para que el frontend siempre
    pueda leer la respuesta y mostrar el mensaje real en vez de fallar en
    silencio."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"success": False, "error": e.description}), e.code
    app.logger.exception("Error no controlado")
    return jsonify({"success": False, "error": f"Error del servidor: {e}"}), 500


def _json_safe(value):
    """Convierte tipos que psycopg2 puede devolver (datetime, date, Decimal)
    a algo serializable en JSON, sin depender del comportamiento por
    defecto de Flask."""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value

def _row_safe(d):
    return {k: _json_safe(v) for k, v in d.items()}


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        if USE_PG:
            import psycopg2
            g.db = psycopg2.connect(DATABASE_URL)
        else:
            import sqlite3
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def _exec(sql, params=()):
    db = get_db()
    try:
        if USE_PG:
            import psycopg2.extras
            cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), params)
            db.commit()
            return cur
        cur = db.execute(sql, params)
        db.commit()
        return cur
    except Exception:
        db.rollback()
        raise

def db_all(sql, params=()):
    cur = _exec(sql, params)
    return [_row_safe(dict(r)) for r in cur.fetchall()]

def db_one(sql, params=()):
    cur = _exec(sql, params)
    r = cur.fetchone()
    return _row_safe(dict(r)) if r else None

def db_run(sql, params=()):
    _exec(sql, params)

def _first_value(row):
    """Devuelve el primer valor de una fila. Tanto sqlite3.Row como
    RealDictRow (psycopg2) soportan .keys() y acceso por nombre de
    columna, así que usamos ese camino para los dos por igual."""
    first_key = list(row.keys())[0]
    return row[first_key]

def db_scalar(sql, params=()):
    cur = _exec(sql, params)
    r = cur.fetchone()
    if not r:
        return None
    return _json_safe(_first_value(r))

def db_insert(sql, params=()):
    db = get_db()
    try:
        if USE_PG:
            cur = db.cursor()
            cur.execute((sql + " RETURNING id").replace("?", "%s"), params)
            db.commit()
            r = cur.fetchone()
            return r[0] if r else None
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid
    except Exception:
        db.rollback()
        raise

def ok(**kwargs):
    return jsonify({"success": True, **kwargs}), 200

def err(msg, status=400):
    return jsonify({"success": False, "error": msg}), status


# ── Reconciliación automática de esquema ──────────────────────────────────────
# En vez de agregar columnas puntuales cada vez que aparece una sorpresa,
# esto compara —en cada arranque— las columnas que el código realmente
# necesita contra las que existen de verdad en la base, y agrega solo las
# que faltan. Si en el futuro se agrega un campo nuevo a alguna función,
# se autocorrige solo en el próximo despliegue, sin intervención manual.
_MIGRATION_LOG = []

REQUIRED_COLUMNS = {
    "products": {
        "code":       "TEXT",
        "name":       "TEXT DEFAULT ''",
        "brand":      "TEXT DEFAULT ''",
        "stock":      "INTEGER DEFAULT 0",
        "location":   "TEXT DEFAULT ''",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "movements": {
        "product_code": "TEXT DEFAULT ''",
        "product_name": "TEXT DEFAULT ''",
        "type":         "TEXT DEFAULT 'entrada'",
        "qty":          "INTEGER DEFAULT 0",
        "stock_before": "INTEGER",
        "stock_after":  "INTEGER",
        "project_id":   "INTEGER",
        "location":     "TEXT DEFAULT ''",
        "notes":        "TEXT DEFAULT ''",
        "created_at":   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "projects": {
        "name":        "TEXT DEFAULT ''",
        "description": "TEXT DEFAULT ''",
        "status":      "TEXT DEFAULT 'activo'",
        "created_at":  "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "purchases": {
        "product_code":  "TEXT DEFAULT ''",
        "product_name":  "TEXT DEFAULT ''",
        "supplier":      "TEXT DEFAULT ''",
        "qty":           "INTEGER DEFAULT 1",
        "unit_price":    "REAL DEFAULT 0",
        "currency":      "TEXT DEFAULT 'USD'",
        "status":        "TEXT DEFAULT 'pendiente'",
        "project_id":    "INTEGER",
        "order_date":    "DATE",
        "expected_date": "DATE",
        "received_date": "DATE",
        "notes":         "TEXT DEFAULT ''",
        "created_at":    "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
}

# Columnas heredadas de esquemas anteriores que pueden traer una restricción
# NOT NULL sin default y romper los INSERT actuales (que no las completan).
# Si existen, se les quita esa restricción; si no existen, no pasa nada.
LEGACY_NULLABLE_FIXES = {
    "movements": ["product_id"],
    "purchases": ["product_id"],
}

def _ensure_columns_pg(cur, table, columns):
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,)
    )
    existing = {r[0] for r in cur.fetchall()}
    for col, coltype in columns.items():
        if col in existing or col == "code":  # 'code' es PK, no se toca por ALTER
            continue
        try:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {coltype}')
            _MIGRATION_LOG.append(f"{table}.{col} agregada")
        except Exception as e:
            _MIGRATION_LOG.append(f"{table}.{col} FALLÓ: {e}")

def _fix_legacy_not_null_pg(cur, table, cols):
    for col in cols:
        try:
            cur.execute(f'ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL')
            _MIGRATION_LOG.append(f"{table}.{col}: restricción NOT NULL heredada removida")
        except Exception:
            pass  # la columna no existe o ya era nullable — no hay nada que hacer

def _ensure_columns_sqlite(conn, table, columns):
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, coltype in columns.items():
        if col in existing or col == "code":
            continue
        try:
            simple_type = coltype.split(" DEFAULT")[0].split(" ")[0]
            # SQLite no permite ALTER TABLE ... ADD COLUMN con un default
            # no-constante como CURRENT_TIMESTAMP; en ese caso se agrega
            # sin default (las filas existentes quedan con NULL ahí, que
            # es aceptable para una columna de auditoría).
            default = ""
            if "DEFAULT" in coltype and "CURRENT_TIMESTAMP" not in coltype:
                default = " DEFAULT" + coltype.split("DEFAULT")[1]
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {simple_type}{default}')
            _MIGRATION_LOG.append(f"{table}.{col} agregada (sqlite)")
        except Exception as e:
            _MIGRATION_LOG.append(f"{table}.{col} FALLÓ (sqlite): {e}")


# ── Init DB (idempotente — se puede llamar en cada arranque sin romper nada) ──
def init_db():
    if USE_PG:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY, name TEXT NOT NULL,
                brand TEXT DEFAULT '', stock INTEGER NOT NULL DEFAULT 0,
                location TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                description TEXT DEFAULT '', status TEXT DEFAULT 'activo',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movements (
                id SERIAL PRIMARY KEY, product_code TEXT NOT NULL,
                product_name TEXT NOT NULL, type TEXT NOT NULL,
                qty INTEGER NOT NULL, stock_before INTEGER, stock_after INTEGER,
                project_id INTEGER, location TEXT DEFAULT '', notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY, product_code TEXT DEFAULT '',
                product_name TEXT NOT NULL, supplier TEXT DEFAULT '',
                qty INTEGER DEFAULT 1, unit_price REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'pendiente',
                project_id INTEGER, order_date DATE, expected_date DATE,
                received_date DATE, notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

        # Reconciliar esquema real contra lo que el código necesita —
        # esto es lo que resuelve tablas heredadas con columnas distintas
        # (como movements.product_id en vez de movements.product_code).
        for table, cols in REQUIRED_COLUMNS.items():
            _ensure_columns_pg(cur, table, cols)
        for table, cols in LEGACY_NULLABLE_FIXES.items():
            _fix_legacy_not_null_pg(cur, table, cols)
        conn.commit()
        if _MIGRATION_LOG:
            print("[DB] Migraciones aplicadas:")
            for line in _MIGRATION_LOG:
                print(f"     - {line}")

        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding="utf-8") as f:
                seed = json.load(f)
            for s in seed:
                cur.execute(
                    "INSERT INTO products (code,name,brand,stock) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s["code"], s["name"], s.get("brand",""), s.get("stock",0)))
            conn.commit()
            print(f"[DB] {len(seed)} productos cargados (PostgreSQL)")
        conn.close()
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY, name TEXT NOT NULL,
                brand TEXT DEFAULT '', stock INTEGER NOT NULL DEFAULT 0,
                location TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                description TEXT DEFAULT '', status TEXT DEFAULT 'activo',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT NOT NULL,
                product_name TEXT NOT NULL, type TEXT NOT NULL,
                qty INTEGER NOT NULL, stock_before INTEGER, stock_after INTEGER,
                project_id INTEGER, location TEXT DEFAULT '', notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT DEFAULT '',
                product_name TEXT NOT NULL, supplier TEXT DEFAULT '',
                qty INTEGER DEFAULT 1, unit_price REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'pendiente',
                project_id INTEGER, order_date DATE, expected_date DATE,
                received_date DATE, notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.commit()
        for table, cols in REQUIRED_COLUMNS.items():
            _ensure_columns_sqlite(conn, table, cols)
        conn.commit()
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding="utf-8") as f:
                seed = json.load(f)
            conn.executemany(
                "INSERT OR IGNORE INTO products (code,name,brand,stock) VALUES (?,?,?,?)",
                [(s["code"],s["name"],s.get("brand",""),s.get("stock",0)) for s in seed])
            conn.commit()
            print(f"[DB] {len(seed)} productos cargados (SQLite)")
        conn.close()


# En Vercel el bloque `if __name__ == "__main__"` nunca se ejecuta, porque
# el runtime importa `app` directamente. Por eso init_db() se llama acá,
# a nivel de módulo, envuelto en try/except para no tumbar el arranque
# si la base de datos está temporalmente inaccesible.
try:
    init_db()
except Exception as _init_err:
    print(f"[DB] init_db() falló al importar: {_init_err}")


# ── Rutas estáticas ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/health", methods=["GET"])
def health():
    """Diagnóstico rápido: entrar a /api/health desde el navegador para ver
    si la base de datos está conectada, qué modo está usando, y qué
    columnas se agregaron automáticamente en el último arranque."""
    info = {"db_mode": "postgres" if USE_PG else "sqlite", "migrations_last_startup": _MIGRATION_LOG}
    try:
        info["products_count"]  = db_scalar("SELECT COUNT(*) FROM products")
        info["projects_count"]  = db_scalar("SELECT COUNT(*) FROM projects")
        info["movements_count"] = db_scalar("SELECT COUNT(*) FROM movements")
        info["purchases_count"] = db_scalar("SELECT COUNT(*) FROM purchases")
        info["connected"] = True
    except Exception as e:
        info["connected"] = False
        info["error"] = str(e)
    return jsonify(info)


# ── Products ──────────────────────────────────────────────────────────────────
@app.route("/api/products", methods=["GET"])
def list_products():
    return jsonify(db_all("SELECT * FROM products ORDER BY name"))

@app.route("/api/products", methods=["POST"])
def create_product():
    d     = request.get_json(force=True)
    code  = (d.get("code") or "").strip()
    name  = (d.get("name") or "").strip()
    brand = (d.get("brand") or "").strip()
    stock = int(d.get("stock") or 0)
    loc   = (d.get("location") or "").strip()
    if not name: return err("Falta el nombre")
    if not code: return err("Falta el código")
    if db_one("SELECT code FROM products WHERE code=?", (code,)):
        return err("Ese código ya existe", 409)
    db_run("INSERT INTO products (code,name,brand,stock,location) VALUES (?,?,?,?,?)",
           (code, name, brand, stock, loc))
    return ok(product={"code":code,"name":name,"brand":brand,"stock":stock,"location":loc})

@app.route("/api/products/<code>", methods=["PUT"])
def update_product(code):
    d = request.get_json(force=True)
    db_run("UPDATE products SET name=?,brand=?,location=? WHERE code=?",
           (d.get("name",""), d.get("brand",""), d.get("location",""), code))
    return ok()

@app.route("/api/products/<code>", methods=["DELETE"])
def delete_product(code):
    db_run("DELETE FROM products WHERE code=?", (code,))
    return ok()


# ── Movements ─────────────────────────────────────────────────────────────────
@app.route("/api/movements", methods=["GET"])
def list_movements():
    filt    = request.args.get("filter", "all")
    mtype   = request.args.get("type", "")
    proj_id = request.args.get("project_id", "")
    where, params = [], []

    if filt == "week":
        where.append("m.created_at >= ?")
        params.append((datetime.datetime.now() - timedelta(days=7)).isoformat())
    elif filt == "2weeks":
        where.append("m.created_at >= ?")
        params.append((datetime.datetime.now() - timedelta(days=14)).isoformat())
    elif filt == "month":
        where.append("m.created_at >= ?")
        params.append((datetime.datetime.now() - timedelta(days=30)).isoformat())

    if mtype:   where.append("m.type = ?");        params.append(mtype)
    if proj_id: where.append("m.project_id = ?");  params.append(proj_id)

    sql = """
        SELECT m.*, p.brand, pr.name AS project_name
        FROM movements m
        LEFT JOIN products  p  ON m.product_code = p.code
        LEFT JOIN projects  pr ON m.project_id   = pr.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.created_at DESC LIMIT 500"
    return jsonify(db_all(sql, params))

@app.route("/api/movements", methods=["POST"])
def create_movement():
    d          = request.get_json(force=True)
    code       = (d.get("product_code") or "").strip()
    mtype      = d.get("type", "entrada")
    qty        = int(d.get("qty") or 1)
    raw_proj   = d.get("project_id")
    project_id = int(raw_proj) if raw_proj not in (None, "", "null") else None
    location   = (d.get("location") or "").strip()
    notes      = (d.get("notes") or "").strip()

    row = db_one("SELECT * FROM products WHERE code=?", (code,))
    if not row: return err("Producto no encontrado", 404)

    before = row["stock"]
    if   mtype == "entrada": after = before + qty
    elif mtype == "salida":  after = max(0, before - qty)
    elif mtype == "ajuste":  after = max(0, qty)
    else: return err("Tipo inválido")

    if location:
        db_run("UPDATE products SET stock=?, location=? WHERE code=?", (after, location, code))
    else:
        db_run("UPDATE products SET stock=? WHERE code=?", (after, code))

    db_run("""INSERT INTO movements
        (product_code,product_name,type,qty,stock_before,stock_after,project_id,location,notes)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (code, row["name"], mtype, qty, before, after, project_id, location, notes))

    return ok(stock_before=before, stock_after=after, product_code=code, product_name=row["name"])


# ── Projects ──────────────────────────────────────────────────────────────────
@app.route("/api/projects", methods=["GET"])
def list_projects():
    projects = db_all("SELECT * FROM projects ORDER BY created_at DESC")
    for p in projects:
        p["items"] = db_all("""
            SELECT m.product_code AS code, m.product_name AS name,
                   COALESCE(pr.brand,'') AS brand,
                   SUM(CASE WHEN m.type='entrada' THEN m.qty ELSE 0 END) AS entradas,
                   SUM(CASE WHEN m.type='salida'  THEN m.qty ELSE 0 END) AS salidas,
                   COUNT(m.id) AS movimientos
            FROM movements m
            LEFT JOIN products pr ON m.product_code = pr.code
            WHERE m.project_id = ?
            GROUP BY m.product_code, m.product_name, pr.brand
            ORDER BY m.product_name
        """, (p["id"],))
        p["movement_count"] = sum(int(i["movimientos"] or 0) for i in p["items"])
    return jsonify(projects)

@app.route("/api/projects", methods=["POST"])
def create_project():
    d    = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    if not name: return err("Falta el nombre")
    new_id = db_insert(
        "INSERT INTO projects (name,description,status) VALUES (?,?,?)",
        (name, d.get("description",""), d.get("status","activo")))
    return ok(id=new_id, name=name)

@app.route("/api/projects/<int:pid>", methods=["PUT"])
def update_project(pid):
    d = request.get_json(force=True)
    db_run("UPDATE projects SET name=?,description=?,status=? WHERE id=?",
           (d.get("name",""), d.get("description",""), d.get("status","activo"), pid))
    return ok()

@app.route("/api/projects/<int:pid>", methods=["DELETE"])
def delete_project(pid):
    db_run("DELETE FROM projects WHERE id=?", (pid,))
    return ok()


# ── Purchases ─────────────────────────────────────────────────────────────────
@app.route("/api/purchases", methods=["GET"])
def list_purchases():
    return jsonify(db_all("""
        SELECT pu.*, pr.name AS project_name
        FROM purchases pu
        LEFT JOIN projects pr ON pu.project_id = pr.id
        ORDER BY pu.created_at DESC
    """))

@app.route("/api/purchases", methods=["POST"])
def create_purchase():
    d = request.get_json(force=True)
    raw_proj = d.get("project_id")
    project_id = int(raw_proj) if raw_proj not in (None, "", "null") else None
    new_id = db_insert("""INSERT INTO purchases
        (product_code,product_name,supplier,qty,unit_price,currency,
         status,project_id,order_date,expected_date,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         project_id,
         d.get("order_date") or None, d.get("expected_date") or None,
         d.get("notes","")))
    return ok(id=new_id)

@app.route("/api/purchases/<int:pid>", methods=["PUT"])
def update_purchase(pid):
    d = request.get_json(force=True)
    raw_proj = d.get("project_id")
    project_id = int(raw_proj) if raw_proj not in (None, "", "null") else None
    db_run("""UPDATE purchases SET product_code=?,product_name=?,supplier=?,qty=?,
        unit_price=?,currency=?,status=?,project_id=?,order_date=?,expected_date=?,
        received_date=?,notes=? WHERE id=?""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         project_id,
         d.get("order_date") or None, d.get("expected_date") or None,
         d.get("received_date") or None, d.get("notes",""), pid))
    return ok()

@app.route("/api/purchases/<int:pid>", methods=["DELETE"])
def delete_purchase(pid):
    db_run("DELETE FROM purchases WHERE id=?", (pid,))
    return ok()


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    week_ago = (datetime.datetime.now() - timedelta(days=7)).isoformat()
    return jsonify({
        "total_products":    db_scalar("SELECT COUNT(*) FROM products") or 0,
        "total_stock":       db_scalar("SELECT SUM(stock) FROM products") or 0,
        "arrivals_week":     db_scalar("SELECT COUNT(*) FROM movements WHERE type='entrada' AND created_at>=?", (week_ago,)) or 0,
        "pending_purchases": db_scalar("SELECT COUNT(*) FROM purchases WHERE status NOT IN ('recibido')") or 0,
        "low_stock": db_all("SELECT code,name,brand,stock FROM products WHERE stock<=3 ORDER BY stock LIMIT 10"),
        "recent_movements": db_all("""
            SELECT m.*, p.brand, pr.name AS project_name
            FROM movements m
            LEFT JOIN products  p  ON m.product_code = p.code
            LEFT JOIN projects  pr ON m.project_id   = pr.id
            ORDER BY m.created_at DESC LIMIT 20"""),
    })


# ── Run (solo modo local / .exe) ───────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    cert = os.path.join(BASE_DIR, "cert.pem")
    key  = os.path.join(BASE_DIR, "key.pem")
    ssl_ctx = (cert, key) if (os.path.exists(cert) and not USE_PG) else None
    proto = "https" if ssl_ctx else "http"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
    except: ip = "127.0.0.1"
    finally: s.close()
    print(f"[Inventario] modo: {'PostgreSQL' if USE_PG else 'SQLite'}")
    print(f"[Inventario] {proto}://localhost:{port}")
    if not USE_PG: print(f"[Inventario] {proto}://{ip}:{port}")
    app.run(host="0.0.0.0", port=port, debug=False,
            ssl_context=ssl_ctx, use_reloader=False)
