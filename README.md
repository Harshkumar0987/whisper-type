# Whisper Dictation Tool

Local speech-to-text dictation for Windows. Runs fully offline on your NVIDIA GPU with OpenAI's Whisper large-v3, delivering an excellent balance of speed and accuracy for English, German, and 90+ other languages.

## Features

- **Hotkey dictation:** Press `CTRL+ALT+D`, speak, press again, text gets pasted into the active window
- **Offline & private:** Everything runs locally on your GPU, no audio ever leaves your machine
- **Fast & accurate:** CUDA float16 with beam search delivers high-quality transcriptions in under a second for short dictations
- **Multi-language:** Works with English, German, and all other Whisper-supported languages
- **Spoken punctuation:** Say "colon", "question mark" etc. and get the actual character (configurable, German words by default)
- **Hallucination filter:** Known Whisper phantom outputs (e.g. "subtitles by ZDF") are detected and discarded
- **System tray:** Runs quietly in the background with a color-coded status icon
- **Recording overlay:** Pulsing red bar + microphone icon across all monitors while recording
- **Audio feedback:** Beep tones on start/stop
- **History log:** All transcriptions are saved with timestamps
- **Autostart:** Launches automatically on Windows login

## Installation

### Prerequisites

- Windows 10/11
- Python 3.12+
- NVIDIA GPU with CUDA support (tested on RTX 4060)
- Up-to-date NVIDIA driver

### Setup

```
git clone https://github.com/dfrfrfr/whisper-diktiertool.git
cd whisper-diktiertool
install.bat
```

The installer will:
1. Check for Python, pip, and NVIDIA GPU
2. Install all Python packages
3. Create an autostart shortcut
4. Download the Whisper model (~3 GB, one-time)
5. Start the dictation tool

## Usage

| Action | Shortcut |
|--------|----------|
| Start/stop recording | `CTRL+ALT+D` |
| Restart (if hook is lost) | `CTRL+ALT+W` |

**Tray icon colors:**

| Color | Status |
|-------|--------|
| Gray | Model loading |
| Green | Ready |
| Red | Recording |

Right-click the tray icon for restart or quit.

### Tip: Mouse shortcut

With Razer Synapse (or similar software) you can map `CTRL+ALT+D` to a mouse button, e.g. Hypershift + scroll wheel click. Dictate without touching the keyboard.

## Spoken Punctuation

Say the word, the tool inserts the character. The default mapping uses German words but can be customized in the `SPOKEN_PUNCTUATION` dictionary at the top of `whisper-dictate.py`.

| Spoken word | Result |
|-------------|--------|
| Doppelpunkt | `: ` |
| Semikolon | `; ` |
| Ausrufezeichen | `!` |
| Fragezeichen | `?` |
| Gedankenstrich | ` - ` |
| Schrägstrich / Slash | `/` |
| Anführungszeichen | `"` |

## Configuration

All settings are defined as variables at the top of `whisper-dictate.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_SIZE` | Whisper model | `large-v3` |
| `INITIAL_PROMPT` | Domain-specific terms for better recognition | Comma-separated list |
| `SPOKEN_PUNCTUATION` | Word-to-character mapping (regex) | See table above |
| `NO_SPEECH_THRESHOLD` | Silence threshold (higher = stricter) | `0.7` |
| `SHORT_TEXT_MAX_WORDS` | Remove trailing period for <= N words | `3` |
| `DEBUG_TRANSCRIPTION` | Write segment details to history log | `True` |

To switch the language, change the `language="de"` parameter in the `model.transcribe()` call to your language code (e.g. `"en"` for English).

## Speed & Accuracy

This tool uses Whisper `large-v3` with `float16` precision and `beam_size=5`, which hits a sweet spot between transcription quality and speed. The result is near-perfect accuracy for both English and German (including dialects and background music), while keeping latency low enough for real-time dictation.

Benchmarks on RTX 4060:

| Scenario | Audio duration | Transcription time |
|----------|----------------|-------------------|
| Short dictation (1-3 words) | 2-4s | ~0.5s |
| Medium dictation (1-2 sentences) | 4-10s | ~1s |
| Long dictation (6 sentences) | ~55s | ~5s |

If you prefer faster transcriptions over maximum accuracy, switch to `large-v3-turbo` with `beam_size=3` (~3-5x faster).

## Platform Compatibility

| Platform | Status | Reason |
|----------|--------|--------|
| Windows 10/11 + NVIDIA GPU | Fully supported | Developed and tested |
| Linux + NVIDIA GPU | Not compatible | Uses Win32 APIs (kernel32, user32, winsound) |
| macOS (Intel/Apple Silicon) | Not compatible | No CUDA support, no Win32 APIs |

The Whisper engine itself (faster-whisper) runs cross-platform, but the entire integration layer (global hotkey, clipboard, overlay, system tray, audio feedback) is built on Windows APIs. Porting would require replacing these components.

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 | Windows 11 |
| GPU | NVIDIA with CUDA | RTX 3060+ |
| VRAM | 4 GB | 8 GB |
| Python | 3.12+ | 3.12+ |
| RAM | 8 GB | 16 GB |

## Author

Built by Daniel Gächter.

Check out my other projects:
- **[SEO Agent](https://seo-agent.ch)** - SEO services and web development in Switzerland
- **[Lotus Academy](https://nachhilfe-lotusacademy.ch)** - Tutoring school in German-speaking Switzerland

## License

MIT
