#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
import time
import urllib.request

PORT = 5051

def mcp_call(tab, cmd, args=None, wait=30):
    url = f"http://127.0.0.1:{PORT}/job?wait={wait}"
    payload = json.dumps({"tab": tab, "cmd": cmd, "args": args or {}}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=wait + 5) as resp:
        return json.loads(resp.read().decode("utf-8"))

def send_chatgpt(prompt_text):
    print("[1] Typing prompt into ChatGPT composer...")
    r = mcp_call("chatgpt", "type", {"sel": "[aria-label='Спросить ChatGPT']", "text": prompt_text})
    print("Type result:", r)
    time.sleep(1)
    
    print("[2] Clicking Send button...")
    r = mcp_call("chatgpt", "click", {"sel": "button[aria-label='Отправить']"})
    print("Click result:", r)
    time.sleep(2)

def wait_chatgpt_completion(timeout_sec=240):
    print("[3] Waiting for ChatGPT to complete generation...")
    start = time.time()
    generating_seen = False
    
    while time.time() - start < timeout_sec:
        # Check if stop button is present
        stop_check = mcp_call("chatgpt", "dom", {"sel": "button[aria-label*='Останов' i], button[data-testid='stop-button']", "limit": 1})
        is_generating = stop_check.get("data", {}).get("count", 0) > 0
        
        if is_generating:
            generating_seen = True
            print(f"Generating in progress... ({int(time.time() - start)}s elapsed)")
            time.sleep(4)
            continue
            
        if generating_seen and not is_generating:
            print("Generation completed!")
            time.sleep(3) # allow DOM to settle
            break
            
        # If we haven't seen the stop button yet, check if send button is back or text is appearing
        print(f"Waiting for generation to begin/settle... ({int(time.time() - start)}s)")
        time.sleep(3)
        
    print("[4] Extracting ChatGPT response...")
    # Look for the last response block
    dom = mcp_call("chatgpt", "dom", {
        "sel": ".group\\/writing-block-surface, [class*='agent-turn'], [data-message-author-role='assistant'], div.markdown",
        "limit": 10,
        "textChars": 15000
    })
    
    items = dom.get("data", {}).get("items", [])
    if not items:
        # Fallback to querying all main children
        dom = mcp_call("chatgpt", "dom", {"sel": "main", "textChars": 20000})
        items = dom.get("data", {}).get("items", [])
        
    print(f"Found {len(items)} items")
    return items

def main():
    prompt_file = "tools/seniors_bridge/prompts/cycle13_phase0_chatgpt_prompt.txt"
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()
        
    send_chatgpt(prompt_text)
    items = wait_chatgpt_completion(240)
    
    os.makedirs("tools/seniors_bridge/extracts", exist_ok=True)
    out_file = "tools/seniors_bridge/extracts/cycle13_phaseA_chatgpt.md"
    
    with open(out_file, "w", encoding="utf-8") as f:
        for idx, item in enumerate(items):
            f.write(f"### Item {idx} ({item.get('cls', '')})\n\n{item.get('text', '')}\n\n")
            
    print(f"Saved extracted output to {out_file}")

if __name__ == "__main__":
    main()
