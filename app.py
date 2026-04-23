import os
import base64
import json
import tempfile
from pathlib import Path

import httpx
import edge_tts
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, FileResponse
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

print(f"Loading Whisper ({WHISPER_MODEL}) on {WHISPER_DEVICE.upper()} [{WHISPER_COMPUTE_TYPE}]...")
stt_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
print("Ready.")

SYSTEM_PROMPT = """\
Sən bilgili, təcrübəli bir insansan. Sualları qısa, birbaşa, canlı Azərbaycan danışıq dilində cavabla.

Heç vaxt etmə:
- "Sizin sorğularınıza cavab verməkdəyəm", "Əlbəttə!", "Buyurun!", "Sizə kömək edə bilərəm" kimi \
formulalı başlanğıclar
- Özünü AI, bot və ya köməkçi kimi təqdim etmə
- Uzun giriş cümlələri — birbaşa cavaba keç

Necə cavab ver:
- Sualın özünə düz keç, giriş yoxdur
- 1–3 cümlə, lazım gəlsə daha çox
- Yaxın, bilgili dost kimi — natural, canlı
- Bilik bazasından məlumat varsa, onu natural işlət, "sənədə görə" demə\
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


@app.post("/api/process")
async def process(
    audio:   UploadFile = File(...),
    history: str        = Form(default="[]"),
):
    suffix = Path(audio.filename).suffix if audio.filename else ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        # 1. Speech → text
        segments, _ = stt_model.transcribe(tmp_path, language="az")
        user_text   = "".join(s.text for s in segments).strip()
        if not user_text:
            return JSONResponse({"error": "Səs tanınmadı"}, status_code=400)

        # 2. Retrieve KB context
        from kb.store import search
        hits   = search(user_text, n=4)
        system = SYSTEM_PROMPT
        if hits:
            system += "\n\nKontekst:\n" + "\n\n".join(hits)

        # 3. Ollama
        messages = [{"role": "system", "content": system}]
        messages += json.loads(history)
        messages.append({"role": "user", "content": user_text})

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            ai_text = resp.json()["message"]["content"]

        # 4. Text → speech
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_a:
            tmp_a_path = tmp_a.name
        await edge_tts.Communicate(ai_text, TTS_VOICE).save(tmp_a_path)
        with open(tmp_a_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_a_path)

        return {"user_text": user_text, "ai_text": ai_text, "audio": audio_b64}

    except httpx.ConnectError:
        return JSONResponse(
            {"error": "Ollama işləmir. Terminalda 'ollama serve' əmrini işə salın."},
            status_code=503,
        )
    finally:
        os.unlink(tmp_path)
