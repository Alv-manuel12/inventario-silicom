"""
Lanzador local — genera SSL, arranca Flask y muestra ventana de control.
Solo se usa para el .exe local. En Railway se usa Procfile + gunicorn.
"""
import sys, os, socket, threading, webbrowser, tkinter as tk, tkinter.messagebox

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    BASE_DIR   = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR   = BUNDLE_DIR

os.chdir(BASE_DIR)
sys.path.insert(0, BUNDLE_DIR)

CERT = os.path.join(BASE_DIR, "cert.pem")
KEY  = os.path.join(BASE_DIR, "key.pem")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except: return "127.0.0.1"
    finally: s.close()

def generate_cert(ip):
    try:
        from OpenSSL import crypto
        k = crypto.PKey(); k.generate_key(crypto.TYPE_RSA, 2048)
        c = crypto.X509(); c.get_subject().CN = ip
        c.set_serial_number(1); c.gmtime_adj_notBefore(0); c.gmtime_adj_notAfter(365*24*60*60)
        c.set_issuer(c.get_subject()); c.set_pubkey(k); c.sign(k, "sha256")
        open(CERT,"wb").write(crypto.dump_certificate(crypto.FILETYPE_PEM, c))
        open(KEY, "wb").write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
        return True
    except Exception as e: print(f"[SSL] {e}"); return False

def run_server(ssl_ctx):
    from app import app, init_db
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False, ssl_context=ssl_ctx, use_reloader=False)

def main():
    ip = get_local_ip()
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        generate_cert(ip)
    use_https  = os.path.exists(CERT) and os.path.exists(KEY)
    ssl_ctx    = (CERT, KEY) if use_https else None
    proto      = "https" if use_https else "http"
    url_local  = f"{proto}://localhost:5000"
    url_celular = f"{proto}://{ip}:5000"

    threading.Thread(target=run_server, args=(ssl_ctx,), daemon=True).start()
    import time; time.sleep(1.5)
    import webbrowser; webbrowser.open(url_local)

    root = tk.Tk()
    root.title("Inventario QR — Silicom")
    root.geometry("440x300")
    root.resizable(False, False)
    root.configure(bg="#F0F7FC")

    def on_close():
        if tk.messagebox.askokcancel("Cerrar","¿Cerrar el servidor?\nEl celular perderá la conexión."):
            root.destroy(); os._exit(0)
    root.protocol("WM_DELETE_WINDOW", on_close)

    hdr = tk.Frame(root, bg="#1A4F9C"); hdr.pack(fill="x")
    tk.Label(hdr, text="SILICOM", font=("Arial",16,"bold"), bg="#1A4F9C", fg="white", padx=16, pady=10).pack(side="left")
    tk.Label(hdr, text="Control de Inventario QR", font=("Arial",9), bg="#1A4F9C", fg="#C8DFF0", padx=4).pack(side="left")

    body = tk.Frame(root, bg="#F0F7FC", padx=20, pady=14); body.pack(fill="both", expand=True)
    tk.Label(body, text="● Servidor activo", font=("Arial",10,"bold"), bg="#F0F7FC", fg="#1E8A5E").pack(anchor="w")
    tk.Label(body, text="En esta PC:", font=("Arial",9), bg="#F0F7FC", fg="#7A99B5").pack(anchor="w", pady=(10,2))
    l1 = tk.Label(body, text=url_local, font=("Courier",10,"bold"), bg="#E8F4FB", fg="#1A4F9C", cursor="hand2", padx=10, pady=6, anchor="w")
    l1.pack(fill="x"); l1.bind("<Button-1>", lambda e: webbrowser.open(url_local))
    tk.Label(body, text="Desde celular / otras PCs:", font=("Arial",9), bg="#F0F7FC", fg="#7A99B5").pack(anchor="w", pady=(12,2))
    l2 = tk.Label(body, text=url_celular, font=("Courier",12,"bold"), bg="#1A4F9C", fg="white", cursor="hand2", padx=10, pady=8, anchor="w")
    l2.pack(fill="x"); l2.bind("<Button-1>", lambda e: webbrowser.open(url_celular))
    ssl_txt = "🔒 HTTPS activo — cámara habilitada" if use_https else "⚠️ Sin HTTPS — cámara no disponible"
    tk.Label(body, text=ssl_txt, font=("Arial",8), bg="#F0F7FC", fg="#1E8A5E" if use_https else "#C0392B").pack(anchor="w", pady=(6,0))
    tk.Button(root, text="Cerrar servidor", command=on_close, bg="#C0392B", fg="white",
              font=("Arial",10,"bold"), relief="flat", pady=8, cursor="hand2").pack(fill="x", padx=20, pady=(0,16))
    root.mainloop()

if __name__ == "__main__":
    main()
