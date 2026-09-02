"""
Inventario QR — Silicom v2
Soporta SQLite (local / .exe) y PostgreSQL (Railway + Supabase).
La variable de entorno DATABASE_URL activa el modo PostgreSQL automáticamente.
"""
import os, sys, json, socket
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, g, send_from_directory

# ── Paths ─────────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):          # corriendo como .exe
    BUNDLE_DIR = sys._MEIPASS
    BASE_DIR   = os.path.dirname(sys.executable)
else:                                      # corriendo como script
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR   = BUNDLE_DIR

STATIC_DIR = os.path.join(BUNDLE_DIR, "static")
SEED_PATH  = os.path.join(BUNDLE_DIR, "seed.json")
DB_PATH    = os.path.join(BASE_DIR,   "inventario.db")

# ── Modo base de datos ────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
USE_PG = bool(DATABASE_URL)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


# ── Helpers de base de datos ──────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
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
    db = g.pop('db', None)
    if db:
        db.close()

def db_all(sql, params=()):
    """Ejecuta una consulta y devuelve todas las filas como lista de dicts."""
    db = get_db()
    if USE_PG:
        import psycopg2.extras
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace('?', '%s'), params)
        return [dict(r) for r in cur.fetchall()]
    else:
        return [dict(r) for r in db.execute(sql, params).fetchall()]

def db_one(sql, params=()):
    """Ejecuta una consulta y devuelve una fila como dict (o None)."""
    db = get_db()
    if USE_PG:
        import psycopg2.extras
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace('?', '%s'), params)
        r = cur.fetchone()
        return dict(r) if r else None
    else:
        r = db.execute(sql, params).fetchone()
        return dict(r) if r else None

def db_run(sql, params=()):
    """Ejecuta un UPDATE o DELETE."""
    db = get_db()
    if USE_PG:
        cur = db.cursor()
        cur.execute(sql.replace('?', '%s'), params)
        db.commit()
    else:
        db.execute(sql, params)
        db.commit()

def db_insert(sql, params=()):
    """Ejecuta un INSERT y devuelve el ID generado."""
    db = get_db()
    if USE_PG:
        cur = db.cursor()
        cur.execute((sql + ' RETURNING id').replace('?', '%s'), params)
        db.commit()
        row = cur.fetchone()
        return row[0] if row else None
    else:
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid

def db_scalar(sql, params=()):
    """Ejecuta una consulta y devuelve el primer valor de la primera fila."""
    db = get_db()
    if USE_PG:
        cur = db.cursor()
        cur.execute(sql.replace('?', '%s'), params)
        r = cur.fetchone()
        return r[0] if r else None
    else:
        r = db.execute(sql, params).fetchone()
        return r[0] if r else None


# ── Inicialización de tablas ──────────────────────────────────────────────────
def init_db():
    if USE_PG:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT DEFAULT '',
                stock INTEGER NOT NULL DEFAULT 0, location TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                description TEXT DEFAULT '', status TEXT DEFAULT 'activo',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movements (
                id SERIAL PRIMARY KEY, product_code TEXT NOT NULL,
                product_name TEXT NOT NULL, type TEXT NOT NULL, qty INTEGER NOT NULL,
                stock_before INTEGER, stock_after INTEGER, project_id INTEGER,
                location TEXT DEFAULT '', notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY, product_code TEXT DEFAULT '',
                product_name TEXT NOT NULL, supplier TEXT DEFAULT '',
                qty INTEGER DEFAULT 1, unit_price REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'pendiente',
                project_id INTEGER, order_date DATE, expected_date DATE,
                received_date DATE, notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        cur.execute("SELECT COUNT(*) FROM products")
        count = cur.fetchone()[0]
        if count == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding='utf-8') as f:
                seed = json.load(f)
            for s in seed:
                cur.execute(
                    "INSERT INTO products (code,name,brand,stock) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s['code'], s['name'], s.get('brand',''), s.get('stock',0))
                )
            print(f"[Inventario] {len(seed)} productos precargados (PostgreSQL)")
        conn.commit(); conn.close()
    else:
        import sqlite3
        db = sqlite3.connect(DB_PATH)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT DEFAULT '',
                stock INTEGER NOT NULL DEFAULT 0, location TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                description TEXT DEFAULT '', status TEXT DEFAULT 'activo',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT NOT NULL,
                product_name TEXT NOT NULL, type TEXT NOT NULL, qty INTEGER NOT NULL,
                stock_before INTEGER, stock_after INTEGER, project_id INTEGER,
                location TEXT DEFAULT '', notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT DEFAULT '',
                product_name TEXT NOT NULL, supplier TEXT DEFAULT '',
                qty INTEGER DEFAULT 1, unit_price REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'pendiente',
                project_id INTEGER, order_date DATE, expected_date DATE,
                received_date DATE, notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        db.commit()
        try: db.execute("ALTER TABLE products ADD COLUMN location TEXT DEFAULT ''"); db.commit()
        except: pass
        count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0 and os.path.exists(SEED_PATH):
            with open(SEED_PATH, encoding='utf-8') as f:
                seed = json.load(f)
            db.executemany(
                "INSERT OR IGNORE INTO products (code,name,brand,stock) VALUES (?,?,?,?)",
                [(s['code'],s['name'],s.get('brand',''),s.get('stock',0)) for s in seed]
            )
            db.commit()
            print(f"[Inventario] {len(seed)} productos precargados (SQLite)")
        db.close()


# ── Rutas estáticas ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ── Productos ─────────────────────────────────────────────────────────────────
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
    if not name: return jsonify({"error": "Falta el nombre"}), 400
    if not code: return jsonify({"error": "Falta el código"}), 400
    if db_one("SELECT code FROM products WHERE code=?", (code,)):
        return jsonify({"error": "Ese código ya existe"}), 409
    db_run("INSERT INTO products (code,name,brand,stock,location) VALUES (?,?,?,?,?)",
           (code, name, brand, stock, loc))
    return jsonify({"code":code,"name":name,"brand":brand,"stock":stock,"location":loc}), 201

@app.route("/api/products/<code>", methods=["PUT"])
def update_product(code):
    d = request.get_json(force=True)
    db_run("UPDATE products SET name=?,brand=?,location=? WHERE code=?",
           (d.get("name",""), d.get("brand",""), d.get("location",""), code))
    return jsonify({"ok": True})

@app.route("/api/products/<code>", methods=["DELETE"])
def delete_product(code):
    db_run("DELETE FROM products WHERE code=?", (code,))
    return jsonify({"ok": True})


# ── Movimientos ───────────────────────────────────────────────────────────────
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
    if not row: return jsonify({"error": "Producto no encontrado"}), 404
    stock_before = row["stock"]
    if   mtype == "entrada": stock_after = stock_before + qty
    elif mtype == "salida":  stock_after = max(0, stock_before - qty)
    elif mtype == "ajuste":  stock_after = max(0, qty)
    else: return jsonify({"error": "Tipo inválido"}), 400
    if location:
        db_run("UPDATE products SET stock=?, location=? WHERE code=?", (stock_after, location, code))
    else:
        db_run("UPDATE products SET stock=? WHERE code=?", (stock_after, code))
    db_run("""INSERT INTO movements
        (product_code,product_name,type,qty,stock_before,stock_after,project_id,location,notes)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (code, row["name"], mtype, qty, stock_before, stock_after, project_id, location, notes))
    return jsonify({"code": code, "stock_before": stock_before, "stock_after": stock_after})

@app.route("/api/movements", methods=["GET"])
def list_movements():
    filt       = request.args.get("filter", "all")
    project_id = request.args.get("project_id")
    mtype      = request.args.get("type")
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
    if project_id: where.append("m.project_id = ?"); params.append(project_id)
    if mtype:      where.append("m.type = ?");       params.append(mtype)
    sql = """SELECT m.*, p.brand, p.location as product_location, pr.name as project_name
             FROM movements m
             LEFT JOIN products  p  ON m.product_code = p.code
             LEFT JOIN projects  pr ON m.project_id   = pr.id
             """ + ("WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY m.created_at DESC LIMIT 500"
    return jsonify(db_all(sql, params))


# ── Proyectos ─────────────────────────────────────────────────────────────────
@app.route("/api/projects", methods=["GET"])
def list_projects():
    return jsonify(db_all("""SELECT p.*, COUNT(m.id) as movement_count
        FROM projects p LEFT JOIN movements m ON p.id = m.project_id
        GROUP BY p.id ORDER BY p.created_at DESC"""))

@app.route("/api/projects", methods=["POST"])
def create_project():
    d = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    if not name: return jsonify({"error": "Falta el nombre"}), 400
    new_id = db_insert("INSERT INTO projects (name,description,status) VALUES (?,?,?)",
                       (name, d.get("description",""), d.get("status","activo")))
    return jsonify({"id": new_id, "name": name}), 201

@app.route("/api/projects/<int:pid>", methods=["PUT"])
def update_project(pid):
    d = request.get_json(force=True)
    db_run("UPDATE projects SET name=?,description=?,status=? WHERE id=?",
           (d.get("name",""), d.get("description",""), d.get("status","activo"), pid))
    return jsonify({"ok": True})

@app.route("/api/projects/<int:pid>", methods=["DELETE"])
def delete_project(pid):
    db_run("DELETE FROM projects WHERE id=?", (pid,))
    return jsonify({"ok": True})


# ── Compras ───────────────────────────────────────────────────────────────────
@app.route("/api/purchases", methods=["GET"])
def list_purchases():
    return jsonify(db_all("""SELECT pu.*, pr.name as project_name
        FROM purchases pu LEFT JOIN projects pr ON pu.project_id = pr.id
        ORDER BY pu.created_at DESC"""))

@app.route("/api/purchases", methods=["POST"])
def create_purchase():
    d = request.get_json(force=True)
    new_id = db_insert("""INSERT INTO purchases
        (product_code,product_name,supplier,qty,unit_price,currency,
         status,project_id,order_date,expected_date,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         d.get("project_id") or None, d.get("order_date") or None,
         d.get("expected_date") or None, d.get("notes","")))
    return jsonify({"id": new_id}), 201

@app.route("/api/purchases/<int:pid>", methods=["PUT"])
def update_purchase(pid):
    d = request.get_json(force=True)
    db_run("""UPDATE purchases SET product_code=?,product_name=?,supplier=?,
        qty=?,unit_price=?,currency=?,status=?,project_id=?,
        order_date=?,expected_date=?,received_date=?,notes=? WHERE id=?""",
        (d.get("product_code",""), d.get("product_name",""), d.get("supplier",""),
         int(d.get("qty") or 1), float(d.get("unit_price") or 0),
         d.get("currency","USD"), d.get("status","pendiente"),
         d.get("project_id") or None, d.get("order_date") or None,
         d.get("expected_date") or None, d.get("received_date") or None,
         d.get("notes",""), pid))
    return jsonify({"ok": True})

@app.route("/api/purchases/<int:pid>", methods=["DELETE"])
def delete_purchase(pid):
    db_run("DELETE FROM purchases WHERE id=?", (pid,))
    return jsonify({"ok": True})


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    return jsonify({
        "total_products":    db_scalar("SELECT COUNT(*) FROM products") or 0,
        "total_stock":       db_scalar("SELECT SUM(stock) FROM products") or 0,
        "arrivals_week":     db_scalar("SELECT COUNT(*) FROM movements WHERE type='entrada' AND created_at>=?", (week_ago,)) or 0,
        "pending_purchases": db_scalar("SELECT COUNT(*) FROM purchases WHERE status NOT IN ('recibido')") or 0,
        "low_stock":         db_all("SELECT code,name,brand,stock FROM products WHERE stock<=3 ORDER BY stock LIMIT 10"),
        "recent_movements":  db_all("""SELECT m.*, pr.name as project_name FROM movements m
            LEFT JOIN projects pr ON m.project_id=pr.id
            ORDER BY m.created_at DESC LIMIT 10"""),
    })


# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get('PORT', 5000))
    # SSL solo en modo local con cert generado (Railway maneja HTTPS él solo)
    cert = os.path.join(BASE_DIR, "cert.pem")
    key  = os.path.join(BASE_DIR, "key.pem")
    ssl_ctx = (cert, key) if (os.path.exists(cert) and not USE_PG) else None
    proto = "https" if ssl_ctx else "http"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8",80)); local_ip = s.getsockname()[0]
    except: local_ip = "127.0.0.1"
    finally: s.close()
    print(f" * Modo: {'PostgreSQL' if USE_PG else 'SQLite'}")
    print(f" * {proto}://localhost:{port}")
    if not USE_PG: print(f" * {proto}://{local_ip}:{port}")
    app.run(host="0.0.0.0", port=port, debug=False,
            ssl_context=ssl_ctx, use_reloader=False)
