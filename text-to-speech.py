import asyncio
import edge_tts

# just example text
TEXT = """Example text."""  # text to be converted to speech
VOICE = "az-AZ-BabekNeural"   # male — use "az-AZ-BanuNeural" for female
OUTPUT = "output.mp3"

async def main():
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(OUTPUT)
    print(f"Saved to {OUTPUT}")

asyncio.run(main())
