import asyncio
import edge_tts

# just example text
TEXT = """Sizin borcunuz 10 manat 20 qəpikdir, tez bir zamanda ödəməlisiniz."""  # text to be converted to speech
VOICE = "az-AZ-BabekNeural"   # male — use "az-AZ-BanuNeural" for female
OUTPUT = "output.mp3"

async def main():
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(OUTPUT)
    print(f"Saved to {OUTPUT}")

asyncio.run(main())
