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

def main():
    prompt_file = "G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle13_phaseC_prompt.txt"
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    print(f"Loaded Phase C prompt ({len(prompt_text)} chars).")
    
    # 1. Type prompt
    print("[1] Typing Phase C prompt into ChatGPT...")
    r = mcp_call("chatgpt", "type", {"sel": "[aria-label='Спросить ChatGPT']", "text": prompt_text})
    print("Type response:", r)
    time.sleep(1.5)
    
    # 2. Find and click send button
    print("[2] Checking send button...")
    dom = mcp_call("chatgpt", "dom", {"sel": "button[aria-label='Отправить'], button[data-testid='send-button']", "limit": 5})
    print("Send button candidates:", dom)
    
    print("[3] Clicking send button...")
    r = mcp_call("chatgpt", "click", {"sel": "button[aria-label='Отправить'], button[data-testid='send-button']"})
    print("Click response:", r)
    
    if not r.get("data", {}).get("clicked"):
        print("Click failed, falling back to Enter key...")
        r = mcp_call("chatgpt", "key", {"sel": "[aria-label='Спросить ChatGPT']", "key": "Enter", "code": "Enter"})
        print("Key response:", r)
        
    # 3. Wait for generation
    print("[4] Monitoring generation...")
    start = time.time()
    generating_seen = False
    timeout_sec = 360
    
    while time.time() - start < timeout_sec:
        stop_check = mcp_call("chatgpt", "dom", {
            "sel": "button[aria-label*='Останов' i], button[data-testid='stop-button']",
            "limit": 1
        })
        is_generating = stop_check.get("data", {}).get("count", 0) > 0
        
        if is_generating:
            generating_seen = True
            elapsed = int(time.time() - start)
            print(f"ChatGPT is generating... ({elapsed}s)")
            time.sleep(5)
            continue
            
        if generating_seen and not is_generating:
            print("Generation finished!")
            time.sleep(5)  # wait for DOM settle
            break
            
        elapsed = int(time.time() - start)
        print(f"Waiting for generation start/finish... ({elapsed}s)")
        time.sleep(4)
        
    print("[5] Extracting response...")
    # Fetch assistant messages
    dom = mcp_call("chatgpt", "dom", {
        "sel": "[data-message-author-role='assistant'], div.markdown",
        "limit": 10,
        "textChars": 35000
    })
    
    items = dom.get("data", {}).get("items", [])
    print(f"Found {len(items)} matching elements.")
    
    # We want the last assistant block
    if items:
        # Pick the last item with substantial text
        best_text = ""
        for item in reversed(items):
            txt = item.get("text", "").strip()
            if len(txt) > len(best_text):
                best_text = txt
                
        if "=== ПЛАН ===" in best_text or len(best_text) > 500:
            print(f"Extracted plan length: {len(best_text)} chars")
            idx = best_text.find("=== ПЛАН ===")
            if idx != -1:
                plan_content = best_text[idx:]
            else:
                plan_content = "=== ПЛАН ===\n\n" + best_text
            
            with open("G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/last_plan.md", "w", encoding="utf-8") as f:
                f.write(plan_content)
            with open("G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle13_phaseC_plan.md", "w", encoding="utf-8") as f:
                f.write(plan_content)
                
            print("Successfully saved last_plan.md and cycle13_phaseC_plan.md!")
            return
            
    print("Warning: could not extract full plan directly. Saving raw items for inspection.")
    with open("G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle13_phaseC_raw.json", "w", encoding="utf-8") as f:
        json.dump(dom, f, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    main()
