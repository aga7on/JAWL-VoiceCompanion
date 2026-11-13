import urllib.request
import json
import time
import sys
import os

MCP_URL = "http://127.0.0.1:5051/job?wait=30"

def mcp_call(tab, cmd, args, wait=30):
    payload = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=wait + 5) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    prompt_path = r"G:\AI\JAWL-VoiceCompanion-V0.5\tools\seniors_bridge\prompts\cycle13_phaseB_argon_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    print(f"Loaded prompt: {len(prompt_text)} characters")

    # Step 1: Check initial markdown count
    init_res = mcp_call("arena", "eval", {"code": """
    const msgs = document.querySelectorAll('.markdown, [class*="prose"], [class*="markdown"]');
    return { count: msgs.length };
    """})
    base_count = init_res.get("data", {}).get("data", {}).get("count", 0)
    print(f"Initial markdown messages count on Arena: {base_count}")

    # Step 2: Insert text and click send
    submit_code = f"""
    const text = {json.dumps(prompt_text)};
    const ta = document.querySelector('textarea[name="message"]') || document.querySelector('textarea');
    if (!ta) return {{ ok: false, error: 'textarea not found' }};
    ta.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
    
    // Check send button
    const btn = document.querySelector('button[aria-label="Send message"]') || document.querySelector('button[type="submit"]');
    if (!btn) return {{ ok: false, error: 'send button not found' }};
    if (btn.disabled) return {{ ok: false, error: 'send button is disabled' }};
    
    btn.click();
    return {{ ok: true, clicked: true }};
    """
    submit_res = mcp_call("arena", "eval", {"code": submit_code})
    print("Submit response:", json.dumps(submit_res, ensure_ascii=False))

    if not submit_res.get("data", {}).get("data", {}).get("ok"):
        print("Failed to submit! Exiting.")
        sys.exit(1)

    print("Successfully clicked Send! Now polling for Argon response...")

    # Step 3: Poll for completion
    last_text = ""
    stable_count = 0
    start_time = time.time()
    
    while True:
        time.sleep(3)
        poll_res = mcp_call("arena", "eval", {"code": """
        const msgs = Array.from(document.querySelectorAll('.markdown, [class*="prose"], [class*="markdown"]'));
        const sendBtn = document.querySelector('button[aria-label="Send message"]');
        const stopBtn = document.querySelector('button[aria-label="Stop generating"]') || 
                        document.querySelector('button svg.lucide-square') || 
                        Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Stop') || b.getAttribute('aria-label') === 'Stop');
        
        let lastMsgText = '';
        if (msgs.length > 0) {
            lastMsgText = msgs[msgs.length - 1].innerText || msgs[msgs.length - 1].textContent || '';
        }
        return {
            msgCount: msgs.length,
            lastMsgLength: lastMsgText.length,
            lastMsgText: lastMsgText,
            isGenerating: !!stopBtn || (sendBtn && sendBtn.disabled),
            sendBtnDisabled: sendBtn ? sendBtn.disabled : null
        };
        """})

        data = poll_res.get("data", {}).get("data", {})
        msg_count = data.get("msgCount", 0)
        curr_text = data.get("lastMsgText", "")
        curr_len = len(curr_text)
        is_gen = data.get("isGenerating", False)
        elapsed = int(time.time() - start_time)

        print(f"[{elapsed}s] msgCount={msg_count}, len={curr_len}, isGen={is_gen}")

        if curr_len > 0 and curr_len == len(last_text):
            stable_count += 1
        else:
            stable_count = 0

        last_text = curr_text

        # If length is substantial and has been stable for 4 polls (12s) and not generating, or stable for 6 polls
        if curr_len > 1500 and (stable_count >= 4 and not is_gen or stable_count >= 6):
            print(f"Generation completed! Final length: {curr_len} chars.")
            break

        if elapsed > 300: # 5 min timeout
            print("Timeout waiting for generation.")
            break

    # Save extract
    out_path = r"G:\AI\JAWL-VoiceCompanion-V0.5\tools\seniors_bridge\extracts\cycle13_phaseB_argon.md"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(last_text)

    print(f"Wrote {len(last_text)} chars to {out_path}")

if __name__ == "__main__":
    main()
