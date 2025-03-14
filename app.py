# SCRIPT BY LUCAS LENAERTS

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import filedialog, messagebox
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# --- Paramètres et URL ---
BASE_URL = "https://appsemflo.be"
LOGIN_URL = BASE_URL + "/login"
COURSES_URL = BASE_URL + "/carnet-de-notes"

session = None

# Fonctions de connexion et de scraping
def get_csrf_token(sess):
    """Récupère le token CSRF depuis la page de connexion."""
    try:
        response = sess.get(LOGIN_URL)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            token_tag = soup.find("input", {"name": "_csrf_token"})
            if token_tag:
                return token_tag.get("value")
    except Exception as e:
        print("Erreur lors de la récupération du CSRF token:", e)
    return None

def login_request(username, password):
    """Tente de se connecter et retourne la session active si la connexion réussit."""
    s = requests.Session()
    csrf_token = get_csrf_token(s)
    if not csrf_token:
        return None
    data = {
        "email": username,
        "password": password,
        "_csrf_token": csrf_token,
        "_remember_me": "on"
    }
    response = s.post(LOGIN_URL, data=data)
    if response.status_code == 200 and "Se déconnecter" in response.text:
        return s
    return None

def fetch_courses():
    """Télécharge la page contenant la liste des cours."""
    global session
    if session is None:
        return None
    response = session.get(COURSES_URL)
    if response.status_code == 200:
        return response.text
    return None

def parse_courses(html):
    """
    Extrait la liste des cours depuis la page HTML.
    Chaque cours est représenté par un dictionnaire contenant :
      - course : le nom du cours
      - teacher : l'enseignant
      - url : l'URL complète vers le carnet de notes (incluant la période, ex. .../p2)
    """
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    table = soup.find("table", class_="w-full text-md bg-white shadow-md rounded mb-4")
    if table:
        rows = table.find_all("tr")
        for row in rows[1:]:
            tds = row.find_all("td")
            if len(tds) >= 3:
                course_name = tds[0].get_text(strip=True)
                teacher = tds[1].get_text(strip=True)
                link_tag = tds[2].find("a")
                if link_tag and "href" in link_tag.attrs:
                    carnet_url = BASE_URL + link_tag["href"]
                    courses.append({
                        "course": course_name,
                        "teacher": teacher,
                        "url": carnet_url
                    })
    return courses

def fetch_notes(url):
    """Télécharge la page du carnet de notes pour un cours donné."""
    global session
    if session is None:
        return None
    response = session.get(url)
    if response.status_code == 200:
        return response.text
    return None

def parse_notes(html):
    """
    Extrait les notes depuis la page du carnet de notes.
    Pour chaque ligne (hors entête), on récupère :
      - title : le titre du test ou devoir
      - date : la date (convertie en objet datetime)
      - score : la note obtenue
      - max_score : la note maximale
    """
    soup = BeautifulSoup(html, "html.parser")
    notes = []
    table = soup.find("table", class_="w-full text-md bg-white shadow-md rounded mb-4")
    if table:
        rows = table.find_all("tr")
        for row in rows[1:]:
            tds = row.find_all("td")
            if len(tds) >= 4:
                title = tds[1].get_text(strip=True)
                date_str = tds[2].get_text(strip=True)
                try:
                    date_obj = datetime.strptime(date_str, "%d/%m/%Y")
                except Exception:
                    date_obj = None
                note_td_text = tds[3].get_text(" ", strip=True)
                numbers = re.findall(r'[\d\.]+', note_td_text)
                if len(numbers) >= 2:
                    try:
                        score = float(numbers[0])
                        max_score = float(numbers[1])
                    except:
                        score, max_score = None, None
                else:
                    score, max_score = None, None
                notes.append({
                    "title": title,
                    "date": date_obj,
                    "score": score,
                    "max_score": max_score
                })
    return notes

def update_period_url(url, delta):
    """
    Recherche dans l'URL le paramètre de période de la forme 'pX'
    et retourne une nouvelle URL avec X modifié par delta.
    Si aucun paramètre n'est trouvé, ajoute par défaut 'p1'.
    """
    match = re.search(r'/p(\d+)', url)
    if match:
        current = int(match.group(1))
        new_period = current + delta
        if new_period < 1:
            new_period = 1
        new_url = re.sub(r'/p\d+', f'/p{new_period}', url)
        return new_url, new_period
    else:
        return url + "/p1", 1

# Interface Graphique avec ttkbootstrap
class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="flatly")
        self.title("Carnet de Notes")
        self.geometry("1200x800")
        self.session = None
        self.courses = []
        self.selected_course = None
        self.notes = []
        self.current_period = None
        self.full_titles = {}
        self.exam_keys = {}
        self.user_email = ""
        self.ignored_exams = set()
        self.create_login_frame()
        self.load_saved_credentials()

    def load_saved_credentials(self):
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
                email = config.get("email", "")
                password = config.get("password", "")
                if email and password:
                    self.email_var.set(email)
                    self.password_var.set(password)
                    self.remember_var.set(True)
        except Exception:
            pass

    def save_credentials(self, email, password):
        try:
            with open("config.json", "w") as f:
                json.dump({"email": email, "password": password}, f)
        except Exception as e:
            print("Erreur lors de l'enregistrement des identifiants:", e)

    def load_ignored_exams(self):
        filename = f"ignored_exams_{self.user_email}.json"
        try:
            with open(filename, "r") as f:
                lst = json.load(f)
                self.ignored_exams = set(lst)
        except Exception:
            self.ignored_exams = set()

    def save_ignored_exams(self):
        filename = f"ignored_exams_{self.user_email}.json"
        try:
            with open(filename, "w") as f:
                json.dump(list(self.ignored_exams), f)
        except Exception as e:
            print("Erreur lors de la sauvegarde des interros ignorées:", e)

    def create_login_frame(self):
        self.login_frame = ttk.Frame(self, padding=20)
        self.login_frame.pack(expand=TRUE, fill=BOTH)
        title_label = ttk.Label(self.login_frame, text="Bienvenue", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=20)
        self.email_var = ttk.StringVar()
        self.password_var = ttk.StringVar()
        self.remember_var = ttk.BooleanVar()
        email_label = ttk.Label(self.login_frame, text="Email :", font=("Helvetica", 12))
        email_label.pack(pady=5)
        email_entry = ttk.Entry(self.login_frame, textvariable=self.email_var, width=30)
        email_entry.pack(pady=5)
        password_label = ttk.Label(self.login_frame, text="Mot de passe :", font=("Helvetica", 12))
        password_label.pack(pady=5)
        password_entry = ttk.Entry(self.login_frame, textvariable=self.password_var, show="*", width=30)
        password_entry.pack(pady=5)
        remember_chk = ttk.Checkbutton(self.login_frame, text="Se souvenir de moi", variable=self.remember_var)
        remember_chk.pack(pady=5)
        self.login_button = ttk.Button(self.login_frame, text="Se connecter", command=self.handle_login, bootstyle=SUCCESS)
        self.login_button.pack(pady=20)
        self.status_label = ttk.Label(self.login_frame, text="", font=("Helvetica", 10))
        self.status_label.pack(pady=5)

    def handle_login(self):
        email = self.email_var.get().strip()
        password = self.password_var.get().strip()
        if not email or not password:
            messagebox.show_error("Erreur", "Veuillez remplir tous les champs.")
            return
        self.login_button.config(state=DISABLED)
        self.status_label.config(text="Connexion en cours...")
        def login_thread():
            global session
            s = login_request(email, password)
            if s:
                session = s
                self.session = s
                self.status_label.config(text="Connexion réussie !")
                self.user_email = email
                if self.remember_var.get():
                    self.save_credentials(email, password)
                else:
                    try:
                        os.remove("config.json")
                    except Exception:
                        pass
                self.after(500, self.show_main_interface)
            else:
                self.status_label.config(text="Échec de la connexion.")
            self.login_button.config(state=NORMAL)
        threading.Thread(target=login_thread).start()

    def show_main_interface(self):
        self.login_frame.destroy()
        self.create_main_interface()
        self.load_ignored_exams()
        self.load_courses()

    def create_main_interface(self):
        header_frame = ttk.Frame(self, padding=10)
        header_frame.pack(fill=X)
        title = ttk.Label(header_frame, text="Carnet de Notes", font=("Helvetica", 20, "bold"))
        title.pack(side=LEFT, padx=5)
        logout_btn = ttk.Button(header_frame, text="Déconnexion", command=self.logout, bootstyle=DANGER)
        logout_btn.pack(side=RIGHT, padx=5)
        export_btn = ttk.Button(header_frame, text="Exporter en PDF", command=self.open_export_window, bootstyle=PRIMARY)
        export_btn.pack(side=RIGHT, padx=5)
        self.main_paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        self.main_paned.pack(expand=TRUE, fill=BOTH, padx=10, pady=10)
        self.sidebar = ttk.Frame(self.main_paned, padding=10)
        self.main_paned.add(self.sidebar, weight=1)
        sidebar_title = ttk.Label(self.sidebar, text="Liste des cours", font=("Helvetica", 16))
        sidebar_title.pack(pady=5)
        refresh_btn = ttk.Button(self.sidebar, text="Actualiser", command=self.load_courses, bootstyle=INFO)
        refresh_btn.pack(pady=5)
        self.course_tree = ttk.Treeview(self.sidebar, columns=("course", "teacher"), show="headings", selectmode="browse")
        self.course_tree.heading("course", text="Cours")
        self.course_tree.heading("teacher", text="Enseignant")
        self.course_tree.column("course", anchor="center")
        self.course_tree.column("teacher", anchor="center")
        self.course_tree.pack(expand=TRUE, fill=BOTH, pady=5)
        self.course_tree.bind("<<TreeviewSelect>>", self.on_course_select)
        self.content = ttk.Frame(self.main_paned, padding=10)
        self.main_paned.add(self.content, weight=3)
        top_content = ttk.Frame(self.content)
        top_content.pack(fill=X)
        self.avg_label = ttk.Label(top_content, text="Moyenne actuelle : -", font=("Helvetica", 14))
        self.avg_label.pack(side=LEFT, padx=5)
        period_frame = ttk.Frame(top_content)
        period_frame.pack(side=RIGHT, padx=5)
        prev_btn = ttk.Button(period_frame, text="Période précédente", command=lambda: self.change_period(-1), bootstyle=SECONDARY)
        prev_btn.pack(side=LEFT, padx=2)
        self.period_label = ttk.Label(period_frame, text="Période : -", font=("Helvetica", 14))
        self.period_label.pack(side=LEFT, padx=2)
        next_btn = ttk.Button(period_frame, text="Période suivante", command=lambda: self.change_period(1), bootstyle=SECONDARY)
        next_btn.pack(side=LEFT, padx=2)
        total_btn = ttk.Button(period_frame, text="Total", command=self.load_total_notes, bootstyle=SECONDARY)
        total_btn.pack(side=LEFT, padx=2)
        self.note_tree = ttk.Treeview(self.content, columns=("title", "date", "note", "percentage"), show="headings")
        for col, text in zip(("title", "date", "note", "percentage"), ("Titre", "Date", "Note", "Pourcentage")):
            self.note_tree.heading(col, text=text)
            self.note_tree.column(col, anchor="center")
        self.note_tree.pack(expand=TRUE, fill=BOTH, pady=10)
        self.note_tree.tag_configure("low", foreground="red")
        self.note_tree.tag_configure("high", foreground="green")
        self.note_tree.tag_configure("ignored", foreground="gray", font=("Helvetica", 10, "italic"))
        self.note_tree.bind("<Button-3>", self.on_note_tree_right_click)
        self.note_tree.bind("<Motion>", self.on_note_tree_motion)
        self.note_tree.bind("<Leave>", self.on_note_tree_leave)
        self.full_titles = {}
        self.exam_keys = {}
        self.chart_frame = ttk.Frame(self.content)
        self.chart_frame.pack(expand=TRUE, fill=BOTH, pady=5)

    def logout(self):
        self.session = None
        self.courses = []
        self.selected_course = None
        self.notes = []
        for widget in self.winfo_children():
            widget.destroy()
        self.create_login_frame()
        self.load_saved_credentials()

    def load_courses(self):
        if not self.session:
            messagebox.show_error("Erreur", "Connectez-vous d'abord.")
            return
        def thread_load():
            html = fetch_courses()
            if html:
                self.courses = parse_courses(html)
                self.course_tree.delete(*self.course_tree.get_children())
                for course in self.courses:
                    self.course_tree.insert("", "end", values=(course["course"], course["teacher"]), tags=(course["url"],))
            else:
                messagebox.show_error("Erreur", "Impossible de charger les cours.")
        threading.Thread(target=thread_load).start()

    def on_course_select(self, event):
        selected = self.course_tree.focus()
        if selected:
            url = self.course_tree.item(selected, "tags")[0]
            for course in self.courses:
                if course["url"] == url:
                    self.selected_course = course
                    break
            period = self.extract_period(self.selected_course["url"])
            self.current_period = period
            self.period_label.config(text=f"Période : {period}")
            self.load_notes()

    def extract_period(self, url):
        match = re.search(r'/p(\d+)', url)
        if match:
            return int(match.group(1))
        return 1

    def change_period(self, delta):
        if not self.selected_course:
            messagebox.show_error("Erreur", "Sélectionnez un cours dans la liste.")
            return
        new_url, new_period = update_period_url(self.selected_course["url"], delta)
        self.selected_course["url"] = new_url
        self.current_period = new_period
        self.period_label.config(text=f"Période : {new_period}")
        self.load_notes()

    def load_total_notes(self):
        if not self.selected_course:
            messagebox.show_error("Erreur", "Sélectionnez un cours dans la liste.")
            return
        base_url = re.sub(r'/p\d+', '', self.selected_course["url"])
        urls = [f"{base_url}/p{i}" for i in [1, 2, 3]]
        combined_notes = []
        def thread_load_total():
            for url in urls:
                html = fetch_notes(url)
                if html:
                    combined_notes.extend(parse_notes(html))
            self.after(0, lambda: self.handle_loaded_notes(combined_notes))
            self.after(0, lambda: self.period_label.config(text="Total"))
        threading.Thread(target=thread_load_total).start()

    def load_notes(self):
        if not self.selected_course:
            messagebox.show_error("Erreur", "Sélectionnez un cours dans la liste.")
            return
        url = self.selected_course["url"]
        def thread_load_notes():
            html = fetch_notes(url)
            if html:
                parsed_notes = parse_notes(html)
                self.after(0, lambda: self.handle_loaded_notes(parsed_notes))
            else:
                self.after(0, lambda: messagebox.show_error("Erreur", "Impossible de charger le carnet de notes."))
        threading.Thread(target=thread_load_notes).start()

    def handle_loaded_notes(self, notes):
        self.notes = notes
        self.update_notes_tree()
        self.plot_chart()

    def update_notes_tree(self):
        self.note_tree.delete(*self.note_tree.get_children())
        self.full_titles = {}
        self.exam_keys = {}
        total = 0
        cnt = 0
        for note in self.notes:
            date_str = note["date"].strftime("%d/%m/%Y") if note["date"] else ""
            if note["score"] is not None and note["max_score"] is not None:
                note_str = f"{note['score']}/{note['max_score']}"
                val = note["score"] / note["max_score"] * 100
                perc = f"{val:.1f}%"
            else:
                note_str = ""
                perc = ""
                val = None
            full_title = note["title"]
            disp_title = full_title if len(full_title) <= 30 else full_title[:30] + "..."
            exam_key = f"{self.selected_course['url']}_{date_str}_{full_title}"
            tag = ""
            if exam_key in self.ignored_exams:
                tag = "ignored"
            else:
                if val is not None:
                    if val < 50:
                        tag = "low"
                    elif val >= 80:
                        tag = "high"
                    total += val
                    cnt += 1
            item = self.note_tree.insert("", "end", values=(disp_title, date_str, note_str, perc), tags=(tag,))
            self.exam_keys[item] = exam_key
            if len(full_title) > 30:
                self.full_titles[item] = full_title
        if cnt > 0:
            avg = total / cnt
            col = "red" if avg < 50 else "green" if avg >= 80 else "black"
            self.avg_label.config(text=f"Moyenne actuelle : {avg:.1f}%", foreground=col)
        else:
            self.avg_label.config(text="Moyenne actuelle : -", foreground="black")

    def on_note_tree_motion(self, event):
        region = self.note_tree.identify("region", event.x, event.y)
        if region == "cell":
            col = self.note_tree.identify_column(event.x)
            if col == "#1":
                item = self.note_tree.identify_row(event.y)
                if item in self.full_titles:
                    text = self.full_titles[item]
                    self.show_tooltip(event, text)
                else:
                    self.hide_tooltip()
            else:
                self.hide_tooltip()
        else:
            self.hide_tooltip()

    def on_note_tree_leave(self, event):
        self.hide_tooltip()

    def show_tooltip(self, event, text):
        if not hasattr(self, "tooltip"):
            self.tooltip = tk.Toplevel(self.note_tree)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip_label = tk.Label(self.tooltip, text=text, background="#ffffe0",
                                          relief="solid", borderwidth=1, font=("Helvetica", 8))
            self.tooltip_label.pack()
        else:
            self.tooltip_label.config(text=text)
        x = event.x_root + 20
        y = event.y_root + 10
        self.tooltip.wm_geometry(f"+{x}+{y}")
        self.tooltip.deiconify()

    def hide_tooltip(self):
        if hasattr(self, "tooltip"):
            self.tooltip.withdraw()

    def on_note_tree_right_click(self, event):
        item = self.note_tree.identify_row(event.y)
        if not item:
            return
        exam_key = self.exam_keys.get(item)
        if not exam_key:
            return
        menu = tk.Menu(self, tearoff=0)
        if exam_key in self.ignored_exams:
            menu.add_command(label="Inclure cette interro", command=lambda: self.toggle_ignore_exam(item, exam_key))
        else:
            menu.add_command(label="Ignorer cette interro", command=lambda: self.toggle_ignore_exam(item, exam_key))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def toggle_ignore_exam(self, item, exam_key):
        if exam_key in self.ignored_exams:
            self.ignored_exams.remove(exam_key)
        else:
            self.ignored_exams.add(exam_key)
        self.save_ignored_exams()
        self.update_notes_tree()
        self.plot_chart()

    def plot_chart(self):
        for widget in self.chart_frame.winfo_children():
            widget.destroy()
        valid_notes = [n for n in self.notes if n["date"] and n["score"] is not None and n["max_score"] and
                       f"{self.selected_course['url']}_{n['date'].strftime('%d/%m/%Y')}_{n['title']}" not in self.ignored_exams]
        if not valid_notes:
            lbl = ttk.Label(self.chart_frame, text="Aucune note trouvée pour cette période.", font=("Helvetica", 12))
            lbl.pack(pady=20)
            return
        sorted_notes = sorted(valid_notes, key=lambda n: n["date"])
        dates = [n["date"] for n in sorted_notes]
        percentages = [n["score"] / n["max_score"] * 100 for n in sorted_notes]
        cum_avg = []
        running = 0
        for i, p in enumerate(percentages):
            running += p
            cum_avg.append(running / (i + 1))
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.plot(dates, percentages, marker='o', linestyle='-', label="Note individuelle")
        ax.plot(dates, cum_avg, marker='', linestyle='--', color='red', label="Moyenne cumulée")
        ax.set_title("Évolution des notes")
        ax.set_xlabel("Date")
        ax.set_ylabel("Pourcentage")
        ax.set_ylim(0, 110)
        ax.legend()
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.autofmt_xdate()
        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(expand=TRUE, fill=BOTH)

    # Fonctionnalité d'export PDF
    def open_export_window(self):
        export_window = ttk.Toplevel(self)
        export_window.title("Exporter le rapport PDF")
        export_window.geometry("400x400")
        
        courses_frame = ttk.Frame(export_window, padding=10)
        courses_frame.pack(fill="both", expand=True)
        ttk.Label(courses_frame, text="Sélectionnez les cours à inclure :", font=("Helvetica", 12, "bold")).pack(anchor="w")
        
        self.export_course_vars = {}
        for course in self.courses:
            var = tk.BooleanVar(value=True)
            chk = ttk.Checkbutton(courses_frame, text=f"{course['course']} - {course['teacher']}", variable=var)
            chk.pack(anchor="w")
            self.export_course_vars[course["course"]] = (var, course)
        
        period_frame = ttk.Frame(export_window, padding=10)
        period_frame.pack(fill="x")
        ttk.Label(period_frame, text="Sélectionnez la période :", font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.period_export_var = ttk.StringVar(value="Total")
        period_options = ["Période 1", "Période 2", "Période 3", "Total"]
        period_dropdown = ttk.Combobox(period_frame, textvariable=self.period_export_var, values=period_options, state="readonly")
        period_dropdown.pack(fill="x", padx=5, pady=5)
        
        export_btn = ttk.Button(export_window, text="Exporter en PDF", command=lambda: self.generate_pdf_report(export_window))
        export_btn.pack(pady=20)

    def generate_pdf_report(self, window):
        selected_courses = []
        for key, (var, course) in self.export_course_vars.items():
            if var.get():
                selected_courses.append(course)
        
        period = self.period_export_var.get()
        
        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        default_filename = f"Rapport de notes_{self.user_email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        file_path = filedialog.asksaveasfilename(initialdir=downloads_folder,
                                                 initialfile=default_filename,
                                                 defaultextension=".pdf",
                                                 filetypes=[("PDF files", "*.pdf")],
                                                 title="Enregistrer le rapport PDF")
        if not file_path:
            return
        
        c = canvas.Canvas(file_path, pagesize=letter)
        width, height = letter
        y = height - 50

        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width/2, y, "Rapport de Notes")
        y -= 40
        c.setFont("Helvetica", 14)
        c.drawCentredString(width/2, y, f"Période: {period}")
        y -= 40

        for course in selected_courses:
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, y, f"Cours: {course['course']} - {course['teacher']}")
            y -= 25
            
            if period == "Total":
                base_url = re.sub(r'/p\d+', '', course["url"])
                notes = []
                for p in [1, 2, 3]:
                    url = f"{base_url}/p{p}"
                    html = fetch_notes(url)
                    if html:
                        notes.extend(parse_notes(html))
            else:
                p = int(period.split()[-1])
                new_url, _ = update_period_url(course["url"], p - self.extract_period(course["url"]))
                html = fetch_notes(new_url)
                notes = parse_notes(html) if html else []
            
            if not notes:
                c.setFont("Helvetica-Oblique", 12)
                c.drawString(70, y, "Aucune note disponible.")
                y -= 20
            else:
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, "Date")
                c.drawString(120, y, "Titre")
                c.drawString(450, y, "Note")
                y -= 20
                c.setFont("Helvetica", 12)
                total = 0
                count = 0
                graph_data = []
                for note in notes:
                    date_str = note["date"].strftime("%d/%m/%Y") if note["date"] else ""
                    title = note["title"] if len(note["title"]) <= 50 else note["title"][:50] + "..."
                    note_str = f"{note['score']}/{note['max_score']}" if note["score"] is not None and note["max_score"] is not None else ""
                    c.drawString(50, y, date_str)
                    c.drawString(120, y, title)
                    c.drawString(450, y, note_str)
                    y -= 20
                    if note["score"] is not None and note["max_score"] is not None:
                        val = note["score"] / note["max_score"] * 100
                        total += val
                        count += 1
                        graph_data.append((note["date"], val))
                    if y < 100:
                        c.showPage()
                        y = height - 50
                if count > 0:
                    avg = total / count
                    c.setFont("Helvetica-Bold", 12)
                    c.drawString(50, y, f"Moyenne: {avg:.1f}%")
                    y -= 30
                if graph_data:
                    graph_data.sort(key=lambda x: x[0])
                    dates, values = zip(*graph_data)
                    cum_avg = []
                    running = 0
                    for i, v in enumerate(values):
                        running += v
                        cum_avg.append(running / (i + 1))
                    fig, ax = plt.subplots(figsize=(5, 3))
                    ax.plot(dates, values, marker='o', linestyle='-', label="Note individuelle")
                    ax.plot(dates, cum_avg, marker='', linestyle='--', color='red', label="Moyenne cumulée")
                    ax.set_title("Évolution des notes")
                    ax.set_xlabel("Date")
                    ax.set_ylabel("Pourcentage")
                    ax.set_ylim(0, 110)
                    ax.legend()
                    ax.grid(True, linestyle="--", alpha=0.5)
                    fig.autofmt_xdate()
                    temp_img = "temp_chart.png"
                    fig.savefig(temp_img, dpi=100)
                    plt.close(fig)
                    c.drawImage(temp_img, 50, y-200, width=500, height=200)
                    y -= 220
                    os.remove(temp_img)
            y -= 30
            if y < 100:
                c.showPage()
                y = height - 50
        c.save()
        messagebox.showinfo("Export PDF", f"Le rapport a été exporté sous le nom :\n{os.path.basename(file_path)}")
        window.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
