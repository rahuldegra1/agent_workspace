import requests
import time

OLLAMA_BASE_URL = "http://localhost:11434"

def unload_model(model_name: str) -> bool:
    """Forces Ollama to drop the model from VRAM immediately."""
    print(f" -> [Memory] Unloading '{model_name}' from VRAM...")
    payload = {
        "model": model_name,
        "keep_alive": 0  # 0 forces immediate unload
    }
    try:
        response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f" -> [Memory Error] Failed to unload {model_name}: {e}")
        return False

def preload_model(model_name: str) -> bool:
    """Wakes up a model and loads it into VRAM before sending the real prompt."""
    print(f" -> [Memory] Waking up '{model_name}'...")
    payload = {
        "model": model_name,
        "prompt": "", 
        "keep_alive": "5m" # Keep alive for 5 mins while we use it
    }
    try:
        # We don't care about the response, just that it loads
        requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=30)
        time.sleep(1) # Give the GPU a second to settle
        return True
    except Exception as e:
        print(f" -> [Memory Error] Failed to wake up {model_name}: {e}")
        return False