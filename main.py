import tkinter as tk
import tkinter.messagebox as messagebox
from PIL import Image, ImageTk
import random
import os
import pyautogui
import threading
import time
import pygame
import sys

# ---------------- Configuration (edit paths if needed) ----------------
DEFAULT_TEXTURE_FOLDER = "Textures/MiniRiska/Idle"        # folder with idle PNGs
DEFAULT_DRAG_TEXTURE = "Textures/MiniRiska/drag.png"
DEFAULT_POSSESSION_TEXTURE = "Textures/MiniRiska/angrysilly.png"
DEFAULT_SOUND_TEXTURE = "Textures/MiniRiska/silly.png"   # used for random sound AND release effect (Option 1)
DEFAULT_RELEASE_SOUND = "Sounds/hehehe.wav"
DEFAULT_RANDOM_SOUND = "Sounds/meow.wav"
# ---------------------------------------------------------------------

class MischievousMover:
    def __init__(self, master, mode,
                 texture_folder=DEFAULT_TEXTURE_FOLDER,
                 drag_texture_path=DEFAULT_DRAG_TEXTURE,
                 possession_texture_path=DEFAULT_POSSESSION_TEXTURE,
                 sound_texture_path=DEFAULT_SOUND_TEXTURE,
                 release_sound_path=DEFAULT_RELEASE_SOUND,
                 random_sound_path=DEFAULT_RANDOM_SOUND):

        self.master = master
        self.mode = mode  # "normal" or "side"
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

        # resolve full paths
        def full(p): return os.path.join(self.script_dir, p)
        self.texture_folder = full(texture_folder)
        self.drag_texture_path = full(drag_texture_path)
        self.possession_texture_path = full(possession_texture_path)
        self.sound_texture_path = full(sound_texture_path)
        self.release_sound_path = full(release_sound_path)
        self.random_sound_path = full(random_sound_path)

        # verify assets exist
        for path, name in [
            (self.texture_folder, "Texture folder"),
            (self.drag_texture_path, "Drag texture"),
            (self.possession_texture_path, "Possession texture"),
            (self.sound_texture_path, "Sound texture"),
            (self.release_sound_path, "Release sound"),
            (self.random_sound_path, "Random sound")
        ]:
            if not os.path.exists(path):
                raise Exception(f"{name} does not exist: {path}")

        # init pygame mixer
        pygame.mixer.init()
        try:
            self.release_sound = pygame.mixer.Sound(self.release_sound_path)
        except Exception:
            self.release_sound = None
        try:
            self.random_sound = pygame.mixer.Sound(self.random_sound_path)
        except Exception:
            self.random_sound = None

        # create top-level sprite window (must before PhotoImage)
        self.win = tk.Toplevel(self.master)
        self.win.overrideredirect(True)
        self.win.wm_attributes("-topmost", True)
        self.transparent_color = "#FF00FF"
        try:
            self.win.wm_attributes("-transparentcolor", self.transparent_color)
        except Exception:
            # not supported on some platforms, ignore
            pass

        # persistent image cache to avoid garbage collection
        self.textures_cache = {}
        # fixed textures
        self.textures_cache['drag'] = self._load_image(self.drag_texture_path, master=self.win)
        self.textures_cache['possession'] = self._load_image(self.possession_texture_path, master=self.win)
        self.textures_cache['sound'] = self._load_image(self.sound_texture_path, master=self.win)
        # preload all idle textures
        self.texture_files = [f for f in os.listdir(self.texture_folder) if f.lower().endswith(".png")]
        if not self.texture_files:
            raise Exception(f"No PNG textures found in: {self.texture_folder}")
        self.textures_cache['idle_list'] = []
        for fn in self.texture_files:
            p = os.path.join(self.texture_folder, fn)
            self.textures_cache['idle_list'].append(self._load_image(p, master=self.win))
        # choose initial idle
        self.textures_cache['idle'] = random.choice(self.textures_cache['idle_list'])
        # keep a current idle reference for restoring after temporary swaps
        self.current_idle_ref = self.textures_cache['idle']

        # position + flags
        self.x = 300.0
        self.y = 300.0
        self.dragging = False
        self.possessed = False
        self.offset_x = 0
        self.offset_y = 0
        self.running = True

        # canvas sized to idle image
        self.win_w = int(self.textures_cache['idle'].width())
        self.win_h = int(self.textures_cache['idle'].height())
        self.canvas = tk.Canvas(self.win, width=self.win_w, height=self.win_h,
                                highlightthickness=0, bg=self.transparent_color)
        self.canvas.pack()
        self.image_on_canvas = self.canvas.create_image(0, 0, image=self.current_idle_ref, anchor="nw")

        # screen info and initial geometry
        self.screen_w = int(self.win.winfo_screenwidth())
        self.screen_h = int(self.win.winfo_screenheight())
        self.win.geometry(f"{self.win_w}x{self.win_h}+{int(self.x)}+{int(self.y)}")

        # bindings
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        self.canvas.bind("<Button-1>", self.stop_possession_click, add="+")
        self.canvas.bind("<Button-3>", lambda e: self.trigger_random_sound_effect())

        # keep visible (periodic lift) to help on some platforms
        self._keep_visible_loop()

        # start behavior
        self.moving = False
        self.start()

    # helper to load & scale image (pixel-art safe), attach to specified master
    def _load_image(self, path, master=None):
        img = Image.open(path).convert("RGBA")
        new_w = max(1, int(img.width * 4))
        new_h = max(1, int(img.height * 4))
        img = img.resize((new_w, new_h), Image.NEAREST)
        return ImageTk.PhotoImage(img, master=master)

    def _keep_idle_on_canvas(self):
        # ensure canvas shows a valid PhotoImage (prevents some flicker issues)
        try:
            # if current image is None or empty, reset to idle
            current = self.canvas.itemcget(self.image_on_canvas, "image")
            if not current or current == "":
                self.canvas.itemconfig(self.image_on_canvas, image=self.current_idle_ref)
        except Exception:
            pass

    def _keep_visible_loop(self):
        if not self.running:
            return
        try:
            self.win.lift()
            self._keep_idle_on_canvas()
        except Exception:
            pass
        # repeat every 1000 ms
        self.win.after(1000, self._keep_visible_loop)

    # ---------------- Movement scheduling ----------------
    def start(self):
        if self.moving:
            return
        self.moving = True
        self.schedule_move()
        self.schedule_texture_change()
        self.schedule_random_sound()

    def destroy(self):
        self.running = False
        try:
            self.win.destroy()
        except Exception:
            pass
        try:
            pygame.mixer.quit()
        except Exception:
            pass

    def schedule_move(self):
        if not self.running:
            return
        self.win.after(random.randint(1000, 3500), self.pick_target)

    def pick_target(self):
        if not self.running:
            return
        # if possessed, movement controlled by possession thread — skip scheduling a normal move
        if self.possessed:
            self.schedule_move()
            return

        r = 100
        tx = int(self.x + random.randint(-r, r))
        ty = int(self.y + random.randint(-r, r))

        # Clamp
        tx = max(0, min(tx, self.screen_w - self.win_w))
        ty = max(0, min(ty, self.screen_h - self.win_h))

        # Side-mode bias (ignored if possessed)
        if self.mode == "side" and not self.possessed:
            left_x = 0
            right_x = self.screen_w - self.win_w
            nearest = left_x if abs(self.x - left_x) <= abs(self.x - right_x) else right_x
            alpha = 0.6
            tx = int(tx * (1 - alpha) + nearest * alpha)

        self.smooth_move_to(tx, ty)

    def smooth_move_to(self, tx, ty):
        if not self.running:
            return
        steps = 40
        dx = (tx - self.x) / steps
        dy = (ty - self.y) / steps

        def step():
            nonlocal steps
            if not self.running:
                return
            self.x += dx
            self.y += dy
            # clamp every step
            self.x = max(0, min(self.x, self.screen_w - self.win_w))
            self.y = max(0, min(self.y, self.screen_h - self.win_h))
            self.win.geometry(f"{self.win_w}x{self.win_h}+{int(self.x)}+{int(self.y)}")
            steps -= 1
            if steps > 0:
                self.win.after(10, step)
            else:
                self.schedule_move()
        step()

    # ---------------- Idle texture cycling ----------------
    def schedule_texture_change(self):
        if not self.running:
            return
        self.win.after(random.randint(1000, 2500), self.random_texture_change)

    def random_texture_change(self):
        if not self.running:
            return
        # only change idle when currently showing idle (no temp textures) and not dragging/possessed
        current_img_id = self.canvas.itemcget(self.image_on_canvas, "image")
        if (not self.dragging) and (not self.possessed) and (current_img_id == str(self.current_idle_ref)):
            self.current_idle_ref = random.choice(self.textures_cache['idle_list'])
            self.canvas.itemconfig(self.image_on_canvas, image=self.current_idle_ref)
        self.schedule_texture_change()

    # ---------------- Random & triggered sound effects ----------------
    def schedule_random_sound(self):
        if not self.running:
            return
        self.win.after(random.randint(5000, 15000), self.random_sound_play)

    def random_sound_play(self):
        if not self.running:
            return
        if (not self.possessed) and (self.random_sound is not None) and (random.random() < 0.3):
            self.trigger_random_sound_effect()
        self.schedule_random_sound()

    def trigger_random_sound_effect(self):
        if not self.running:
            return
        try:
            if self.random_sound: self.random_sound.play()
        except Exception:
            pass
        # temp swap to sound texture, then restore after 1s (but only if not possessed)
        old = self.current_idle_ref
        try:
            self.canvas.itemconfig(self.image_on_canvas, image=self.textures_cache['sound'])
        except Exception:
            pass
        def restore():
            time.sleep(1)
            if self.running and (not self.possessed):
                try:
                    self.canvas.itemconfig(self.image_on_canvas, image=old)
                except Exception:
                    pass
        threading.Thread(target=restore, daemon=True).start()

    # ---------------- Dragging (Option C: mixed) ----------------
    def start_drag(self, event):
        # ignore if already possessed
        if self.possessed:
            return
        self.dragging = True
        # store offsets within the widget
        self.offset_x = int(event.x)
        self.offset_y = int(event.y)
        # set drag texture
        try:
            self.canvas.itemconfig(self.image_on_canvas, image=self.textures_cache['drag'])
        except Exception:
            pass

        # attempt to steal after delay (30% chance)
        def attempt_possession():
            time.sleep(0.2)
            if self.running and self.dragging and (not self.possessed) and random.random() < 0.1:
                # start possession
                self.possessed = True
                self.dragging = False
                self.start_possession()
        threading.Thread(target=attempt_possession, daemon=True).start()

    def drag(self, event):
        if (not self.dragging) or self.possessed:
            return
        # compute target using root coords (mouse absolute position)
        # safer to use event.x_root, event.y_root to compute absolute coords
        try:
            tx = int(event.x_root - self.offset_x)
            ty = int(event.y_root - self.offset_y)
        except Exception:
            tx = int(self.win.winfo_x() + (event.x - self.offset_x))
            ty = int(self.win.winfo_y() + (event.y - self.offset_y))

        # clamp to screen
        tx = max(0, min(tx, self.screen_w - self.win_w))
        ty = max(0, min(ty, self.screen_h - self.win_h))

        # mixed movement: mostly snap but with small lag (Option C)
        self.x += (tx - self.x) * 0.5   # closer to cursor than previous 0.3
        self.y += (ty - self.y) * 0.5
        # clamp again and apply
        self.x = max(0, min(self.x, self.screen_w - self.win_w))
        self.y = max(0, min(self.y, self.screen_h - self.win_h))
        self.win.geometry(f"{self.win_w}x{self.win_h}+{int(self.x)}+{int(self.y)}")

    def end_drag(self, event):
        if not self.possessed:
            self.dragging = False
            try:
                self.canvas.itemconfig(self.image_on_canvas, image=self.current_idle_ref)
            except Exception:
                pass

    # ---------------- Possession (cursor stealing) ----------------
    def start_possession(self):
        # set possession texture immediately
        try:
            self.canvas.itemconfig(self.image_on_canvas, image=self.textures_cache['possession'])
        except Exception:
            pass

        def possession_loop():
            # while possessed, pick random targets and move there while forcing cursor
            while self.running and self.possessed:
                tx = random.randint(0, max(0, self.screen_w - self.win_w))
                ty = random.randint(0, max(0, self.screen_h - self.win_h))
                steps = max(1, int(max(abs(tx - self.x), abs(ty - self.y)) // 15))
                dx = (tx - self.x) / steps
                dy = (ty - self.y) / steps
                for _ in range(steps):
                    if (not self.running) or (not self.possessed):
                        return
                    self.x += dx
                    self.y += dy
                    # clamp always
                    self.x = max(0, min(self.x, self.screen_w - self.win_w))
                    self.y = max(0, min(self.y, self.screen_h - self.win_h))
                    try:
                        self.win.geometry(f"{self.win_w}x{self.win_h}+{int(self.x)}+{int(self.y)}")
                    except Exception:
                        pass
                    # move cursor to center of sprite (may fail in restricted envs)
                    try:
                        pyautogui.moveTo(int(self.x + self.win_w / 2), int(self.y + self.win_h / 2))
                    except Exception:
                        pass
                    time.sleep(0.02)

        threading.Thread(target=possession_loop, daemon=True).start()

    # clicking while possessed releases it (and plays release sound + texture)
    def stop_possession_click(self, event):
        if self.possessed:
            self.possessed = False
            # play release sound (if loaded) and show sound texture for 2 seconds (Option 1)
            try:
                if self.release_sound:
                    self.release_sound.play()
            except Exception:
                pass
            old = self.current_idle_ref
            try:
                # use the same sound texture for release (as requested option 1)
                self.canvas.itemconfig(self.image_on_canvas, image=self.textures_cache['sound'])
            except Exception:
                pass
            def restore_after_release():
                time.sleep(2)
                if self.running:
                    try:
                        self.canvas.itemconfig(self.image_on_canvas, image=old)
                    except Exception:
                        pass
            threading.Thread(target=restore_after_release, daemon=True).start()

# ---------------- Controller UI ----------------
class Controller:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MiniRiska Setup")
        self.root.geometry("360x160")
        self.root.resizable(False, False)

        tk.Label(self.root, text="What mode do you choose?").pack(pady=(10, 6))

        self.mode_var = tk.StringVar(value="normal")
        frame = tk.Frame(self.root)
        frame.pack()
        tk.Radiobutton(frame, text="Normal", variable=self.mode_var, value="normal").pack(side="left", padx=12)
        tk.Radiobutton(frame, text="Side", variable=self.mode_var, value="side").pack(side="left", padx=12)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=12)
        self.start_btn = tk.Button(btn_frame, text="Start", width=10, command=self.start_mover)
        self.start_btn.pack(side="left", padx=8)
        self.stop_btn = tk.Button(btn_frame, text="Stop", width=10, command=self.stop_all, state="normal")
        self.stop_btn.pack(side="left", padx=8)

        self.mover = None
        self.root.protocol("WM_DELETE_WINDOW", self.stop_all)

    def start_mover(self):
        if self.mover:
            return
        mode = self.mode_var.get()
        try:
            self.mover = MischievousMover(self.root, mode)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.start_btn.config(state="disabled")

    def stop_all(self):
        if self.mover:
            try:
                self.mover.destroy()
            except Exception:
                pass
            self.mover = None
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        sys.exit(0)

# ---------------- Run ----------------
if __name__ == "__main__":
    Controller()
    tk.mainloop()