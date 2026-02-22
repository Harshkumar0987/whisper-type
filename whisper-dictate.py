"""
Whisper Diktiertool - Sprechen & Text einfuegen
================================================
Druecke CTRL+ALT+D zum Starten/Stoppen der Aufnahme.
Laeuft als System Tray Icon (kein Taskleisten-Eintrag).
Nur eine Instanz laeuft gleichzeitig (Mutex-geschuetzt).

Starten:
    pythonw whisper-dictate.py
"""

import sys
import os
import ctypes
from ctypes import wintypes

# Single-Instance: Windows Mutex verhindert Doppelstart
_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "WhisperDiktiertool_Mutex")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    sys.exit(0)

# NVIDIA DLLs fuer CUDA sichtbar machen (cublas, cudnn)
_nvidia_base = os.path.join(
    os.path.dirname(sys.executable), "Lib", "site-packages", "nvidia"
)
_dll_dirs = []
for _lib in ("cublas", "cudnn"):
    _dll_dir = os.path.join(_nvidia_base, _lib, "bin")
    if os.path.isdir(_dll_dir):
        os.add_dll_directory(_dll_dir)
        _dll_dirs.append(_dll_dir)
# Auch PATH erweitern (CTranslate2 laedt DLLs ueber LoadLibrary)
if _dll_dirs:
    os.environ["PATH"] = os.pathsep.join(_dll_dirs) + os.pathsep + os.environ.get("PATH", "")

import time
import math
import re
import threading
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import subprocess
import pystray
from PIL import Image, ImageDraw
import winsound

# ============================================================
# KONFIGURATION - Hier anpassen
# ============================================================
HOTKEY = "ctrl+alt+d"
SAMPLE_RATE = 16000      # Whisper erwartet 16kHz
MODEL_SIZE = "large-v3"  # Beste Qualitaet, auch mit Hintergrundmusik
NO_SPEECH_THRESHOLD = 0.7  # Segmente mit hoeherem no_speech_prob werden verworfen
DEBUG_TRANSCRIPTION = True   # Segment-Details ins History-Log schreiben
SHORT_TEXT_MAX_WORDS = 3     # Bei <= N Woertern: trailing Punkt entfernen

# Fachbegriffe die Whisper korrekt erkennen soll (biased den Decoder, kein Performance-Impact)
INITIAL_PROMPT = "CLAUDE.md, Whisper, faster-whisper, Python, CUDA, RTX 4060, committe, pushe"

# Gesprochene Satzzeichen → echte Zeichen (Regex-Pattern, case-insensitive)
# Kommas/Leerzeichen vor und nach dem Wort werden mit-konsumiert
SPOKEN_PUNCTUATION = {
    r'[,\s]*[-–]?\s*Doppelpunkt[,\s]*': ': ',
    r'[,\s]*[-–]?\s*Semikolon[,\s]*': '; ',
    r'[,\s]*[-–]?\s*Ausrufezeichen': '!',
    r'[,\s]*[-–]?\s*Fragezeichen': '?',
    r'[,\s]*[-–]?\s*Gedankenstrich[,\s]*': ' - ',
    r'[,\s]*[-–]?\s*(?:Schrägstrich|Slash)[,\s]*': '/',
    r'[,\s]*[-–]?\s*Anführungszeichen[,\s]*': '"',
}

# Bekannte Whisper-Halluzinationen bei Stille (lowercase fuer Vergleich)
HALLUCINATION_PHRASES = {
    "untertitelung von zdf",
    "untertitel von zdf",
    "untertitelung des zdf",
    "untertitel des zdf",
    "untertitel der amara.org-community",
    "copyright wdr",
    "copyright swr",
    "vielen dank fürs zuschauen",
    "vielen dank für's zuschauen",
    "danke fürs zuschauen",
    "thanks for watching",
    "thank you for watching",
    "bis zum nächsten mal",
    "ich danke euch fürs zuschauen",
    "tschüss",
    "vielen dank.",
    "vielen dank",
    "untertitelung des zdf, 2020",
    "untertitelung des zdf 2020",
}
# ============================================================

# Win32 API fuer Fensterverwaltung
user32 = ctypes.windll.user32

# Globale Variablen
recording = False
audio_chunks = []
audio_overflow_count = 0
model = None
stream = None
target_window = None
tray_icon = None


def create_icon_idle():
    """Gruenes Icon = bereit."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill="#22c55e")
    return img


def create_icon_recording():
    """Rotes Icon = Aufnahme laeuft."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill="#ef4444")
    return img


def create_icon_loading():
    """Graues Icon = Modell wird geladen."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill="#9ca3af")
    return img


def update_tray(status_text, icon_img):
    """Tray-Icon und Tooltip aktualisieren."""
    if tray_icon:
        tray_icon.icon = icon_img
        tray_icon.title = f"Whisper Diktiertool - {status_text}"


def play_start_sound():
    """Kurzer hoher Ton = Aufnahme gestartet."""
    winsound.Beep(800, 100)


def play_stop_sound():
    """Kurzer tiefer Ton = Aufnahme gestoppt."""
    winsound.Beep(500, 100)


def filter_hallucinations(segments):
    """Whisper-Halluzinationen filtern (Stille-Phantome und bekannte Phrasen)."""
    filtered = []
    debug_lines = []
    for seg in segments:
        text = seg.text.strip()
        no_speech = getattr(seg, "no_speech_prob", 0.0)
        # Segmente mit hoher no_speech-Wahrscheinlichkeit verwerfen
        if no_speech > NO_SPEECH_THRESHOLD:
            if DEBUG_TRANSCRIPTION:
                debug_lines.append(f"  SKIP (no_speech={no_speech:.2f}): {text}")
            continue
        if not text:
            continue
        # Bekannte Halluzinationen pruefen
        text_lower = text.lower().rstrip(".!?,;:")
        if text_lower in HALLUCINATION_PHRASES:
            if DEBUG_TRANSCRIPTION:
                debug_lines.append(f"  SKIP (hallucination): {text}")
            continue
        if DEBUG_TRANSCRIPTION:
            debug_lines.append(f"  KEEP (no_speech={no_speech:.2f}): {text}")
        filtered.append(text)
    # Debug-Info ins Log schreiben
    if DEBUG_TRANSCRIPTION and debug_lines:
        append_to_history("[DEBUG] Segmente:\n" + "\n".join(debug_lines))
    return filtered


def apply_spoken_punctuation(text):
    """Gesprochene Satzzeichen durch echte Zeichen ersetzen."""
    for pattern, replacement in SPOKEN_PUNCTUATION.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r'  +', ' ', text)  # Doppelte Leerzeichen bereinigen
    return text.strip()


def remove_trailing_period(text):
    """Trailing Punkt entfernen bei kurzen Texten (1-3 Woerter)."""
    if len(text.split()) <= SHORT_TEXT_MAX_WORDS and text.endswith('.'):
        return text[:-1]
    return text


def append_to_history(text, duration=0):
    """Transkription mit Timestamp und Dauer in whisper-history.log speichern."""
    try:
        from datetime import datetime
        log_path = os.path.join(os.path.dirname(__file__), "whisper-history.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dur_str = f" ({duration:.1f}s)" if duration > 0 else ""
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}]{dur_str} {text}\n")
    except Exception:
        pass


def get_monitors():
    """Alle angeschlossenen Monitore ermitteln (Position und Groesse)."""
    monitors = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_ulong,
    )

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        rect = lprcMonitor.contents
        monitors.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    return monitors


class RecordingOverlay:
    """Roter Balken am oberen Bildschirmrand auf allen Monitoren waehrend der Aufnahme."""

    BAR_HEIGHT = 8
    MIC_SIZE = 100

    def __init__(self):
        self.root = None
        self._windows = []
        self._mic_win = None
        self._mic_photo = None
        self._visible = False

    def _create_mic_image(self):
        """Premium Mikrofon-Icon (100x100), 8x Supersampling fuer glatte Raender."""
        s = self.MIC_SIZE
        scale = 8
        hs = s * scale
        img = Image.new("RGBA", (hs, hs), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx = hs // 2

        # --- Kreis: Smooth Gradient (viele Stufen) ---
        r_outer = 384
        steps = 40
        for i in range(steps):
            t = i / (steps - 1)
            inset = int(16 + t * 176)
            r = int(205 + t * 34)
            g = int(45 + t * 23)
            b = int(45 + t * 23)
            draw.ellipse([cx - r_outer + inset, cx - r_outer + inset,
                          cx + r_outer - inset, cx + r_outer - inset],
                         fill=(r, g, b))

        # --- Glossy Highlight (obere Haelfte, subtil) ---
        highlight = Image.new("RGBA", (hs, hs), (0, 0, 0, 0))
        hdraw = ImageDraw.Draw(highlight)
        hdraw.ellipse([160, 72, hs - 160, cx + 20], fill=(255, 255, 255, 30))
        img = Image.alpha_composite(img, highlight)
        draw = ImageDraw.Draw(img)

        # --- Mikrofon ---
        w = (255, 255, 255)

        # Schatten
        sh = Image.new("RGBA", (hs, hs), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        o = 10
        sc = (120, 25, 25, 100)
        sd.rounded_rectangle([cx - 76 + o, 176 + o, cx + 76 + o, 432 + o],
                             radius=76, fill=sc)
        sd.arc([cx - 136 + o, 352 + o, cx + 136 + o, 544 + o],
               0, 180, fill=sc, width=24)
        sd.line([cx + o, 544 + o, cx + o, 600 + o], fill=sc, width=24)
        sd.rounded_rectangle([cx - 68 + o, 588 + o, cx + 68 + o, 616 + o],
                             radius=14, fill=sc)
        img = Image.alpha_composite(img, sh)
        draw = ImageDraw.Draw(img)

        # Kapsel
        draw.rounded_rectangle([cx - 76, 176, cx + 76, 432], radius=76, fill=w)
        # U-Halterung
        draw.arc([cx - 136, 352, cx + 136, 544], 0, 180, fill=w, width=24)
        # Stiel
        draw.line([cx, 544, cx, 600], fill=w, width=24)
        # Basis
        draw.rounded_rectangle([cx - 68, 588, cx + 68, 616], radius=14, fill=w)

        # --- Runterskalieren ---
        img = img.resize((s, s), Image.LANCZOS)
        # Gegen Kreisrand-Farbe (Dunkelrot) compositen statt gegen Schwarz.
        # Halbtransparente Rand-Pixel werden zu dunklem Rot statt fast-Schwarz,
        # ergibt glatten Anti-Aliased Rand trotz tkinters 1-Bit-Transparenz.
        bg = Image.new("RGBA", (s, s), (180, 40, 40, 255))
        composited = Image.alpha_composite(bg, img)
        alpha = img.split()[3]
        mask = alpha.point(lambda x: 255 if x > 10 else 0)
        rgb = Image.new("RGB", (s, s), (1, 1, 1))
        rgb.paste(composited.convert("RGB"), mask=mask)
        return rgb

    def start(self):
        """Overlay in eigenem Thread starten."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()

        monitors = get_monitors()

        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x20
        WS_EX_LAYERED = 0x80000

        for i, (left, top, right, bottom) in enumerate(monitors):
            win = tk.Toplevel(self.root)
            title = f"WhisperREC_{i}"
            win.title(title)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#ef4444")

            width = right - left
            win.geometry(f"{width}x{self.BAR_HEIGHT}+{left}+{top}")

            # Click-through: Mausklicks gehen durch den Balken
            win.update_idletasks()
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TRANSPARENT)

            win.withdraw()
            self._windows.append(win)

        # Mikrofon-Icon (roter Kreis mit weissem Mikrofon, oben links)
        from PIL import ImageTk
        mic_win = tk.Toplevel(self.root)
        mic_title = "WhisperMIC"
        mic_win.title(mic_title)
        mic_win.overrideredirect(True)
        mic_win.attributes("-topmost", True)
        trans = "#010101"
        mic_win.configure(bg=trans)
        mic_win.attributes("-transparentcolor", trans)

        primary = monitors[0] if monitors else (0, 0, 1920, 1080)
        mic_x = primary[0] + 20
        mic_y = primary[1] + self.BAR_HEIGHT + 12
        mic_win.geometry(f"{self.MIC_SIZE}x{self.MIC_SIZE}+{mic_x}+{mic_y}")

        mic_img = self._create_mic_image()
        self._mic_photo = ImageTk.PhotoImage(mic_img)
        label = tk.Label(mic_win, image=self._mic_photo, bg=trans, bd=0,
                         highlightthickness=0)
        label.pack()

        mic_win.update_idletasks()
        hwnd_mic = user32.FindWindowW(None, mic_title)
        if hwnd_mic:
            ex_style = user32.GetWindowLongW(hwnd_mic, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd_mic, GWL_EXSTYLE,
                                  ex_style | WS_EX_TRANSPARENT | WS_EX_LAYERED)

        mic_win.withdraw()
        self._mic_win = mic_win

        # Polling: recording-Status alle 100ms pruefen
        self._poll()
        self.root.mainloop()

    def _poll(self):
        """Balken und Mikrofon ein-/ausblenden basierend auf Aufnahme-Status."""
        if recording and not self._visible:
            for win in self._windows:
                win.deiconify()
            if self._mic_win:
                self._mic_win.deiconify()
            self._visible = True
            self._pulse()
        elif not recording and self._visible:
            for win in self._windows:
                win.withdraw()
            if self._mic_win:
                self._mic_win.withdraw()
            self._visible = False

        self.root.after(100, self._poll)

    def _pulse(self):
        """Sanftes Pulsieren zwischen hellem und dunklerem Rot."""
        if not self._visible:
            return
        # Sinus-Welle fuer sanfte Uebergaenge (Zyklus ~2 Sekunden)
        factor = (math.sin(time.time() * math.pi) + 1) / 2
        # Interpolieren: #b91c1c (dunkel) bis #ef4444 (hell)
        r = int(185 + factor * 54)   # 185-239
        g = int(28 + factor * 40)    # 28-68
        b = int(28 + factor * 40)    # 28-68
        color = f"#{r:02x}{g:02x}{b:02x}"
        for win in self._windows:
            win.configure(bg=color)
        self.root.after(50, self._pulse)


def load_model():
    """Whisper-Modell beim Start laden."""
    global model
    import traceback
    try:
        from faster_whisper import WhisperModel

        t0 = time.time()
        model = WhisperModel(
            MODEL_SIZE,
            device="cuda",
            compute_type="float16",
        )
        load_time = time.time() - t0
        append_to_history(f"[STARTUP] Modell geladen in {load_time:.1f}s")
        update_tray("Bereit (CTRL+ALT+D)", create_icon_idle())
    except Exception:
        # Fehler in Logdatei schreiben (pythonw hat keine Konsole)
        log_path = os.path.join(os.path.dirname(__file__), "whisper-error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        update_tray("FEHLER - siehe whisper-error.log", create_icon_loading())


def audio_callback(indata, frames, time_info, status):
    """Wird aufgerufen waehrend der Aufnahme."""
    global audio_overflow_count
    if status:
        # Input overflow = Audio-Daten gingen verloren (Buffer zu klein)
        audio_overflow_count += 1
    if recording:
        audio_chunks.append(indata.copy())


def start_recording():
    """Aufnahme starten."""
    global recording, audio_chunks, audio_overflow_count, stream, target_window
    if recording:
        return

    target_window = user32.GetForegroundWindow()

    # Sound VOR der Aufnahme (damit der Beep nicht mitaufgenommen wird)
    play_start_sound()

    audio_chunks = []
    audio_overflow_count = 0
    recording = True
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
        blocksize=1024,
        latency="high",
    )
    stream.start()

    update_tray("Aufnahme...", create_icon_recording())


def stop_recording_and_transcribe():
    """Aufnahme stoppen, transkribieren, Text einfuegen."""
    global recording, stream
    if not recording:
        return

    recording = False

    if stream:
        stream.stop()
        stream.close()
        stream = None

    # Sound NACH dem Stoppen (Aufnahme ist bereits beendet)
    play_stop_sound()

    update_tray("Transkribiere...", create_icon_loading())

    if not audio_chunks:
        update_tray("Bereit (CTRL+ALT+D)", create_icon_idle())
        return

    chunk_count = len(audio_chunks)
    audio = np.concatenate(audio_chunks, axis=0).flatten()
    duration = len(audio) / SAMPLE_RATE

    # Overflow-Warnung ins Log schreiben
    if audio_overflow_count > 0:
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(__file__), "whisper-history.log")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] ⚠ OVERFLOW: {audio_overflow_count}x Input-Overflow, "
                        f"{chunk_count} Chunks, {duration:.1f}s Audio\n")
        except Exception:
            pass

    if duration < 0.3:
        update_tray("Bereit (CTRL+ALT+D)", create_icon_idle())
        return

    try:
        t_start = time.time()
        segments, info = model.transcribe(
            audio,
            language="de",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=INITIAL_PROMPT,
        )

        # Generator komplett konsumieren (verhindert Datenverlust bei Iteration-Fehlern)
        segments_list = list(segments)
        t_transcribe = time.time() - t_start

        parts = filter_hallucinations(segments_list)
        text = " ".join(parts).strip()
        text = apply_spoken_punctuation(text)
        text = remove_trailing_period(text)

        # Performance-Log
        ratio = duration / t_transcribe if t_transcribe > 0 else 0
        append_to_history(f"[PERF] {duration:.1f}s Audio → {t_transcribe:.1f}s Transkription ({ratio:.1f}x Echtzeit)")

        if text:
            if target_window:
                user32.SetForegroundWindow(target_window)
                time.sleep(0.1)

            old_clipboard = ""
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

            pyperclip.copy(text)
            time.sleep(0.05)
            keyboard.send("ctrl+v")

            time.sleep(0.15)
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass

            append_to_history(text, duration)

    except Exception as e:
        append_to_history(f"[FEHLER] Transkription fehlgeschlagen: {e}")

    update_tray("Bereit (CTRL+ALT+D)", create_icon_idle())


def hotkey_loop():
    """Keyboard-Loop in eigenem Thread."""
    # Warte bis Modell geladen
    while model is None:
        time.sleep(0.1)

    while True:
        keyboard.wait(HOTKEY)
        if not recording:
            start_recording()
        else:
            stop_recording_and_transcribe()
        while keyboard.is_pressed(HOTKEY):
            time.sleep(0.01)


def on_restart(icon, item):
    """Neustart ueber Tray-Menue: neue Instanz starten, dann aktuelle beenden."""
    bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper-dictate.bat")
    # Detached cmd.exe wartet 2s (Mutex-Freigabe), startet dann neu
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        f'cmd.exe /c "timeout /t 2 /nobreak >nul && start "" "{bat_path}""',
        creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
        close_fds=True,
    )
    icon.stop()
    os._exit(0)


def on_quit(icon, item):
    """Beenden ueber Tray-Menue."""
    icon.stop()
    os._exit(0)


def main():
    global tray_icon

    # Tray-Icon erstellen
    menu = pystray.Menu(
        pystray.MenuItem("Neustart", on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", on_quit),
    )
    tray_icon = pystray.Icon(
        "whisper-dictate",
        create_icon_loading(),
        "Whisper Diktiertool - Lade Modell...",
        menu,
    )

    # Recording-Overlay (floating "REC" Anzeige)
    overlay = RecordingOverlay()
    overlay.start()

    # Hotkey-Loop und Modell-Laden in Hintergrund-Threads
    hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
    hotkey_thread.start()

    model_thread = threading.Thread(target=load_model, daemon=True)
    model_thread.start()

    # Tray-Icon blockiert den Hauptthread (muss so sein)
    tray_icon.run()


if __name__ == "__main__":
    main()
