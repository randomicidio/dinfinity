# -*- coding: utf-8 -*-
"""Jogo de revelar imagens (portado do PuzzleLive). Widget embutível: pode ser
colocado dentro de uma aba do Dinfinity. O servidor HTTP continua servindo o
frame para o OBS (navegador apontando para http://127.0.0.1:<porta>)."""
import io
import os
import random
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image, ImageDraw, ImageTk

FPS = 60
FADE_SECONDS = 1.5
FADE_FRAMES = int(FPS * FADE_SECONDS)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class PuzzleWidget(ttk.Frame):
    def __init__(self, master, cfg, on_change=None):
        super().__init__(master)
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)

        self.image = None
        self.revealed = []
        self.history = []
        self.animating = {}
        self.hover_cell = None
        self.hover_alpha = int(cfg.get("hover_alpha", 220))
        self.random_pool = []
        self.obs_version = 0
        self.image_version = 0
        self.animation_running = False
        self.cached_obs_jpeg = None
        self.cached_obs_version = -1

        self.cols_var = tk.IntVar(value=int(cfg.get("cols", 3)))
        self.rows_var = tk.IntVar(value=int(cfg.get("rows", 6)))
        self.answer_var = tk.StringVar()
        self.remaining_var = tk.StringVar()

        self.shown_images = []
        self.image_pos = -1

        self.build_ui()
        self.load_image_list()

        if self.random_pool:
            try:
                path = self.random_pool.pop()
                self.shown_images.append(path)
                self.image_pos = 0
                self.load_image(path)
            except Exception as exc:
                print("Erro ao carregar imagem inicial:", exc)

        self.bind("<space>", lambda e: self.reveal_random())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Right>", lambda e: self.next_in_history())
        self.bind("<Left>", lambda e: self.prev_image())
        self.canvas.bind("<space>", lambda e: self.reveal_random())
        self.canvas.bind("<Control-z>", lambda e: self.undo())
        self.canvas.bind("<Right>", lambda e: self.next_in_history())
        self.canvas.bind("<Left>", lambda e: self.prev_image())
        self.start_obs_server()

    # ---------------- UI ----------------
    def build_ui(self):
        from core.theme import input_bg, is_dark, text_fg, window_bg
        # O Puzzle pode abrir standalone ou dentro do Dinfinity; a aparência
        # segue o tema global do customtkinter quando disponível.
        try:
            import customtkinter as _ctk
            escuro = _ctk.get_appearance_mode().lower() == "dark"
        except Exception:
            escuro = True
        self._escuro = escuro
        painel_bg = window_bg("dark" if escuro else "light")
        painel_fg = text_fg("dark" if escuro else "light")

        main = tk.Frame(self, bg=painel_bg)
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(main, bg="black", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas_image_id = None
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.left_click)
        self.canvas.bind("<Button-3>", self.right_click)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Leave>", self.on_leave)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        right = ttk.Frame(main, width=300)
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        right_canvas = tk.Canvas(right, width=300, highlightthickness=0, borderwidth=0,
                                 bg=painel_bg)
        right_canvas.grid(row=0, column=0, sticky="nsew")
        right_scroll = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        right_scroll.grid(row=0, column=1, sticky="ns")
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_inner = ttk.Frame(right_canvas)
        right_canvas.create_window((0, 0), window=right_inner, anchor="nw", width=300)

        def _on_panel_configure(_e):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))

        right_inner.bind("<Configure>", _on_panel_configure)
        right_canvas.bind("<MouseWheel>",
                          lambda e: right_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        right_inner.bind("<MouseWheel>",
                         lambda e: right_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        right = right_inner

        self.preview = ttk.Label(right)
        self.preview.pack(pady=5)
        ttk.Label(right, textvariable=self.answer_var, wraplength=240).pack(fill="x")

        grade = ttk.LabelFrame(right, text="Grade")
        grade.pack(fill="x", padx=10, pady=5)
        gr = ttk.Frame(grade)
        gr.pack(fill="x", padx=5, pady=2)
        ttk.Label(gr, text="Colunas").pack(side="left")
        ttk.Spinbox(gr, from_=2, to=50, textvariable=self.cols_var, width=5).pack(side="left", padx=(2, 12))
        ttk.Label(gr, text="Linhas").pack(side="left")
        ttk.Spinbox(gr, from_=2, to=50, textvariable=self.rows_var, width=5).pack(side="left", padx=2)
        ttk.Button(grade, text="Aplicar Grade", command=self.restart).pack(fill="x", padx=5, pady=5)

        ttk.Label(right, textvariable=self.remaining_var).pack()

        style = ttk.Style()
        try:
            style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=6)
        except Exception:
            pass

        imgf = ttk.LabelFrame(right, text="Imagem")
        imgf.pack(fill="x", padx=10, pady=5)
        ttk.Button(imgf, text="Próxima aleatória", command=self.next_random,
                   style="Big.TButton").pack(fill="x", padx=5, pady=(4, 6), ipady=4)

        nav = ttk.Frame(imgf)
        nav.pack(fill="x", padx=5, pady=2)
        ttk.Button(nav, text="Anterior", command=self.prev_image).pack(
            side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(nav, text="Seguinte", command=self.next_in_history).pack(
            side="left", fill="x", expand=True, padx=(2, 0))

        ttk.Button(imgf, text="Abrir imagem", command=self.open_image).pack(fill="x", padx=5, pady=2)
        ttk.Button(imgf, text="Pastas / Opções", command=self.open_options).pack(fill="x", padx=5, pady=2)

        rev = ttk.LabelFrame(right, text="Revelação")
        rev.pack(fill="x", padx=10, pady=5)
        ttk.Button(rev, text="Revelar aleatório", command=self.reveal_random).pack(fill="x", padx=5, pady=2)
        ttk.Button(rev, text="Desfazer última", command=self.undo).pack(fill="x", padx=5, pady=2)
        ttk.Button(rev, text="Reiniciar", command=self.restart).pack(fill="x", padx=5, pady=2)
        ttk.Button(rev, text="Mostrar tudo", command=self.show_all).pack(fill="x", padx=5, pady=2)

    # ---------------- pastas ----------------
    def load_config(self):
        folders = self.cfg.get("folders")
        if isinstance(folders, list) and folders:
            self.folders = [f for f in folders if isinstance(f, str)]
        else:
            self.folders = ["images"]
        self.recursive = bool(self.cfg.get("recursive", False))

    def save_config(self):
        self.cfg["folders"] = self.folders
        self.cfg["recursive"] = self.recursive
        self.cfg["cols"] = self.cols_var.get()
        self.cfg["rows"] = self.rows_var.get()
        self.cfg["hover_alpha"] = self.hover_alpha
        self.on_change()

    def load_image_list(self):
        self.load_config()
        pool = []
        for folder in self.folders:
            if not os.path.isdir(folder):
                if folder == "images":
                    os.makedirs("images", exist_ok=True)
                else:
                    continue
            try:
                if self.recursive:
                    for base, _dirs, files in os.walk(folder):
                        for f in files:
                            if f.lower().endswith(IMAGE_EXTS):
                                pool.append(os.path.join(base, f))
                else:
                    for f in os.listdir(folder):
                        if f.lower().endswith(IMAGE_EXTS):
                            pool.append(os.path.join(folder, f))
            except Exception as exc:
                print("Erro ao ler pasta", folder, ":", exc)
        self.random_pool = pool
        random.shuffle(self.random_pool)

    # ---------------- navegação / imagem ----------------
    def open_image(self):
        f = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if f:
            self.shown_images = self.shown_images[:self.image_pos + 1]
            self.shown_images.append(f)
            self.image_pos = len(self.shown_images) - 1
            self.load_image(f)

    def next_random(self):
        if not self.random_pool:
            self.load_image_list()
        if self.random_pool:
            path = self.random_pool.pop()
            self.shown_images = self.shown_images[:self.image_pos + 1]
            self.shown_images.append(path)
            self.image_pos = len(self.shown_images) - 1
            self.load_image(path)

    def next_in_history(self):
        if self.image_pos < len(self.shown_images) - 1:
            self.image_pos += 1
            self.load_image(self.shown_images[self.image_pos])

    def prev_image(self):
        if self.image_pos > 0:
            self.image_pos -= 1
            self.load_image(self.shown_images[self.image_pos])

    def open_options(self):
        from core.theme import input_bg, is_dark, text_fg, window_bg
        escuro = getattr(self, "_escuro", True)
        painel_bg = window_bg("dark" if escuro else "light")
        painel_fg = text_fg("dark" if escuro else "light")
        campo_bg = input_bg("dark" if escuro else "light")

        win = tk.Toplevel(self)
        win.title("Opções - Pastas de imagens")
        win.geometry("560x360")
        win.transient(self.winfo_toplevel())
        win.configure(bg=painel_bg)

        tk.Label(win, text="Pastas onde o programa busca as imagens:",
                 bg=painel_bg, fg=painel_fg).pack(anchor="w", padx=10, pady=(10, 0))

        frame = tk.Frame(win, bg=painel_bg)
        frame.pack(fill="both", expand=True, padx=10, pady=5)
        scroll = tk.Scrollbar(frame, bg=campo_bg, troughcolor=("dark" if escuro else "white"))
        scroll.pack(side="right", fill="y")
        listbox = tk.Listbox(frame, yscrollcommand=scroll.set, bg=campo_bg, fg=painel_fg,
                             selectbackground="#3f3350" if escuro else "#d9c7ee",
                             selectforeground="#ffffff" if escuro else "#1f1f1f",
                             relief="flat")
        listbox.pack(side="left", fill="both", expand=True)
        scroll.config(command=listbox.yview)
        for folder in self.folders:
            listbox.insert("end", folder)

        recursive_var = tk.BooleanVar(value=self.recursive)
        tk.Checkbutton(win, text="Incluir subpastas automaticamente (recursivo)",
                       variable=recursive_var, bg=painel_bg, fg=painel_fg,
                       activebackground=painel_bg, activeforeground=painel_fg,
                       selectcolor=(campo_bg if escuro else "#ffffff"),
                       highlightthickness=0).pack(anchor="w", padx=10)

        def add_folder():
            d = filedialog.askdirectory(parent=win)
            if d and d not in self.folders:
                self.folders.append(d)
                listbox.insert("end", d)

        def remove_folder():
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                listbox.delete(idx)
                del self.folders[idx]

        def apply_and_close():
            if not self.folders:
                self.folders = ["images"]
            self.recursive = recursive_var.get()
            self.save_config()
            self.load_image_list()
            win.destroy()

        btns = tk.Frame(win, bg=painel_bg)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Adicionar pasta...", command=add_folder).pack(side="left", padx=2)
        ttk.Button(btns, text="Remover selecionada", command=remove_folder).pack(side="left", padx=2)
        ttk.Button(btns, text="Salvar e fechar", command=apply_and_close).pack(side="right", padx=2)

    def load_image(self, path):
        self.cached_obs_jpeg = None
        self.cached_obs_version = -1
        self.tk_img = None
        self.tk_prev = None
        self.canvas_image_id = None
        self.image = Image.open(path).convert("RGB")
        self.answer_var.set(os.path.basename(path))
        self.image_version += 1
        self.hover_alpha = int(self.cfg.get("hover_alpha", 220))
        p = self.image.copy()
        p.thumbnail((280, 280))
        self.tk_prev = ImageTk.PhotoImage(p)
        self.preview.configure(image=self.tk_prev)
        self.restart()

    # ---------------- grade / revelação ----------------
    def restart(self):
        if not self.image:
            return
        self.cols = self.cols_var.get()
        self.rows = self.rows_var.get()
        self.revealed = [[False] * self.cols for _ in range(self.rows)]
        self.animating.clear()
        self.history.clear()
        self.update_counter()
        self.obs_version += 1
        self.cached_obs_jpeg = None
        self.redraw()
        self.save_config()

    def update_counter(self):
        total = self.rows * self.cols
        hidden = sum(not c for row in self.revealed for c in row)
        self.remaining_var.set(f"Blocos restantes: {hidden} / {total}")

    def render(self):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        img = self.image.copy()
        margin = 5
        img.thumbnail((max(cw - margin * 2, 10), max(ch - margin * 2, 10)))

        self.img_w, self.img_h = img.size
        self.off_x = (cw - self.img_w) // 2
        self.off_y = (ch - self.img_h) // 2

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        bw = self.img_w / self.cols
        bh = self.img_h / self.rows

        for r in range(self.rows):
            for c in range(self.cols):
                if self.revealed[r][c]:
                    continue
                if (r, c) in self.animating:
                    progress = self.animating[(r, c)]
                    alpha = int(255 * (1 - progress / FADE_FRAMES))
                elif (r, c) == self.hover_cell:
                    alpha = self.hover_alpha
                else:
                    alpha = 255
                alpha = max(0, min(255, alpha))

                x1 = int(c * bw)
                y1 = int(r * bh)
                x2 = min(int((c + 1) * bw), self.img_w - 1)
                y2 = min(int((r + 1) * bh), self.img_h - 1)

                draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0, alpha))

                grid = (120, 120, 120, 255)
                draw.line((x1, y1, x2, y1), fill=grid, width=2)
                draw.line((x1, y1, x1, y2), fill=grid, width=2)
                draw.line((x2, y1, x2, y2), fill=grid, width=2)
                draw.line((x1, y2, x2, y2), fill=grid, width=2)

        return Image.alpha_composite(img.convert("RGBA"), overlay)

    def redraw(self):
        if not self.image:
            return
        img = self.render()
        self.tk_img = ImageTk.PhotoImage(img)
        x = self.canvas.winfo_width() // 2
        y = self.canvas.winfo_height() // 2
        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(x, y, image=self.tk_img)
        else:
            self.canvas.coords(self.canvas_image_id, x, y)
            self.canvas.itemconfig(self.canvas_image_id, image=self.tk_img)

    def animation_loop(self):
        changed = False
        finished = []
        for cell in list(self.animating.keys()):
            self.animating[cell] += 1
            changed = True
            if self.animating[cell] >= FADE_FRAMES:
                finished.append(cell)
        for r, c in finished:
            self.animating.pop((r, c), None)
            self.revealed[r][c] = True
            self.update_counter()
            self.cached_obs_jpeg = None
            self.obs_version += 1
        if changed:
            self.obs_version += 1
            self.cached_obs_jpeg = None
            self.redraw()
        if self.animating:
            self.after(int(1000 / FPS), self.animation_loop)
        else:
            self.animation_running = False

    def ensure_animation_loop(self):
        if not self.animation_running:
            self.animation_running = True
            self.animation_loop()

    def start_reveal(self, r, c):
        if self.revealed[r][c] or (r, c) in self.animating:
            return
        self.animating[(r, c)] = 0
        self.history.append((r, c))
        self.ensure_animation_loop()

    def reveal_random(self):
        hidden = [(r, c) for r in range(self.rows) for c in range(self.cols)
                  if not self.revealed[r][c] and (r, c) not in self.animating]
        if hidden:
            self.start_reveal(*random.choice(hidden))

    def show_all(self):
        delay = 0
        hidden = [(r, c) for r in range(self.rows) for c in range(self.cols)
                  if not self.revealed[r][c] and (r, c) not in self.animating]
        for r, c in hidden:
            self.after(delay, lambda rr=r, cc=c: self.start_reveal(rr, cc))
            delay += 40

    def undo(self):
        if self.history:
            r, c = self.history.pop()
            self.animating.pop((r, c), None)
            self.revealed[r][c] = False
            self.update_counter()
            self.cached_obs_jpeg = None
            self.obs_version += 1
            self.redraw()

    def cell_at(self, x, y):
        if not self.image or not hasattr(self, "img_w"):
            return None
        if not (self.off_x <= x <= self.off_x + self.img_w):
            return None
        if not (self.off_y <= y <= self.off_y + self.img_h):
            return None
        c = int((x - self.off_x) / (self.img_w / self.cols))
        r = int((y - self.off_y) / (self.img_h / self.rows))
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return r, c

    def on_hover(self, e):
        p = self.cell_at(e.x, e.y)
        if p is not None:
            r, c = p
            if self.revealed[r][c] or (r, c) in self.animating:
                p = None
        if p != self.hover_cell:
            self.hover_cell = p
            self.redraw()

    def on_leave(self, e):
        if self.hover_cell is not None:
            self.hover_cell = None
            self.redraw()

    def on_wheel(self, e):
        if self.hover_cell is None:
            return
        steps = int(e.delta / 120) if e.delta else 0
        if steps == 0:
            return
        new_alpha = max(0, min(255, self.hover_alpha - steps * 15))
        if new_alpha != self.hover_alpha:
            self.hover_alpha = new_alpha
            self.redraw()

    def left_click(self, e):
        self.canvas.focus_set()
        p = self.cell_at(e.x, e.y)
        if p:
            self.start_reveal(*p)

    def right_click(self, e):
        p = self.cell_at(e.x, e.y)
        if p:
            r, c = p
            self.animating.pop((r, c), None)
            self.revealed[r][c] = False
            self.update_counter()
            self.cached_obs_jpeg = None
            self.obs_version += 1
            self.redraw()

    # ---------------- servidor OBS ----------------
    def render_obs_image(self):
        if not self.image:
            return None
        img = self.image.copy().convert("RGBA")
        img.thumbnail((1920, 1080))

        bw = img.width / self.cols
        bh = img.height / self.rows

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        for r in range(self.rows):
            for c in range(self.cols):
                if self.revealed[r][c]:
                    continue
                if (r, c) in self.animating:
                    progress = self.animating[(r, c)]
                    alpha = int(255 * (1 - progress / FADE_FRAMES))
                else:
                    alpha = 255
                alpha = max(0, min(255, alpha))

                x1 = int(c * bw)
                y1 = int(r * bh)
                x2 = min(int((c + 1) * bw), img.width - 1)
                y2 = min(int((r + 1) * bh), img.height - 1)

                draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0, alpha))

                grid = (120, 120, 120, 255)
                draw.line((x1, y1, x2, y1), fill=grid, width=6)
                draw.line((x1, y1, x1, y2), fill=grid, width=6)
                draw.line((x2, y1, x2, y2), fill=grid, width=6)
                draw.line((x1, y2, x2, y2), fill=grid, width=6)

        return Image.alpha_composite(img, overlay)

    def start_obs_server(self):
        app = self
        port = int(self.cfg.get("obs_port", 8765))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/version"):
                    data = ('{"version": %d, "animating": %s}' % (
                        app.obs_version,
                        "true" if app.animating else "false",
                    )).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                if self.path.startswith("/status"):
                    data = (b'{"animating": true}' if app.animating else b'{"animating": false}')
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                if self.path.startswith("/render"):
                    if app.cached_obs_version != app.obs_version or app.cached_obs_jpeg is None:
                        img = app.render_obs_image()
                        if img is None:
                            self.send_response(404)
                            self.end_headers()
                            return
                        buf = io.BytesIO()
                        img = img.convert("RGB")
                        img.save(buf, format="JPEG", quality=85)
                        app.cached_obs_jpeg = buf.getvalue()
                        app.cached_obs_version = app.obs_version
                    data = app.cached_obs_jpeg
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{margin:0;background:transparent;overflow:hidden;width:100%;height:100%;}
#frame{width:100%;height:100%;object-fit:contain;}
</style>
</head>
<body>
<img id="frame">
<script>
const frame=document.getElementById("frame");
let lastVersion=-1;
async function updateFrame(){
  try{
    const r=await fetch('/version?t='+Date.now());
    const s=await r.json();
    if(s.version !== lastVersion){
      const preload = new Image();
      preload.onload = function(){ frame.src = preload.src; lastVersion = s.version; };
      preload.src = '/render?v=' + s.version + '&t=' + Date.now();
    }
    setTimeout(updateFrame, s.animating ? 16 : 750);
  }catch(e){ setTimeout(updateFrame,1000); }
}
updateFrame();
</script>
</body>
</html>"""
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        def run():
            try:
                HTTPServer(("127.0.0.1", port), Handler).serve_forever()
            except Exception as exc:
                print("OBS server:", exc)

        threading.Thread(target=run, daemon=True).start()
