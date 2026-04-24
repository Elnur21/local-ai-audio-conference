import asyncio
import sys
import os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import base64
import json
import tempfile
import threading
from pathlib import Path

import httpx
import edge_tts
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from faster_whisper import WhisperModel

load_dotenv()

FFMPEG_PATH   = os.getenv("FFMPEG_PATH", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3")
TTS_VOICE     = os.getenv("TTS_VOICE", "az-AZ-BabekNeural")

# Auto-detect GPU; fall back to CPU gracefully
def _resolve_device():
    import torch
    pref = os.getenv("WHISPER_DEVICE", "auto").lower()
    if pref == "auto":
        return ("cuda", "int8_float16") if torch.cuda.is_available() else ("cpu", "int8")
    if pref == "cuda":
        if not torch.cuda.is_available():
            print("WARNING: CUDA not available, falling back to CPU.")
            return ("cpu", "int8")
        return ("cuda", "int8_float16")
    return ("cpu", "int8")

WHISPER_DEVICE, WHISPER_COMPUTE_TYPE = _resolve_device()

if FFMPEG_PATH:
    os.environ["PATH"] += f";{FFMPEG_PATH}"

Path("kb/uploads").mkdir(parents=True, exist_ok=True)
Path("chroma_db").mkdir(exist_ok=True)

app = FastAPI()

_stt_model = None
_stt_ready = threading.Event()
_stt_error: Exception | None = None

def _load_whisper_model():
    global _stt_model, _stt_error
    kwargs = dict(device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    print(f"Loading Whisper ({WHISPER_MODEL}) on {WHISPER_DEVICE.upper()} [{WHISPER_COMPUTE_TYPE}]...")
    try:
        try:
            _stt_model = WhisperModel(WHISPER_MODEL, local_files_only=True, **kwargs)
            print("Whisper loaded from local cache.")
        except Exception:
            print("Model not in cache — downloading from HuggingFace Hub...")
            _stt_model = WhisperModel(WHISPER_MODEL, **kwargs)
            print("Whisper download complete.")
    except Exception as e:
        _stt_error = e
        print(f"ERROR loading Whisper: {e}")
    finally:
        _stt_ready.set()

threading.Thread(target=_load_whisper_model, daemon=True).start()
print("Server ready. Whisper model loading in background...")

SYSTEM_PROMPT = """\
You are a helpful assistant. You MUST always respond in Azerbaijani (Azərbaycan dili), no matter what language the user writes in.

KNOWLEDGE BASE:
- If a "Kontekst:" section is provided, your answer must come ONLY from that context.
- Do not add outside information when context is given.
- If the context does not contain the answer, say only: "Bu barədə məlumatım yoxdur."
- If no context is provided, answer from your general knowledge in Azerbaijani.

STYLE:
- Never start with "Əlbəttə", "Buyurun", "Sizə kömək edə bilərəm" or any filler phrase.
- Never introduce yourself as an AI or assistant.
- Go straight to the answer — no preamble.
- Speak like a knowledgeable friend: natural, warm, conversational Azerbaijani.
- 1–3 sentences by default; more only when the question clearly requires it.\
"""

ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".ppt", ".txt"}


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin")
async def admin_page():
    return FileResponse("static/admin.html")


@app.get("/api/admin/documents")
async def list_docs():
    from kb.store import list_documents
    return list_documents()


@app.post("/api/admin/upload")
async def upload_doc(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return JSONResponse({"error": f"Dəstəklənməyən format: {ext}"}, status_code=400)

    save_path = Path("kb/uploads") / file.filename
    save_path.write_bytes(await file.read())

    try:
        from kb.processor import extract_text
        from kb.store import add_document
        text   = extract_text(str(save_path))
        doc_id = add_document(file.filename, text)
        return {"success": True, "doc_id": doc_id}
    except Exception as e:
        save_path.unlink(missing_ok=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/admin/documents/{doc_id}")
async def delete_doc(doc_id: str):
    from kb.store import delete_document, list_documents
    docs = list_documents()
    if doc_id not in docs:
        return JSONResponse({"error": "Tapılmadı"}, status_code=404)
    (Path("kb/uploads") / docs[doc_id]["filename"]).unlink(missing_ok=True)
    delete_document(doc_id)
    return {"success": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/chat")
async def chat_page():
    return FileResponse("static/chat.html")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_llm_tts(user_text: str, history_json: str):
    from kb.store import search
    hits   = search(user_text, n=2)
    system = SYSTEM_PROMPT
    if hits:
        system += "\n\nKontekst:\n" + "\n\n".join(hits)

    messages = [{"role": "system", "content": system}]
    messages += json.loads(history_json)
    messages.append({"role": "user", "content": user_text})

    ai_text = ""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "messages": messages, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        ai_text += token
                        yield _sse({"type": "token", "content": token})
                    if chunk.get("done"):
                        break
    except httpx.ConnectError:
        yield _sse({"type": "error", "message": "Ollama işləmir. Terminalda 'ollama serve' əmrini işə salın."})
        return
    except httpx.ReadTimeout:
        yield _sse({"type": "error", "message": "Ollama cavab vermədi (timeout). Bir az gözləyib yenidən cəhd edin."})
        return

    if not ai_text:
        yield _sse({"type": "error", "message": "Modeldən boş cavab gəldi."})
        return

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp_path = f.name
        await edge_tts.Communicate(ai_text, TTS_VOICE).save(tmp_path)
        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)
        yield _sse({"type": "done", "audio": audio_b64})
    except Exception as e:
        yield _sse({"type": "error", "message": f"TTS xətası: {e}"})


def _sse_response(gen):
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
async def chat_text(
    text:    str = Form(...),
    history: str = Form(default="[]"),
):
    user_text = text.strip()
    if not user_text:
        return JSONResponse({"error": "Mətn boşdur"}, status_code=400)
    return _sse_response(_stream_llm_tts(user_text, history))


@app.post("/api/process")
async def process(
    audio:   UploadFile = File(...),
    history: str        = Form(default="[]"),
):
    suffix = Path(audio.filename).suffix if audio.filename else ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    async def _gen():
        try:
            if not _stt_ready.is_set():
                yield _sse({"type": "error", "message": "Whisper modeli hələ yüklənir, bir az gözləyin."})
                return
            if _stt_error:
                yield _sse({"type": "error", "message": f"Whisper yüklənmədi: {_stt_error}"})
                return

            segments, _ = await asyncio.to_thread(_stt_model.transcribe, tmp_path, language="az")
            user_text   = "".join(s.text for s in segments).strip()
            if not user_text:
                yield _sse({"type": "error", "message": "Səs tanınmadı"})
                return

            yield _sse({"type": "transcribed", "user_text": user_text})
            async for event in _stream_llm_tts(user_text, history):
                yield event
        finally:
            os.unlink(tmp_path)

    return _sse_response(_gen())
