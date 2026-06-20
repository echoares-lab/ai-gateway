import sys
import json
import os

STATE_FILE = os.path.expanduser("~/.cli-proxy-api/probe_failures.json")

def main():
    if len(sys.argv) < 3:
        return
    alias = sys.argv[1]
    status = int(sys.argv[2])
    
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except Exception:
            pass
            
    if status == 44:
        state[alias] = state.get(alias, 0) + 1
    elif status == 0:
        if alias in state:
            del state[alias]
            
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
        
    print(state.get(alias, 0))

if __name__ == "__main__":
    main()
