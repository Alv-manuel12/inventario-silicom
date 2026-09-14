"""
Inventario QR — Silicom
Flask + SQLite (local/.exe) | PostgreSQL (Vercel + Supabase)
Todos los endpoints POST retornan {"success": true} con HTTP 200.
"""
import os, sys, json, socket
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, g, render_template, send_from_directory

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
    if USE_PG:
        import psycopg2.extras
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        db.commit()
        return cur
    cur = db.execute(sql, params)
    db.commit()
    return cur

def db_all(sql, params=()):
    cur = _exec(sql, params)
    return [dict(r) for r in cur.fetchall()]

def db_one(sql, params=()):
    cur = _exec(sql, params)
    r = cur.fetchone()
    return dict(r) if r else None

def db_run(sql, params=()):
    _exec(sql, params)

def db_scalar(sql, params=()):
    cur = _exec(sql, params)
    r = cur.fetchone()
    return (r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) if r else None

def db_insert(sql, params=()):
    db = get_db()
    if USE_PG:
        import psycopg2.extras
        cur = db.cursor()
        cur.execute((sql + " RETURNING id").replace("?", "%s"), params)
        db.commit()
        r = cur.fetchone()
        return r[0] if r else None
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid

def ok(**kwargs):
    """Respuesta estándar de éxito."""
    return jsonify({"success": True, **kwargs}), 200

def err(msg, status=400):
    return jsonify({"success": False, "error": msg}), status


# ── Init DB ───────────────────────────────────────────────────────────────────
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
        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding="utf-8") as f:
                seed = json.load(f)
            for s in seed:
                cur.execute(
                    "INSERT INTO products (code,name,brand,stock) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s["code"], s["name"], s.get("brand",""), s.get("stock",0)))
            print(f"[DB] {len(seed)} productos cargados (PostgreSQL)")
        conn.commit(); conn.close()
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
        try: conn.execute("ALTER TABLE products ADD COLUMN location TEXT DEFAULT ''"); conn.commit()
        except: pass
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding="utf-8") as f:
                seed = json.load(f)
            conn.executemany(
                "INSERT OR IGNORE INTO products (code,name,brand,stock) VALUES (?,?,?,?)",
                [(s["code"],s["name"],s.get("brand",""),s.get("stock",0)) for s in seed])
            conn.commit()
            print(f"[DB] {len(seed)} productos cargados (SQLite)")
        conn.close()


# ── Rutas estáticas ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


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
        params.append((datetime.now() - timedelta(days=7)).isoformat())
    elif filt == "2weeks":
        where.append("m.created_at >= ?")
        params.append((datetime.now() - timedelta(days=14)).isoformat())
    elif filt == "month":
        where.append("m.created_at >= ?")
        params.append((datetime.now() - timedelta(days=30)).isoformat())

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
    project_id = d.get("project_id") or None
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
        p["movement_count"] = sum(i["movimientos"] for i in p["items"])
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
    new_id = db_insert("""INSERT INTO purchases
        (product_code,product_name,supplier,qty,unit_price,currency,
         status,project_id,order_date,expected_date,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         d.get("project_id") or None,
         d.get("order_date") or None, d.get("expected_date") or None,
         d.get("notes","")))
    return ok(id=new_id)

@app.route("/api/purchases/<int:pid>", methods=["PUT"])
def update_purchase(pid):
    d = request.get_json(force=True)
    db_run("""UPDATE purchases SET product_code=?,product_name=?,supplier=?,qty=?,
        unit_price=?,currency=?,status=?,project_id=?,order_date=?,expected_date=?,
        received_date=?,notes=? WHERE id=?""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         d.get("project_id") or None,
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
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
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


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
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
