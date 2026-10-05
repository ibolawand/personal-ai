import io
import threading
from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import soundfile as sf
# Import your existing setup components
from main import Aria
import io, json, base64
import soundfile as sf
import numpy as np
import resampy   # pip install resampy   (only if sr != target)
from fastapi import WebSocket, WebSocketDisconnect

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global holder for our shared Aria instance
aria_instance: Aria = None


def generate_aria_voice_wav(text: str) -> io.BytesIO:
    """
    Leverages Aria's existing VoiceEngine pipeline (Kokoro + RVC conversion)
    to compile speech into a standard WAV byte stream for mobile playback.
    """
    global aria_instance
    wav_io = io.BytesIO()

    # Fallback default configuration if the voice engine hasn't fully booted up
    default_sr = 24000

    if not aria_instance or not aria_instance.voice:
        print("[Mobile Server] Warning: VoiceEngine uninitialized. Returning empty WAV.")
        sf.write(wav_io, [], default_sr, format='WAV', subtype='PCM_16')
        wav_io.seek(0)
        return wav_io

    try:
        audio_np, sample_rate = aria_instance.voice._synthesize(text)

        if audio_np is None:
            raise ValueError("Synthesizer pipeline returned an empty array block.")

        sf.write(wav_io, audio_np, sample_rate, format='WAV', subtype='PCM_16')
        print(f"[Mobile Server] Compiled voice response at {sample_rate}Hz.")

    except Exception as e:
        print(f"[Mobile Server] Core audio stream compilation failed: {e}")
        sf.write(wav_io, [], default_sr, format='WAV', subtype='PCM_16')

    wav_io.seek(0)
    return wav_io


@app.post("/aria/chat")
@app.get("/aria/chat")
@app.post("/chat")
@app.get("/chat")
async def mobile_chat_endpoint(
        text: str = Query(None),
        audio: UploadFile = File(None)
):
    global aria_instance
    if not aria_instance:
        return {"error": "Aria core engine is initializing."}

    user_message = ""

    if text:
        user_message = text
    elif audio:
        audio_bytes = await audio.read()
        try:
            user_message = aria_instance.stt.transcribe(audio_bytes)
        except Exception as e:
            user_message = "Audio parsing error."

    if not user_message:
        return {"error": "No message body found"}

    print(f"[Mobile Server] Hit detected! Message text: {user_message}")

    aria_text_response = aria_instance.process_text_input(user_message)
    print(f"[Mobile Server] Aria Output: {aria_text_response}")

    if aria_instance.ha:
        aria_instance.ha.notify_phone(aria_text_response, title="Aria Mobile")

    wav_audio_stream = generate_aria_voice_wav(aria_text_response)

    return StreamingResponse(wav_audio_stream, media_type="audio/wav")



WS_TARGET_SR = None  # set at startup from aria_instance.stt

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    global live_queue, WS_TARGET_SR
    await ws.accept()
    print("[Live] client connected")

    # Lazy-init target SR from STTEngine
    if WS_TARGET_SR is None:
        WS_TARGET_SR = getattr(aria_instance.stt, "sample_rate", 16000)

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            text = msg.get("text")
            if not text:
                continue

            if text == "END":
                live_queue.send_activity_end()
                continue
            if text == "CLOSE":
                live_queue.close()
                break

            try:
                obj = json.loads(text)
            except Exception:
                continue

            if obj.get("type") != "audio_wav":
                continue

            raw = base64.b64decode(obj["wav_b64"])
            audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)          # stereo → mono
            if sr != WS_TARGET_SR:
                audio = resampy.resample(audio, sr, WS_TARGET_SR)

            live_queue.send_realtime(audio.astype(np.float32))
    except WebSocketDisconnect:
        pass
    finally:
        print("[Live] client gone")

def run_fastapi():
    # Runs the web API on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    aria_instance = Aria()

    threading.Thread(target=aria_instance.run, daemon=True).start()

    run_fastapi()