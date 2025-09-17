"""
phish_detector_advanced.py
Advanced Phishing Link Detector (Tkinter)

Features:
 - 5+ randomized phishing emails (levels)
 - fuzzy matching using difflib (tolerant to typos / partial phrases)
 - highlights matched tokens inside the email Text widget
 - per-email timer with visual progress bar
 - lives system (player loses a life for skipping/failing)
 - "Next Email" button enabled after at least one correct find
 - Hint button (costs points, highlights an unmatched flag)
 - Pause / Resume
 - Score multipliers (bonus for finding all flags quickly)
 - End-of-game summary (found vs missed per email)
 - Local leaderboard saved in "leaderboard.json"
"""

import tkinter as tk
from tkinter import simpledialog, messagebox, ttk
import random
import difflib
import json
import os
import time

# ---------------------------
# Configuration / Templates
# ---------------------------

BASE_TIME = 40           # starting seconds per email (scales down with level)
HINT_COST_BASE = 6       # base penalty for hints; scales with level
BONUS_PERFECT = 15       # extra points for finding all flags this email
LEADERBOARD_FILE = "leaderboard.json"
MAX_LEADERS = 10

# Phishing email templates (>=5)
EMAILS = [
    {
        "title": "Bank Security Notice",
        "text": """Dear Customer,

We detected unusual activity on your account. Please verify your account immediately by clicking:
http://secure-bank.verify-account.xyz/confirm

Failure to do so will result in account suspension.

Sincerely,
Secure Bank Support""",
        "flags": ["verify", "verify-account", ".xyz", "http://", "suspension", "Dear Customer"]
    },
    {
        "title": "Password Reset (IT)",
        "text": """Hello John,

Our system requires you to reset your password due to a security update.
Click here to reset: https://company-it-reset.secure-now.net/reset?user=john

If you didn't request this, reply with your username and password.

-- IT Helpdesk""",
        "flags": ["reset", "company-it-reset", "secure-now.net", "reply with your username", "password"]
    },
    {
        "title": "PayPal Account Change",
        "text": """Hi,

We updated your account details. To view changes, go to:
http://paypal.com-security.info/view

Note: This link will expire in 24 hours.

Regards,
PayPal Security Team""",
        "flags": ["paypal", "paypal.com-security.info", "expire", "24 hours", "link"]
    },
    {
        "title": "Unauthorized Login Alert",
        "text": """ATTENTION!

We detected unauthorized login from Russia.
If this wasn’t you, confirm immediately: http://secure-login-warning.com
Failure to act may result in account lock.""",
        "flags": ["Russia", "unauthorized", "secure-login-warning.com", "confirm immediately", "account lock"]
    },
    {
        "title": "Prize / Payment Request",
        "text": """Congratulations!

You are the lucky winner of a $1000 Amazon gift card.
Please enter your credit card details here: http://amazon-prize-free.net

Don’t miss this chance!""",
        "flags": ["$1000", "credit card", "amazon-prize-free.net", "winner", "enter your credit card"]
    },
    # Additional variations to increase replayability:
    {
        "title": "Fake Invoice",
        "text": """Hello,

Please find attached invoice INV-9923. Open the attachment to view it: INV_9923.exe

If you have questions contact accounts@payroll.example

Regards.""",
        "flags": ["INV-9923", "INV_9923.exe", ".exe", "accounts@", "invoice"]
    }
]

# ---------------------------
# Utility functions
# ---------------------------

def load_leaderboard():
    if not os.path.exists(LEADERBOARD_FILE):
        return []
    try:
        with open(LEADERBOARD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def save_leaderboard(board):
    try:
        with open(LEADERBOARD_FILE, "w", encoding="utf-8") as f:
            json.dump(board[:MAX_LEADERS], f, indent=2)
    except Exception:
        pass

def fuzzy_match(user_input, token):
    """
    Return True if user_input matches token tolerantly.
    Uses:
     - case-insensitive substring
     - difflib SequenceMatcher ratio threshold
     - token split words (match if one word close)
    """
    if not user_input or not token:
        return False
    u = user_input.lower().strip()
    t = token.lower().strip()

    # direct substring or exact
    if u == t or u in t or t in u:
        return True

    # word-level check
    for w in t.split():
        if len(w) > 2:
            ratio = difflib.SequenceMatcher(None, u, w).ratio()
            if ratio >= 0.78:
                return True

    # fuzzy overall
    ratio = difflib.SequenceMatcher(None, u, t).ratio()
    return ratio >= 0.72

# ---------------------------
# Main Game Class
# ---------------------------

class AdvancedPhishGame:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Phishing Link Detector")
        self.root.geometry("900x680")
        self.root.resizable(False, False)

        # State
        self.all_emails = random.sample(EMAILS, k=min(len(EMAILS), 6))  # pick some templates
        self.total_levels = min(5, len(self.all_emails))               # play 5 levels
        self.current_level = 0
        self.score = 0
        self.lives = 3
        self.flags_found = []
        self.results = []           # summary for each email
        self.start_time = None
        self.paused = False
        self.timer_id = None
        self.time_left = BASE_TIME

        self.init_ui()
        self.load_level(0)   # load first level (0-based index)

    # ----- UI -----
    def init_ui(self):
        # Top frame: HUD
        hud = tk.Frame(self.root, bg="#101826", padx=10, pady=8)
        hud.place(x=12, y=12, width=876, height=70)

        tk.Label(hud, text="Phishing Link Detector (Advanced)", fg="#9ef0b4", bg="#101826", font=("Helvetica", 16, "bold")).pack(anchor="w")

        # Status row
        status = tk.Frame(self.root, bg="#0b1220")
        status.place(x=12, y=90, width=876, height=40)
        self.lbl_score = tk.Label(status, text=f"Score: {self.score}", bg="#0b1220", fg="#d1f7df", font=("Helvetica", 11, "bold"))
        self.lbl_score.pack(side="left", padx=12)
        self.lbl_level = tk.Label(status, text=f"Level: {self.current_level+1}/{self.total_levels}", bg="#0b1220", fg="#d1f7df", font=("Helvetica", 11))
        self.lbl_level.pack(side="left", padx=12)
        self.lbl_lives = tk.Label(status, text=f"Lives: {self.lives}", bg="#0b1220", fg="#ffd6d6", font=("Helvetica", 11))
        self.lbl_lives.pack(side="left", padx=12)

        # Timer + progress bar
        self.lbl_timer = tk.Label(status, text=f"Time: {self.time_left}s", bg="#0b1220", fg="#ffd", font=("Helvetica", 11))
        self.lbl_timer.pack(side="right", padx=12)
        self.pb = ttk.Progressbar(status, length=200, mode="determinate")
        self.pb.place(x=640, y=8, width=220, height=24)
        self.pb['maximum'] = BASE_TIME

        # Email display (Text widget)
        frame_email = tk.LabelFrame(self.root, text="Email", padx=10, pady=8)
        frame_email.place(x=12, y=140, width=576, height=360)
        self.txt_email = tk.Text(frame_email, wrap="word", font=("Consolas", 11), bg="#f5f7fa")
        self.txt_email.pack(fill="both", expand=True)
        self.txt_email.config(state="disabled")

        # Controls (input / buttons)
        frame_controls = tk.LabelFrame(self.root, text="Identify Red Flags", padx=10, pady=8)
        frame_controls.place(x=600, y=140, width=288, height=360)

        tk.Label(frame_controls, text="Type flag (keyword / phrase):", anchor="w").pack(fill="x")
        self.entry_flag = tk.Entry(frame_controls, font=("Arial", 11))
        self.entry_flag.pack(fill="x", pady=6)
        self.entry_flag.bind("<Return>", lambda e: self.on_submit())

        btn_row = tk.Frame(frame_controls)
        btn_row.pack(fill="x", pady=6)
        self.btn_submit = tk.Button(btn_row, text="Submit", command=self.on_submit, width=10, bg="#00a86b", fg="white")
        self.btn_submit.pack(side="left", padx=4)
        self.btn_hint = tk.Button(btn_row, text="Hint (-points)", command=self.use_hint, width=10)
        self.btn_hint.pack(side="left", padx=4)

        self.lbl_msg = tk.Label(frame_controls, text="", fg="#d0e9ff", wraplength=260, anchor="w", justify="left")
        self.lbl_msg.pack(fill="x", pady=8)

        tk.Label(frame_controls, text="Found Flags:", anchor="w").pack(fill="x")
        self.frame_chips = tk.Frame(frame_controls)
        self.frame_chips.pack(fill="both", expand=True, pady=4)

        nav_row = tk.Frame(self.root)
        nav_row.place(x=12, y=520, width=876, height=58)
        self.btn_next = tk.Button(nav_row, text="Next Email ➜", state="disabled", command=self.next_level, bg="#0b7bd6", fg="white", width=12)
        self.btn_next.pack(side="right", padx=8)
        self.btn_pause = tk.Button(nav_row, text="Pause", command=self.toggle_pause, width=8)
        self.btn_pause.pack(side="right", padx=6)
        self.btn_restart = tk.Button(nav_row, text="Restart", command=self.restart_game, width=8)
        self.btn_restart.pack(side="right", padx=6)

        # Bottom: small help and leaderboard
        frame_bottom = tk.LabelFrame(self.root, text="Help & Leaderboard", padx=10, pady=8)
        frame_bottom.place(x=12, y=590, width=876, height=80)
        help_text = ("Tips: type tokens such as 'http', 'suspension', 'password', 'credit card', "
                     "'.exe', 'expire', 'urgent', 'reply with', 'paypal'")
        tk.Label(frame_bottom, text=help_text, anchor="w").pack(fill="x")
        self.leader_listbox = tk.Listbox(frame_bottom, height=2)
        self.leader_listbox.pack(side="right", padx=10)
        self.update_leaderboard_ui()

    # ----- game flow -----
    def load_level(self, level_index):
        # clamp
        self.current_level = level_index
        if level_index >= self.total_levels:
            self.finish_game()
            return

        email_obj = self.all_emails[level_index]
        # display email
        self.txt_email.config(state="normal")
        self.txt_email.delete("1.0", "end")
        self.txt_email.insert("1.0", f"Subject: {email_obj.get('title','')}\n\n{email_obj['text']}")
        self.txt_email.tag_remove("highlight", "1.0", "end")
        self.txt_email.tag_config("highlight", background="#ffd6d6")
        self.txt_email.config(state="disabled")

        # reset level state
        self.flags_found = []
        self.lbl_level.config(text=f"Level: {self.current_level+1}/{self.total_levels}")
        self.lbl_msg.config(text="")
        self.btn_next.config(state="disabled")
        for widget in self.frame_chips.winfo_children():
            widget.destroy()

        # time scales down slightly with level (increasing difficulty)
        self.time_left = max(10, BASE_TIME - (self.current_level * 6))
        self.pb['maximum'] = max(10, BASE_TIME - (self.current_level * 6))
        self.pb['value'] = self.time_left
        self.update_timer_labels()

        self.start_time = time.time()
        self.start_timer()

    def on_submit(self):
        if self.paused:
            return
        user_text = self.entry_flag.get().strip()
        self.entry_flag.delete(0, "end")
        if not user_text:
            return

        email_obj = self.all_emails[self.current_level]
        matched_flag = None
        # check against all flags (fuzzy tolerant)
        for f in email_obj['flags']:
            if f in self.flags_found:
                continue
            if fuzzy_match(user_text, f):
                matched_flag = f
                break

        if matched_flag:
            # mark found
            self.flags_found.append(matched_flag)
            self.show_found_chip(matched_flag)
            self.highlight_in_text(matched_flag)
            self.lbl_msg.config(text=f"✅ Matched flag: {matched_flag}", fg="#9ef0b4")
            # award points: base 10 + small bonus for speed
            elapsed = time.time() - self.start_time
            speed_bonus = max(0, int((self.pb['maximum'] - elapsed) // 3))
            gained = 10 + speed_bonus
            self.score += gained
            self.lbl_score.config(text=f"Score: {self.score}")
            # enable next if at least one found
            if len(self.flags_found) >= 1:
                self.btn_next.config(state="normal")
            # if found all flags -> award perfect bonus and enable next
            if len(self.flags_found) == len(email_obj['flags']):
                self.score += BONUS_PERFECT
                self.lbl_score.config(text=f"Score: {self.score}")
                self.lbl_msg.config(text=f"🟢 All flags found! +{BONUS_PERFECT} bonus", fg="#9ef0b4")
                self.stop_timer()
                self.btn_next.config(state="normal")
        else:
            # wrong guess: small penalty
            self.score = max(0, self.score - 3)
            self.lbl_score.config(text=f"Score: {self.score}")
            self.lbl_msg.config(text=f"❌ Not recognized as a red flag (try synonyms)", fg="#ff9b9b")

    def show_found_chip(self, text):
        chip = tk.Label(self.frame_chips, text=text, bg="#0f2b26", fg="#dff8ea", padx=6, pady=3, bd=0, relief="ridge")
        chip.pack(side="left", padx=4, pady=4)

    def highlight_in_text(self, token):
        # find first occurrence and tag it
        self.txt_email.config(state="normal")
        content = self.txt_email.get("1.0", "end-1c")
        # case-insensitive search
        idx = content.lower().find(token.lower())
        if idx >= 0:
            start = f"1.0 + {idx} chars"
            end = f"{start} + {len(token)} chars"
            self.txt_email.tag_add("highlight", start, end)
        self.txt_email.config(state="disabled")

    # ----- timer management -----
    def start_timer(self):
        self.stop_timer()
        self._tick()

    def _tick(self):
        if self.paused:
            return
        self.update_timer_labels()
        if self.time_left <= 0:
            self.on_time_up()
            return
        # schedule next tick
        self.time_left -= 1
        self.pb['value'] = max(0, self.time_left)
        self.timer_id = self.root.after(1000, self._tick)

    def stop_timer(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

    def update_timer_labels(self):
        self.lbl_timer.config(text=f"Time: {self.time_left}s")
        self.pb['value'] = max(0, self.time_left)

    def on_time_up(self):
        # record missed flags and penalize a life
        self.lbl_msg.config(text="⏱ Time's up for this email!", fg="#ff9b9b")
        self.lives -= 1
        self.lbl_lives.config(text=f"Lives: {self.lives}")
        # record result with missed flags
        self.save_result_and_continue(skipped=True)

    # ----- hint / skip / next -----
    def use_hint(self):
        if self.paused:
            return
        email_obj = self.all_emails[self.current_level]
        remaining = [f for f in email_obj['flags'] if f not in self.flags_found]
        if not remaining:
            self.lbl_msg.config(text="No hints needed — all flags found.", fg="#9ef0b4")
            return
        # cost increases with level
        cost = min(20, HINT_COST_BASE + self.current_level * 3)
        self.score = max(0, self.score - cost)
        self.lbl_score.config(text=f"Score: {self.score}")
        hint_token = random.choice(remaining)
        self.highlight_in_text(hint_token)
        self.show_found_chip("(HINT: "+hint_token+")")
        self.lbl_msg.config(text=f"Hint shown: {hint_token} (-{cost} pts)", fg="#ffd78f")
        # mark hint as "found" visually but do NOT count as found; user still needs to type to get points
        # allow next if at least one real found exists
        if len(self.flags_found) >= 1:
            self.btn_next.config(state="normal")

    def next_level(self):
        if self.paused:
            return
        self.save_result_and_continue(skipped=False)

    def save_result_and_continue(self, skipped=False):
        # Save found vs missed for current email
        current = self.all_emails[self.current_level]
        missed = [f for f in current['flags'] if f not in self.flags_found]
        self.results.append({
            "title": current.get("title",""),
            "text": current["text"],
            "found": self.flags_found.copy(),
            "missed": missed,
            "skipped": skipped
        })
        # proceed
        self.stop_timer()
        if self.lives <= 0:
            self.finish_game()
            return
        if self.current_level + 1 >= self.total_levels:
            self.finish_game()
            return
        self.current_level += 1
        self.load_level(self.current_level)

    # ----- pause / resume / restart -----
    def toggle_pause(self):
        if self.paused:
            self.paused = False
            self.btn_pause.config(text="Pause")
            self.start_timer()
            self.lbl_msg.config(text="Resumed.", fg="#d1f7df")
        else:
            self.paused = True
            self.stop_timer()
            self.btn_pause.config(text="Resume")
            self.lbl_msg.config(text="Paused.", fg="#ffd78f")

    def restart_game(self):
        if not messagebox.askyesno("Restart", "Are you sure you want to restart the game?"):
            return
        # reset
        self.score = 0; self.lives = 3; self.current_level = 0; self.results = []
        random.shuffle(self.all_emails)
        self.lbl_score.config(text=f"Score: {self.score}")
        self.lbl_lives.config(text=f"Lives: {self.lives}")
        self.load_level(0)

    # ----- finishing & leaderboard -----
    def finish_game(self):
        # stop timer & show summary UI dialog
        self.stop_timer()
        summary_lines = [f"Final Score: {self.score}\n"]
        for i, r in enumerate(self.results, 1):
            summary_lines.append(f"Email {i}: {r['title']}")
            summary_lines.append(f"Found: {', '.join(r['found']) if r['found'] else 'None'}")
            summary_lines.append(f"Missed: {', '.join(r['missed']) if r['missed'] else 'None'}")
            summary_lines.append("")
        summary_text = "\n".join(summary_lines)

        # show big summary window
        SummaryWindow(self.root, summary_text, self.score, self.save_score_and_exit)

    def save_score_and_exit(self, name):
        # load leaderboard, insert, save
        if not name:
            name = "ANON"
        board = load_leaderboard()
        board.append({"name": name[:3].upper(), "score": self.score, "time": time.time()})
        board.sort(key=lambda x: x["score"], reverse=True)
        board = board[:MAX_LEADERS]
        save_leaderboard(board)
        self.update_leaderboard_ui()
        messagebox.showinfo("Saved", f"Score saved for {name[:3].upper()}. Thanks for playing!")
        self.root.destroy()

    def update_leaderboard_ui(self):
        board = load_leaderboard()
        self.leader_listbox.delete(0, "end")
        if not board:
            self.leader_listbox.insert("end", "No scores yet")
        else:
            for item in board[:5]:
                self.leader_listbox.insert("end", f"{item['name']} - {item['score']}")

# ---------------------------
# Summary & Save prompt window
# ---------------------------

class SummaryWindow(tk.Toplevel):
    def __init__(self, parent, summary_text, final_score, save_callback):
        super().__init__(parent)
        self.title("Game Summary")
        self.geometry("640x480")
        self.save_callback = save_callback

        lbl = tk.Label(self, text="Game Summary", font=("Helvetica", 14, "bold"))
        lbl.pack(pady=8)

        txt = tk.Text(self, wrap="word", height=20, width=72)
        txt.pack(padx=10, pady=6)
        txt.insert("1.0", summary_text)
        txt.config(state="disabled")

        bottom = tk.Frame(self)
        bottom.pack(pady=6)
        tk.Label(bottom, text=f"Final Score: {final_score}", font=("Helvetica", 12, "bold")).pack(side="left", padx=8)

        tk.Button(bottom, text="Save Score", command=self.on_save).pack(side="left", padx=6)
        tk.Button(bottom, text="Close (Quit)", command=self.destroy_and_quit).pack(side="left", padx=6)

    def on_save(self):
        name = simpledialog.askstring("Save Score", "Enter your initials (max 3 chars):", parent=self)
        if name:
            self.save_callback(name[:3].upper())
            self.destroy()

    def destroy_and_quit(self):
        self.destroy()
        # if user closes summary without saving, just quit main app
        # do nothing else; caller will decide

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = AdvancedPhishGame(root)
    root.mainloop()
