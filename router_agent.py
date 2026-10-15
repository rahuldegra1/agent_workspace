import json
import requests
import re

from model_manager import unload_model, OLLAMA_BASE_URL

ROUTER_MODEL = "qwen2.5:0.5b"

ROUTER_PROMPT = """
You are the central routing gateway for a desktop automation system.
Analyze the user's task. If the task contains multiple actions or requires different types of skills, you MUST break it down into sequential, single-intent sub-tasks.

ASSIGNMENT RULES:
- Use "llava" whenever an action involves GUI interaction, opening an app/browser, clicking, typing in a window, or interacting with the screen.
- Use "qwen2.5:1.5b" ONLY for simple text parsing, string reformatting, or basic summaries.
- Use "qwen2.5:3b" for intermediate scripting or standard shell logic.
- Use "qwen2.5-coder:7b" for writing algorithms, data structures, or complex code.

EXAMPLE:
User Task: "Open Chrome, search for weather in Tokyo, and write a Python script to parse the temperature."
Output:
{
  "routing_plan": [
    {"step": 1, "model": "llava", "instruction": "Open Chrome and search for weather in Tokyo"},
    {"step": 2, "model": "qwen2.5-coder:7b", "instruction": "Write a Python script to parse temperature data"}
  ]
}

Return ONLY valid JSON matching this schema:
{
  "routing_plan": [
    {
      "step": 1,
      "model": "<exact_model_name>",
      "instruction": "<sub-task instruction>"
    }
  ]
}
"""

def get_routing_plan(user_prompt: str) -> list:
    print(f" -> [Router] Dispatching via {ROUTER_MODEL}...")

    payload = {
        "model": ROUTER_MODEL,
        "prompt": f"{ROUTER_PROMPT}\n\nUser Task: \"{user_prompt}\"\nOutput:",
        "stream": False,
        "format": "json",
        "keep_alive": -1,
        "options": {
            "temperature": 0.0
        }
    }

    try:
        response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=60)
        response.raise_for_status()
        text = response.json().get("response", "")

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text.strip())
            text = re.sub(r"\s*```$", "", text)

        plan = json.loads(text).get("routing_plan", [])
        return plan

    except Exception as e:
        print(f" -> [Router Error]: Failed to generate plan - {e}")
        return []

if __name__ == "__main__":
    test_task = "Open Google Chrome, navigate to my GitHub, and then write a Python script for a binary search tree."
    print(f"User Task: {test_task}\n")

    plan = get_routing_plan(test_task)

    print("\nFinal Routing Plan:")
    print(json.dumps(plan, indent=2))