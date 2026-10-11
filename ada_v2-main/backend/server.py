import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import socketio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse, FileResponse
import asyncio
import threading
import os
import json
import mimetypes
from datetime import datetime
from pathlib import Path

# Ensure we can import backend modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import ada
from authenticator import FaceAuthenticator

# --- Frontend dist directory ---
DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
DIST_EXISTS = DIST_DIR.exists() and (DIST_DIR / "index.html").exists()

# Cache ALL static files in memory at startup for zero-latency serving
STATIC_CACHE = {}  # path -> (bytes, content_type)
INDEX_HTML = b""

if DIST_EXISTS:
    print(f"[FRONTEND] Loading dist/ into memory...")
    for f in DIST_DIR.rglob("*"):
        if f.is_file():
            rel = "/" + str(f.relative_to(DIST_DIR)).replace("\\", "/")
            ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            STATIC_CACHE[rel] = (f.read_bytes(), ct)
    INDEX_HTML = STATIC_CACHE.get("/index.html", (b"", "text/html"))[0]
    print(f"[FRONTEND] Cached {len(STATIC_CACHE)} files ({sum(len(v[0]) for v in STATIC_CACHE.values()) // 1024}KB)")
else:
    print(f"[FRONTEND] No dist/ found at {DIST_DIR} - run 'npm run build' first")

# --- Create FastAPI app ---
app = FastAPI()

@app.get("/status")
async def status():
    return {"status": "running", "service": "ZORO Backend"}

@app.middleware("http")
async def serve_spa_middleware(request: Request, call_next):
    path = request.url.path

    # Fast path: serve cached static assets immediately (most common)
    if path.startswith("/assets/") or path.endswith(".task"):
        cached = STATIC_CACHE.get(path)
        if cached:
            body, ct = cached
            return Response(content=body, media_type=ct,
                          headers={"Cache-Control": "public, max-age=31536000"})

    # Fast path: /status endpoint
    if path == "/status":
        return await call_next(request)

    # SPA fallback for everything else
    response = await call_next(request)
    if response.status_code == 404 and INDEX_HTML:
        return Response(content=INDEX_HTML, media_type="text/html")
    return response


# --- Socket.IO ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app_socketio = socketio.ASGIApp(sio, app)

import signal

# --- SHUTDOWN HANDLER ---
def signal_handler(sig, frame):
    print(f"\n[SERVER] Caught signal {sig}. Exiting gracefully...")
    if audio_loop:
        try:
            print("[SERVER] Stopping Audio Loop...")
            audio_loop.stop() 
        except:
            pass
    print("[SERVER] Force exiting...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Global state
audio_loop = None
loop_task = None
authenticator = None
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "face_auth_enabled": False,
    "tool_permissions": {
        "run_web_agent": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True
    },
    "printers": [],
    "kasa_devices": [],
    "camera_flipped": False
}

SETTINGS = DEFAULT_SETTINGS.copy()

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                         SETTINGS["tool_permissions"].update(v)
                    else:
                        SETTINGS[k] = v
            print(f"Loaded settings: {SETTINGS}")
        except Exception as e:
            print(f"Error loading settings: {e}")

def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(SETTINGS, f, indent=4)
        print("Settings saved.")
    except Exception as e:
        print(f"Error saving settings: {e}")

# Load on startup
load_settings()

authenticator = None

@app.on_event("startup")
async def startup_event():
    print(f"[SERVER DEBUG] Startup Event Triggered")
    print(f"[SERVER DEBUG] Python Version: {sys.version}")
    try:
        loop = asyncio.get_running_loop()
        print(f"[SERVER DEBUG] Running Loop: {type(loop)}")
        policy = asyncio.get_event_loop_policy()
        print(f"[SERVER DEBUG] Current Policy: {type(policy)}")
    except Exception as e:
        print(f"[SERVER DEBUG] Error checking loop: {e}")

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to ZORO Backend'}, room=sid)

    global authenticator
    
    async def on_auth_status(is_auth):
        print(f"[SERVER] Auth status change: {is_auth}")
        await sio.emit('auth_status', {'authenticated': is_auth})

    async def on_auth_frame(frame_b64):
        await sio.emit('auth_frame', {'image': frame_b64})

    if authenticator is None:
        authenticator = FaceAuthenticator(
            reference_image_path="reference.jpg",
            on_status_change=on_auth_status,
            on_frame=on_auth_frame
        )
    
    if authenticator.authenticated:
        await sio.emit('auth_status', {'authenticated': True})
    else:
        if SETTINGS.get("face_auth_enabled", False):
            await sio.emit('auth_status', {'authenticated': False})
            asyncio.create_task(authenticator.start_authentication_loop())
        else:
            print("Face Auth Disabled. Auto-authenticating.")
            await sio.emit('auth_status', {'authenticated': True})

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.event
async def start_audio(sid, data=None):
    global audio_loop, loop_task
    
    if SETTINGS.get("face_auth_enabled", False):
        if authenticator and not authenticator.authenticated:
            print("Blocked start_audio: Not authenticated.")
            await sio.emit('error', {'msg': 'Authentication Required'})
            return

    print("Starting Audio Loop...")
    
    device_index = None
    device_name = None
    if data:
        if 'device_index' in data:
            device_index = data['device_index']
        if 'device_name' in data:
            device_name = data['device_name']
            
    print(f"Using input device: Name='{device_name}', Index={device_index}")
    
    if audio_loop:
        if loop_task and (loop_task.done() or loop_task.cancelled()):
             print("Audio loop task appeared finished/cancelled. Clearing and restarting...")
             audio_loop = None
             loop_task = None
        else:
             print("Audio loop already running. Re-connecting client to session.")
             await sio.emit('status', {'msg': 'ZORO Already Running'})
             return

    def on_audio_data(data_bytes):
        # Send only amplitude chunks for visualization (downsample ~64x)
        step = max(1, len(data_bytes) // 128)
        amps = [data_bytes[i] for i in range(0, len(data_bytes), step)][:128]
        asyncio.create_task(sio.emit('audio_data', {'data': amps}))

    def on_web_data(data):
        print(f"Sending Browser data to frontend: {len(data.get('log', ''))} chars logs")
        asyncio.create_task(sio.emit('browser_frame', data))
        
    def on_transcription(data):
        asyncio.create_task(sio.emit('transcription', data))

    def on_tool_confirmation(data):
        print(f"Requesting confirmation for tool: {data.get('tool')}")
        asyncio.create_task(sio.emit('tool_confirmation_request', data))

    def on_project_update(project_name):
        print(f"Sending Project Update: {project_name}")
        asyncio.create_task(sio.emit('project_update', {'project': project_name}))

    def on_error(msg):
        print(f"Sending Error to frontend: {msg}")
        asyncio.create_task(sio.emit('error', {'msg': msg}))

    try:
        print(f"Initializing AudioLoop with device_index={device_index}")
        audio_loop = ada.AudioLoop(
            video_mode="none", 
            on_audio_data=on_audio_data,
            on_web_data=on_web_data,
            on_transcription=on_transcription,
            on_tool_confirmation=on_tool_confirmation,
            on_project_update=on_project_update,
            on_error=on_error,
            input_device_index=device_index,
            input_device_name=device_name,
        )
        print("AudioLoop initialized successfully.")

        audio_loop.update_permissions(SETTINGS["tool_permissions"])
        
        if data and data.get('muted', False):
            print("Starting with Audio Paused")
            audio_loop.set_paused(True)

        print("Creating asyncio task for AudioLoop.run()")
        loop_task = asyncio.create_task(audio_loop.run())
        
        def handle_loop_exit(task):
            try:
                task.result()
            except asyncio.CancelledError:
                print("Audio Loop Cancelled")
            except Exception as e:
                print(f"Audio Loop Crashed: {e}")
        
        loop_task.add_done_callback(handle_loop_exit)
        
        print("Emitting 'ZORO Started'")
        await sio.emit('status', {'msg': 'ZORO Started'})

    except Exception as e:
        print(f"CRITICAL ERROR STARTING ZORO: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Failed to start: {str(e)}"})
        audio_loop = None


@sio.event
async def stop_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.stop() 
        print("Stopping Audio Loop")
        audio_loop = None
        await sio.emit('status', {'msg': 'ZORO Stopped'})

@sio.event
async def pause_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(True)
        print("Pausing Audio")
        await sio.emit('status', {'msg': 'Audio Paused'})

@sio.event
async def resume_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(False)
        print("Resuming Audio")
        await sio.emit('status', {'msg': 'Audio Resumed'})

@sio.event
async def confirm_tool(sid, data):
    request_id = data.get('id')
    confirmed = data.get('confirmed', False)
    
    print(f"[SERVER DEBUG] Received confirmation response for {request_id}: {confirmed}")
    
    if audio_loop:
        audio_loop.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Audio loop not active, cannot resolve confirmation.")

@sio.event
async def shutdown(sid, data=None):
    global audio_loop, loop_task, authenticator
    
    print("[SERVER] ========================================")
    print("[SERVER] SHUTDOWN SIGNAL RECEIVED FROM FRONTEND")
    print("[SERVER] ========================================")
    
    if audio_loop:
        print("[SERVER] Stopping Audio Loop...")
        audio_loop.stop()
        audio_loop = None
    
    if loop_task and not loop_task.done():
        print("[SERVER] Cancelling loop task...")
        loop_task.cancel()
        loop_task = None
    
    if authenticator:
        print("[SERVER] Stopping Authenticator...")
        authenticator.stop()
    
    print("[SERVER] Graceful shutdown complete. Terminating process...")
    os._exit(0)

@sio.event
async def user_input(sid, data):
    text = data.get('text')
    print(f"[SERVER DEBUG] User input received: '{text}'")
    
    if not audio_loop:
        print("[SERVER DEBUG] [Error] Audio loop is None. Cannot send text.")
        await sio.emit('error', {'msg': 'Not connected to model. Press Power then unmute mic.'})
        return

    if not audio_loop.session:
        print("[SERVER DEBUG] [Error] Session is None. Cannot send text.")
        await sio.emit('error', {'msg': 'Model session not ready yet. Wait a few seconds and retry.'})
        return

    if text:
        print(f"[SERVER DEBUG] Sending message to model: '{text}'")
        
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)
            
        if audio_loop and audio_loop._latest_image_payload:
            print(f"[SERVER DEBUG] Piggybacking video frame with text input.")
            try:
                await audio_loop.session.send(input=audio_loop._latest_image_payload, end_of_turn=False)
            except Exception as e:
                print(f"[SERVER DEBUG] Failed to send piggyback frame: {e}")
                
        await audio_loop.session.send(input=text, end_of_turn=True)
        print(f"[SERVER DEBUG] Message sent to model successfully.")

@sio.event
async def video_frame(sid, data):
    image_data = data.get('image')
    if image_data and audio_loop:
        asyncio.create_task(audio_loop.send_frame(image_data))

@sio.event
async def save_memory(sid, data):
    try:
        messages = data.get('messages', [])
        if not messages:
            print("No messages to save.")
            return

        memory_dir = Path("long_term_memory")
        memory_dir.mkdir(exist_ok=True)

        provided_name = data.get('filename')
        
        if provided_name:
            if not provided_name.endswith('.txt'):
                provided_name += '.txt'
            filename = memory_dir / Path(provided_name).name 
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = memory_dir / f"memory_{timestamp}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            for msg in messages:
                sender = msg.get('sender', 'Unknown')
                text = msg.get('text', '')
        print(f"Conversation saved to {filename}")
        await sio.emit('status', {'msg': 'Memory Saved Successfully'})

    except Exception as e:
        print(f"Error saving memory: {e}")
        await sio.emit('error', {'msg': f"Failed to save memory: {str(e)}"})

@sio.event
async def upload_memory(sid, data):
    print(f"Received memory upload request")
    try:
        memory_text = data.get('memory', '')
        if not memory_text:
            print("No memory data provided.")
            return

        if not audio_loop:
             print("[SERVER DEBUG] [Error] Audio loop is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (Audio Loop inactive)"})
             return
        
        if not audio_loop.session:
             print("[SERVER DEBUG] [Error] Session is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (No active session)"})
             return

        print("Sending memory context to model...")
        context_msg = f"System Notification: The user has uploaded a long-term memory file. Please load the following context into your understanding. The format is a text log of previous conversations:\n\n{memory_text}"
        
        await audio_loop.session.send(input=context_msg, end_of_turn=True)
        print("Memory context sent successfully.")
        await sio.emit('status', {'msg': 'Memory Loaded into Context'})

    except Exception as e:
        print(f"Error uploading memory: {e}")
        await sio.emit('error', {'msg': f"Failed to upload memory: {str(e)}"})

@sio.event
async def prompt_web_agent(sid, data):
    prompt = data.get('prompt')
    print(f"Received web agent prompt: '{prompt}'")
    
    if not audio_loop or not audio_loop.web_agent:
        await sio.emit('error', {'msg': "Web Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Web Agent running...'})
        await audio_loop.web_agent.run(prompt)
        await sio.emit('status', {'msg': 'Web Agent finished'})
        
    except Exception as e:
        print(f"Error running Web Agent: {e}")
        await sio.emit('error', {'msg': f"Web Agent Error: {str(e)}"})

@sio.event
async def get_settings(sid):
    await sio.emit('settings', SETTINGS)

@sio.event
async def update_settings(sid, data):
    print(f"Updating settings: {data}")
    
    if "tool_permissions" in data:
        SETTINGS["tool_permissions"].update(data["tool_permissions"])
        if audio_loop:
            audio_loop.update_permissions(SETTINGS["tool_permissions"])
            
    if "face_auth_enabled" in data:
        SETTINGS["face_auth_enabled"] = data["face_auth_enabled"]
        if not data["face_auth_enabled"]:
             await sio.emit('auth_status', {'authenticated': True})
             if authenticator:
                 authenticator.stop() 

    if "camera_flipped" in data:
        SETTINGS["camera_flipped"] = data["camera_flipped"]
        print(f"[SERVER] Camera flip set to: {data['camera_flipped']}")

    save_settings()
    await sio.emit('settings', SETTINGS)


@sio.event
async def get_tool_permissions(sid):
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def update_tool_permissions(sid, data):
    print(f"Updating permissions (legacy event): {data}")
    SETTINGS["tool_permissions"].update(data)
    save_settings()
    
    if audio_loop:
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  ANBU BLACK OPS V2 - Starting...")
    if DIST_EXISTS:
        print(f"  Open in browser: http://localhost:8000")
    else:
        print(f"  Frontend: Run 'npm run build' to enable")
    print(f"{'='*50}\n")

    uvicorn.run(
        "server:app_socketio", 
        host=os.getenv("ZORO_HOST", "0.0.0.0"), 
        port=int(os.getenv("PORT", os.getenv("ZORO_PORT", "8000"))), 
        reload=False,
        loop="asyncio",
        reload_excludes=["temp_cad_gen.py", "output.stl", "*.stl"],
        backlog=128,
        timeout_keep_alive=30
    )
