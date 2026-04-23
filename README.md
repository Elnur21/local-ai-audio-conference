# AI Səs Konfransı

Azerbaijani voice-based AI assistant with a knowledge base. Speak into the mic, get a spoken response — powered by Whisper (STT), Ollama (LLM), and Edge TTS.

---

## Requirements

- Windows 10/11
- Python 3.11
- NVIDIA GPU (RTX 3050 or better, 4 GB+ VRAM)
- [ffmpeg](https://ffmpeg.org) in PATH
- [Ollama](https://ollama.com) installed and running

---

## Installation

### 1. Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install PyTorch with CUDA

```bash
pip install torch==2.11.0+cu126 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

### 4. Install ffmpeg

```bash
winget install Gyan.FFmpeg
```

Restart your terminal after installation so PATH updates take effect.

### 5. Install and set up Ollama

Download from https://ollama.com, then pull the model:

```bash
ollama pull llama3 # example llama3
```

---

## Running

Open **two terminals**:

**Terminal 1 — Ollama:**
```bash
ollama serve
```

**Terminal 2 — App:**
```bash
cd ai-assistant
.venv\Scripts\activate
uvicorn app:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

> The first launch downloads the Whisper `large-v3` model (~1.5 GB) and the sentence-transformer embedding model (~120 MB). This only happens once.

---

## Usage

### Chat (http://localhost:8000)

1. Click the **🎙️** button and speak in Azerbaijani
2. Click **⏹️** to stop recording
3. Wait a moment — the AI transcribes your speech, generates a reply, and speaks it back
4. The conversation history is kept for the entire session
5. Click **Söhbəti sil** to start a fresh conversation

### Admin Panel (http://localhost:8000/admin)

Upload documents to the knowledge base so the AI can answer questions about them.

**Supported formats:** PDF, DOCX, XLSX, XLS, PPTX, PPT, TXT

1. Drag and drop a file onto the upload zone (or click to browse)
2. The file is processed, chunked, and indexed automatically
3. To remove a document, click **Sil** next to it

Once documents are uploaded, the AI automatically retrieves relevant context from them when answering questions — no need to mention the document by name.

---

## Project Structure

```
ai-assistant/
├── app.py                  # FastAPI backend
├── requirements.txt
├── kb/
│   ├── processor.py        # Text extraction (PDF, DOCX, XLSX, PPTX, TXT)
│   ├── store.py            # ChromaDB vector store + metadata
│   ├── metadata.json       # Document index (auto-generated)
│   └── uploads/            # Original uploaded files
├── chroma_db/              # Vector embeddings (auto-generated)
└── static/
    ├── index.html          # Chat UI
    └── admin.html          # Admin panel
```

---

## Configuration

Edit the constants at the top of `app.py`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `llama3` | Ollama model to use |
| `TTS_VOICE` | `az-AZ-BabekNeural` | Edge TTS voice (`az-AZ-BanuNeural` for female) |
| `SYSTEM_PROMPT` | — | AI personality and response style |

---

## Troubleshooting

**"ffmpeg not found"**
Install ffmpeg via `winget install Gyan.FFmpeg` and restart the terminal.

**"Ollama işləmir"**
Run `ollama serve` in a separate terminal before starting the app.

**GPU not used / slow inference**
Verify CUDA is available:
```bash
.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```
Should print `True`. If not, reinstall PyTorch with the CUDA index URL above.

**Out of memory on GPU**
Switch to a smaller Whisper model in `app.py`:
```python
stt_model = WhisperModel("medium", device="cuda", compute_type="int8_float16")
```
