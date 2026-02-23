# Reddit Post: r/LocalLLaMA

## Title

I turned my RTX 4060 into a system-wide dictation engine with Whisper large-v3 (open source, single Python file)

## Body

I got tired of cloud-based voice typing, so I built a local dictation tool that runs Whisper large-v3 entirely on my GPU. Press a hotkey, speak, text gets pasted into whatever text field had focus before you pressed the hotkey. Works everywhere, not just in a browser or specific app.

**Demo:** https://raw.githubusercontent.com/TryoTrix/whisper-type/master/demo.gif

**GitHub:** https://github.com/TryoTrix/whisper-type

### How it works

- Hotkey (`CTRL+ALT+D`) starts/stops recording
- Audio goes straight to a NumPy array (no WAV files, no disk I/O)
- `faster-whisper` with CTranslate2 backend runs inference on GPU
- Silero VAD filters silence before Whisper sees it
- Result gets pasted via clipboard into the active window
- Runs as a system tray icon, starts with Windows

The whole thing is one Python file (~600 lines). No server, no config files, no build step.

### Benchmarks (RTX 4060, float16, beam_size=5)

| Audio length | Transcription time | Speed |
|---|---|---|
| 2-4s (few words) | ~0.5s | 4-6x real-time |
| 4-10s (1-2 sentences) | ~1s | 5-10x real-time |
| ~55s (full paragraph) | ~5s | 11x real-time |
| 73s (long monologue) | 7.7s | 9.5x real-time |

VRAM usage: ~3 GB. Model loads in ~3-5s from cache.

### A Whisper bug that might save you time

If you're using Whisper with non-English languages: **do not trust `no_speech_prob`**. With German audio, clearly spoken sentences were getting flagged with `no_speech_prob = 0.97` and silently dropped. 8 out of 9 segments gone, even though the speech was perfectly clear.

```
SKIP (no_speech=0.97): Yeah, das sieht cool aus.
SKIP (no_speech=0.97): Die Animation beim Mikrofon klappt auch super.
```

The fix: disable `no_speech_prob` filtering entirely and use `vad_filter=True` (Silero VAD) instead. VAD works on the actual audio waveform, not on model confidence, so it works regardless of language.

### Hallucination filtering

Whisper sometimes generates phantom text when it gets ambient noise. "Thanks for watching!", "Subscribe to my channel", German subtitle credits. I keep a blocklist and filter these before pasting. Simple but necessary.

### Requirements

- Windows 10/11 (uses Win32 APIs for hotkeys, tray, overlay)
- NVIDIA GPU with CUDA (tested RTX 4060, should work RTX 3060+)
- Python 3.12+
- ~3 GB disk for the model

### Install

```bash
git clone https://github.com/TryoTrix/whisper-type.git
cd whisper-type
install.bat
```

Sets up dependencies, downloads the model, creates autostart shortcut.

### Limitations

- Windows only for now (the Whisper part is cross-platform, it's the OS integration that's Windows-specific)
- NVIDIA only (CUDA dependency)
- Not real-time streaming, you record a chunk then it transcribes
- Whisper's number formatting can be inconsistent in German ("140" → "140.000")

I've been using this daily for a few weeks and it genuinely changed how I work. Happy to answer questions about the implementation.

---

**Edit:** Uses `faster-whisper` (CTranslate2), not OpenAI's original implementation. `large-v3` model, `float16` compute type.
