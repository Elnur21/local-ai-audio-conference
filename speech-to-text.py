import os
import whisper

os.environ["PATH"] += r";C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"

model = whisper.load_model("large-v3", device="cuda")

result = model.transcribe("example.ogg", language="az")

print(result["text"])