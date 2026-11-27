# -*- coding: utf-8 -*-
"""画像・GIFスライドショー (Tkinter + Pillow)

必要ライブラリ:  pip install pillow send2trash
操作:  ←/→ 送り戻し / Space 自動送り / Delete 削除(ゴミ箱) / F2 名前変更 / Enter エクスプローラーでファイルを選択
"""
import os
import re
import sys
import json
import time
import random
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageTk, ImageSequence, ImageOps

try:
    from send2trash import send2trash
except ImportError:  # 未インストール時は削除ボタンで案内
    send2trash = None

EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
SORTS = ["ファイル名順", "更新日順", "ランダム"]
INTERVALS = [1, 2, 3, 5, 10, 30, 60]
TOPS = ["アクティブ時手前表示", "常時手前表示"]   # 表示メニュー(既定は先頭)
DEFAULT_SORT = "ランダム"          # 起動時の並び
MENU_FONT = ("Yu Gothic UI", 13)   # メニューの行の高さ(行間)はフォントサイズで決まる
BG = "#202020"
INVALID = re.compile(r'[\\/:*?"<>|]')


def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "image-slideshow", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def resource_path(name):
    """通常実行・PyInstaller実行のどちらでも同梱ファイルを探す"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


class App:
    def __init__(self, root):
        self.root = root
        root.title("image-slideshow")
        try:
            root.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass
        root.geometry("900x650")
        root.minsize(480, 320)

        self.files = []          # 全ファイル(サブフォルダ横断)
        self.fileset = set()
        self.idx = 0
        self.auto_job = None
        self.anim_job = None
        self.resize_job = None
        self.frames = []         # GIFの元フレーム(RGBA)
        self.durations = []
        self.frame_cache = {}
        self.frame_i = 0
        self.photo = None
        self.cur_size = (0, 0)
        self.fullscreen = False
        self._cursor_job = None
        self._last_xy = None

        self.settings = load_settings()
        self._build_ui()
        self._bind_keys()
        self.apply_topmost(save=False)
        root.after(200, self.add_folder)

    # ---------------- UI ----------------
    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=4)
        bar.pack(side="top", fill="x")
        self.bar = bar

        def btn(text, cmd):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=2)
            return b

        iv = str(self.settings.get("interval", "3"))
        try:
            iv = iv if 0.2 <= float(iv) <= 600 else "3"
        except ValueError:
            iv = "3"
        sv = self.settings.get("sort", DEFAULT_SORT)
        tv = self.settings.get("topmost", TOPS[0])
        self.interval = tk.StringVar(value=iv)
        self.sort_var = tk.StringVar(value=sv if sv in SORTS else DEFAULT_SORT)
        self.top_var = tk.StringVar(value=tv if tv in TOPS else TOPS[0])
        self._clicks = 0
        self._click_job = None

        # ☰ メニュー
        menu = tk.Menu(self.root, tearoff=0, font=MENU_FONT)
        menu.add_command(label="フォルダを追加…", command=self.add_folder)
        menu.add_command(label="ファイルを追加…", command=self.add_files)
        menu.add_command(label="名前変更…  (F2)", command=self.rename_current)
        menu.add_command(label="リセット(再生リストを空にする)", command=self.reset_list)
        menu.add_separator()
        im = tk.Menu(menu, tearoff=0, font=MENU_FONT)
        for s in INTERVALS:
            im.add_radiobutton(label=f"{s}秒", variable=self.interval, value=str(s),
                               command=self._interval_changed)
        im.add_separator()
        im.add_command(label="秒数を指定…", command=self.ask_interval)
        menu.add_cascade(label="自動送りの間隔", menu=im)
        sm = tk.Menu(menu, tearoff=0, font=MENU_FONT)
        for s in SORTS:
            sm.add_radiobutton(label=s, variable=self.sort_var, value=s,
                               command=self._sort_changed)
        menu.add_cascade(label="並び", menu=sm)
        tm = tk.Menu(menu, tearoff=0, font=MENU_FONT)
        for s in TOPS:
            tm.add_radiobutton(label=s, variable=self.top_var, value=s,
                               command=self.apply_topmost)
        menu.add_cascade(label="ウィンドウ手前表示", menu=tm)
        menu.add_command(label="全画面表示  (F11)", command=self.enter_fullscreen)
        mb = ttk.Menubutton(bar, text="☰ メニュー", menu=menu)
        mb.pack(side="left", padx=2)

        self.auto_btn = btn("▶ 自動送り", self.toggle_auto)
        btn("◀ 戻る", self.prev)
        btn("送る ▶", self.next)
        btn("🗑 削除", self.delete_current)
        btn("📁 ファイル選択", self.reveal_in_explorer)
        btn("？ キー操作", self.show_help)

        # ボタンが常にすべて見えるよう、最小幅をボタン列の必要幅に合わせる
        self.root.update_idletasks()
        self.root.minsize(bar.winfo_reqwidth() + 8, 320)

        # 枚数・位置・ファイル名はボタンの右側に表示。幅が足りないときは右端が切れる
        self.status = tk.StringVar(value="フォルダを追加してください")
        ttk.Label(bar, textvariable=self.status, anchor="w", width=1).pack(
            side="left", fill="x", expand=True, padx=(10, 0))

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.prev() if e.delta > 0 else self.next())
        self.canvas.bind("<Button-4>", lambda e: self.prev())
        self.canvas.bind("<Button-5>", lambda e: self.next())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)

    def _bind_keys(self):
        r = self.root
        r.bind("<Left>", lambda e: self.prev())
        r.bind("<Right>", lambda e: self.next())
        r.bind("<space>", lambda e: self.toggle_auto())
        r.bind("<Delete>", lambda e: self.delete_current())
        r.bind("<F2>", lambda e: self.rename_current())
        r.bind("<Return>", lambda e: self.reveal_in_explorer())
        r.bind("<F11>", lambda e: self.toggle_fullscreen())
        r.bind("<Escape>", lambda e: self.exit_fullscreen())

    # ---------------- ファイル追加 ----------------
    def _add_paths(self, paths):
        cur = self.current_path()
        added = 0
        for p in paths:
            p = os.path.normpath(p)
            if p not in self.fileset and os.path.splitext(p)[1].lower() in EXTS:
                self.fileset.add(p)
                self.files.append(p)
                added += 1
        if added:
            self.apply_sort(keep=cur)
        return added

    def add_folder(self):
        d = filedialog.askdirectory(title="フォルダを選択(サブフォルダも含めて読み込みます)")
        if not d:
            return
        paths = []
        for base, _dirs, names in os.walk(d):
            for n in names:
                paths.append(os.path.join(base, n))
        n = self._add_paths(paths)
        self.status.set(f"{n} 件追加しました") if n else messagebox.showinfo(
            "追加なし", "追加できる画像がありませんでした(重複・非対応形式)")
        if n and len(self.files) == n:
            self.idx = 0
            self.show()
            if self.auto_job is None:
                self._start_auto()

    def add_files(self):
        fs = filedialog.askopenfilenames(
            title="ファイルを選択",
            filetypes=[("画像", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("すべて", "*.*")])
        if not fs:
            return
        first = not self.files
        n = self._add_paths(fs)
        if n and first:
            self.idx = 0
            self.show()
            if self.auto_job is None:
                self._start_auto()

    # ---------------- 並び替え ----------------
    def apply_sort(self, keep=None):
        if keep is None:
            keep = self.current_path()
        mode = self.sort_var.get()
        if mode == "ファイル名順":
            self.files.sort(key=lambda p: natural_key(os.path.basename(p)))
        elif mode == "更新日順":
            def mt(p):
                try:
                    return os.path.getmtime(p)
                except OSError:
                    return 0
            self.files.sort(key=mt)
        else:
            random.shuffle(self.files)
        self.idx = self.files.index(keep) if keep in self.files else 0
        self.show()

    # ---------------- 移動 ----------------
    def current_path(self):
        return self.files[self.idx] if 0 <= self.idx < len(self.files) else None

    def next(self, from_auto=False):
        if self.files:
            self.idx = (self.idx + 1) % len(self.files)
            self.show()

    def prev(self):
        if self.files:
            self.idx = (self.idx - 1) % len(self.files)
            self.show()

    # ---------------- 自動送り ----------------
    def _interval_ms(self):
        try:
            return max(200, int(float(self.interval.get()) * 1000))
        except ValueError:
            return 3000

    def toggle_auto(self):
        if self.auto_job is not None:
            self._stop_auto()
        else:
            self._start_auto()

    def _start_auto(self):
        self.auto_btn.config(text="■ 停止")
        self._schedule_auto()

    def _stop_auto(self):
        if self.auto_job is not None:
            self.root.after_cancel(self.auto_job)
            self.auto_job = None
        self.auto_btn.config(text="▶ 自動送り")

    def _schedule_auto(self):
        self.auto_job = self.root.after(self._interval_ms(), self._auto_tick)

    def _auto_tick(self):
        self.auto_job = None
        self.next()
        self.auto_btn.config(text="■ 停止")
        self._schedule_auto()

    def _restart_auto(self):
        if self.auto_job is not None:
            self.root.after_cancel(self.auto_job)
            self._schedule_auto()

    # ---------------- 設定の保存 ----------------
    def save_settings(self):
        d = {"interval": self.interval.get(), "sort": self.sort_var.get(),
             "topmost": self.top_var.get()}
        try:
            path = settings_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _interval_changed(self):
        self._restart_auto()
        self.save_settings()

    def _sort_changed(self):
        self.apply_sort()
        self.save_settings()

    def apply_topmost(self, save=True):
        try:
            self.root.attributes("-topmost", self.top_var.get() == TOPS[1])
        except Exception:
            pass
        if save:
            self.save_settings()

    # ---------------- 画像クリック ----------------
    def _on_click(self, _e):
        """1回: 自動送りの停止/再開(約0.4秒待って判定) / 2回: 何もしない / 3回: エクスプローラーで選択
        全画面中は、1回のクリックで解除する"""
        if self.fullscreen:
            if time.time() - self._fs_at > 0.4:   # 全画面にした直後のクリックは無視
                self.exit_fullscreen()
            return
        self._clicks += 1
        if self._click_job is not None:
            self.root.after_cancel(self._click_job)
            self._click_job = None
        if self._clicks >= 3:
            self._clicks = 0
            self.reveal_in_explorer()
            return
        self._click_job = self.root.after(400, self._click_done)

    # ---------------- 全画面表示 ----------------
    def toggle_fullscreen(self):
        if self.fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if self.fullscreen:
            return
        self._prev_geom = self.root.geometry()
        self._prev_state = self.root.state()
        self.fullscreen = True
        self._fs_at = time.time()
        self.bar.pack_forget()
        self.root.attributes("-fullscreen", True)
        self._arm_cursor_hide()

    def exit_fullscreen(self):
        if not self.fullscreen:
            return
        self.fullscreen = False
        self.root.attributes("-fullscreen", False)
        self.bar.pack(side="top", fill="x", before=self.canvas)
        try:
            if self._prev_state == "zoomed":
                self.root.state("zoomed")
            else:
                self.root.state("normal")
                self.root.geometry(self._prev_geom)
        except Exception:
            pass
        if self._cursor_job is not None:
            self.root.after_cancel(self._cursor_job)
            self._cursor_job = None
        self.canvas.config(cursor="")

    def _arm_cursor_hide(self):
        """全画面中、マウスを約2.5秒動かさないとカーソルを消す"""
        if self._cursor_job is not None:
            self.root.after_cancel(self._cursor_job)
        self._cursor_job = self.root.after(2500, self._hide_cursor)

    def _hide_cursor(self):
        self._cursor_job = None
        if self.fullscreen:
            self.canvas.config(cursor="none")

    def _on_motion(self, e):
        if not self.fullscreen:
            return
        if self._last_xy == (e.x, e.y):   # カーソル変更で出る見かけ上の動きは無視
            return
        self._last_xy = (e.x, e.y)
        self.canvas.config(cursor="")
        self._arm_cursor_hide()

    def _click_done(self):
        n, self._clicks, self._click_job = self._clicks, 0, None
        if n == 1 and self.files:
            self.toggle_auto()

    def ask_interval(self):
        try:
            cur = float(self.interval.get())
        except ValueError:
            cur = 3.0
        v = simpledialog.askfloat("自動送りの間隔", "秒数(0.2〜600):", initialvalue=cur,
                                  minvalue=0.2, maxvalue=600, parent=self.root)
        if v is not None:
            self.interval.set(f"{v:g}")
            self._restart_auto()
            self.save_settings()

    # ---------------- リセット・ヘルプ ----------------
    def reset_list(self):
        if not self.files:
            return
        if not messagebox.askyesno("リセット",
                                   "再生リストを空にします。\n(ファイルは削除されません)"):
            return
        self._stop_auto()
        self._release()
        self.files.clear()
        self.fileset.clear()
        self.idx = 0
        self.root.title("image-slideshow")
        self.status.set("リセットしました。☰メニューからフォルダ/ファイルを追加してください")

    def show_help(self):
        w = tk.Toplevel(self.root)
        w.title("キー操作")
        w.resizable(False, False)
        text = ("←  /  マウスホイール上     前の画像\n"
                "→  /  マウスホイール下     次の画像\n"
                "Space                      自動送り 開始/停止\n"
                "Delete                     ゴミ箱へ削除\n"
                "F2                         名前変更\n"
                "Enter                      エクスプローラーでファイルを選択\n"
                "F11                        全画面表示の切替\n"
                "Esc / 全画面中にクリック   全画面を解除\n"
                "画像をクリック             自動送り 停止/再開\n"
                "画像をトリプルクリック     エクスプローラーでファイルを選択\n"
                "(ダブルクリックは何もしません)")
        ttk.Label(w, text=text, font=("MS Gothic", 10), justify="left",
                  padding=16).pack()
        ttk.Button(w, text="閉じる", command=w.destroy).pack(pady=(0, 12))
        w.transient(self.root)

    # ---------------- 表示 ----------------
    def _on_resize(self, e):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(80, self._redraw)

    def _redraw(self):
        self.resize_job = None
        if self.frames:
            self.frame_cache.clear()
            self._draw_frame()

    def _stop_anim(self):
        if self.anim_job:
            self.root.after_cancel(self.anim_job)
            self.anim_job = None

    def show(self):
        self._stop_anim()
        self.frames, self.durations, self.frame_cache = [], [], {}
        self.frame_i = 0
        self.canvas.delete("all")
        path = self.current_path()
        if not path:
            self.status.set("画像がありません。「＋フォルダ」で追加してください")
            return
        self.root.title(f"image-slideshow - {os.path.basename(path)}")
        self.status.set(f"{self.idx + 1} / {len(self.files)}   {os.path.basename(path)}")
        try:
            with Image.open(path) as im:
                if getattr(im, "is_animated", False) and im.n_frames > 1:
                    for fr in ImageSequence.Iterator(im):
                        self.frames.append(fr.convert("RGBA"))
                        d = fr.info.get("duration", 100)
                        self.durations.append(100 if d <= 10 else d)
                else:
                    im = ImageOps.exif_transpose(im)
                    self.frames = [im.convert("RGBA")]
                    self.durations = [0]
        except Exception as ex:
            self.canvas.create_text(
                self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2,
                text=f"表示できません\n{ex}", fill="#ddd", justify="center")
            return
        self._draw_frame()
        if len(self.frames) > 1:
            self.anim_job = self.root.after(self.durations[0], self._animate)

    def _animate(self):
        self.frame_i = (self.frame_i + 1) % len(self.frames)
        self._draw_frame()
        self.anim_job = self.root.after(self.durations[self.frame_i], self._animate)

    def _draw_frame(self):
        cw, ch = max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)
        ph = self.frame_cache.get(self.frame_i)
        if ph is None:
            im = self.frames[self.frame_i]
            s = min(cw / im.width, ch / im.height)
            size = (max(1, int(im.width * s)), max(1, int(im.height * s)))
            ph = ImageTk.PhotoImage(im.resize(size, Image.LANCZOS))
            self.frame_cache[self.frame_i] = ph
        self.photo = ph
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=ph, anchor="center")

    # ---------------- 操作ボタン ----------------
    def _release(self):
        """ファイルを掴んだままにしないよう表示を止める"""
        self._stop_anim()
        self.frames, self.frame_cache, self.photo = [], {}, None
        self.canvas.delete("all")

    def delete_current(self):
        path = self.current_path()
        if not path:
            return
        if send2trash is None:
            messagebox.showerror("削除できません",
                                 "send2trash が未インストールです。\npip install send2trash を実行してください。")
            return
        if not messagebox.askyesno("削除の確認",
                                   f"ゴミ箱へ移動します。\n\n{os.path.basename(path)}"):
            return
        self._release()
        try:
            send2trash(path)
        except Exception as ex:
            messagebox.showerror("削除失敗", str(ex))
            self.show()
            return
        self.files.pop(self.idx)
        self.fileset.discard(path)
        if self.idx >= len(self.files):
            self.idx = 0
        self.show()

    def rename_current(self):
        path = self.current_path()
        if not path:
            return
        folder, name = os.path.split(path)
        stem, ext = os.path.splitext(name)
        new = simpledialog.askstring("名前変更", f"新しいファイル名(拡張子 {ext} は維持):",
                                     initialvalue=stem, parent=self.root)
        if new is None:
            return
        new = new.strip()
        if not new or INVALID.search(new):
            messagebox.showerror("名前変更", "使用できない文字が含まれているか、空です。")
            return
        new_path = os.path.join(folder, new + ext)
        if new_path != path and os.path.exists(new_path):
            messagebox.showerror("名前変更", "同名のファイルが既にあります。")
            return
        self._release()
        try:
            os.rename(path, new_path)
        except Exception as ex:
            messagebox.showerror("名前変更失敗", str(ex))
            self.show()
            return
        self.files[self.idx] = new_path
        self.fileset.discard(path)
        self.fileset.add(new_path)
        self.show()

    def reveal_in_explorer(self):
        """エクスプローラーで現在のファイルを選択した状態にする(右クリックで各種操作できる)"""
        path = self.current_path()
        if not path:
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as ex:
            messagebox.showerror("エクスプローラーを開けません", str(ex))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
