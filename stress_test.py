import os
import json
from howdex import Howdex

def run_stress_tests():
    db_path = os.path.join(os.getcwd(), ".howdex_stress_test.db")
    print(f"Initializing Howdex with DB at: {db_path}")
    memory = Howdex(path=db_path)

    print("\n" + "="*50)
    print("🚀 TEST 1: Canonicalization (JSON Key Swap)")
    print("="*50)
    
    memory.start_session("test_canonicalization")
    memory.log_step({"tool": "bash", "cmd": "npm install cors", "cwd": "./"}, "success")
    memory.end_session("success")

    memory.start_session("test_canonicalization")
    memory.log_step({"cwd": "./", "cmd": "npm install cors", "tool": "bash"}, "success")
    memory.end_session("success")

    procedures = memory.learn(min_samples=2)
    print(f"-> Extracted Procedures: {len(procedures)}")
    if len(procedures) > 0:
        print("✅ PASS: Howdex successfully canonicalized the swapped JSON keys.")
    else:
        print("❌ FAIL: Howdex failed to match the swapped keys. LCS is relying on raw strings.")

    print("\n" + "="*50)
    print("🚀 TEST 2: AST Parameterization (Variable Masking)")
    print("="*50)
    
    memory.start_session("test_parameterization")
    memory.log_step({"tool": "fs", "cmd": "write", "file": "app.js"}, "success")
    memory.end_session("success")

    memory.start_session("test_parameterization")
    memory.log_step({"tool": "fs", "cmd": "write", "file": "server.js"}, "success")
    memory.end_session("success")

    procedures = memory.learn(min_samples=2)
    print("-> Current Learned Procedures:")
    for i, proc in enumerate(procedures):
        print(f"   [{i}] {proc}")

    print("\n" + "="*50)
    print("🚀 TEST 3: Terminal Garbage / Token Exhaustion")
    print("="*50)
    
    memory.start_session("test_garbage_1")
    ansi_garbage = "\033[2K\r\033[31mError:\033[0m Cannot resolve module\n"
    massive_stack_trace = "    at Function.Module._resolveFilename (node:internal/modules/cjs/loader:1144:15)\n" * 100
    dirty_payload = (ansi_garbage * 50) + massive_stack_trace
    
    memory.log_step(dirty_payload, "failure")
    memory.end_session("failure")

    context = memory.get_working_context()
    context_length = len(str(context))
    print(f"-> Working Context Length: {context_length} characters")
    
    if "\033" in str(context):
        print("❌ FAIL: ANSI escape codes leaked into the working context. This will poison the LLM.")
    elif context_length > 5000:
        print("❌ FAIL: Howdex failed to truncate the massive stack trace. Token budget will explode.")
    else:
        print("✅ PASS: Context appears sanitized and truncated appropriately.")

if __name__ == "__main__":
    run_stress_tests()
