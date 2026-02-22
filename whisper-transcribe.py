"""
Whisper Transkription - Audio zu Text (Deutsch)
================================================
Nutzt faster-whisper mit dem large-v3 Modell auf GPU.

Verwendung:
    python whisper-transcribe.py "pfad/zur/audiodatei.mp3"
    python whisper-transcribe.py                              (fragt nach Datei)

Unterstützte Formate: mp3, wav, m4a, flac, ogg, wma, aac, mp4, mkv, avi
"""

import sys
import os
import time
from pathlib import Path

def transcribe(audio_path: str) -> None:
    from faster_whisper import WhisperModel

    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"Fehler: Datei nicht gefunden: {audio_path}")
        sys.exit(1)

    print(f"Datei:  {audio_path.name}")
    print(f"Groesse: {audio_path.stat().st_size / (1024*1024):.1f} MB")
    print()

    # Modell laden (beim ersten Mal wird es heruntergeladen ~3GB)
    print("Lade Whisper large-v3 Modell (GPU)...")
    print("(Erster Start: Download ~3 GB, danach sofort bereit)")
    print()

    model = WhisperModel(
        "large-v3",
        device="cuda",
        compute_type="float16",  # Optimal fuer RTX 4060
    )

    print("Transkribiere...")
    start = time.time()

    segments, info = model.transcribe(
        str(audio_path),
        language="de",
        beam_size=5,
        vad_filter=True,           # Filtert Stille heraus
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )

    # Ergebnis sammeln
    full_text = []
    segments_list = []

    for segment in segments:
        segments_list.append(segment)
        full_text.append(segment.text.strip())
        # Live-Ausgabe
        mins, secs = divmod(int(segment.start), 60)
        print(f"  [{mins:02d}:{secs:02d}] {segment.text.strip()}")

    elapsed = time.time() - start
    duration_mins = info.duration / 60

    print()
    print(f"Fertig! {duration_mins:.1f} Min Audio in {elapsed:.1f} Sek transkribiert")
    print(f"Geschwindigkeit: {info.duration / elapsed:.1f}x Echtzeit")
    print()

    # Text-Datei speichern
    output_path = audio_path.with_suffix(".txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(" ".join(full_text))

    print(f"Gespeichert: {output_path}")

    # Optional: SRT-Untertitel speichern
    srt_path = audio_path.with_suffix(".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments_list, 1):
            start_h, start_r = divmod(seg.start, 3600)
            start_m, start_s = divmod(start_r, 60)
            end_h, end_r = divmod(seg.end, 3600)
            end_m, end_s = divmod(end_r, 60)
            f.write(f"{i}\n")
            f.write(f"{int(start_h):02d}:{int(start_m):02d}:{start_s:06.3f}".replace(".", ","))
            f.write(f" --> ")
            f.write(f"{int(end_h):02d}:{int(end_m):02d}:{end_s:06.3f}".replace(".", ","))
            f.write(f"\n{seg.text.strip()}\n\n")

    print(f"Untertitel: {srt_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Dateipfad als Argument
        audio_file = sys.argv[1]
    else:
        # Interaktiv nach Datei fragen
        print("=== Whisper Transkription (Deutsch) ===")
        print()
        audio_file = input("Audio-Datei (Pfad eingeben oder reinziehen): ").strip().strip('"')

    if not audio_file:
        print("Keine Datei angegeben.")
        sys.exit(1)

    transcribe(audio_file)
