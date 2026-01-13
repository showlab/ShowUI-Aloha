# Aloha Act — Computer-Use Agent Framework

An open-source, modular framework for building computer-use agents. It includes a server that plans/actions from screenshots and a client that captures screens and executes actions locally.

## Quick Start

Prerequisites
- Python 3.10+
- macOS/Windows (screen capture and automation require local permissions)

Install
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements_server.txt
pip install -r requirements_client.txt
```

Run the server (port 7887)
```bash
python app_server.py
```

Run the client (port 7888)
```bash
python app_client.py
```

Start a task from another terminal
```bash
curl -X POST http://127.0.0.1:7888/run_task \
  -H 'Content-Type: application/json' \
  -d '{
        "task":"open settings",
        "selected_screen":0,
        "trace_id":"hero_cases",
        "max_steps":10,
        "server_url":"http://127.0.0.1:7887/generate_action"
      }'
```

Stop the task
```bash
curl -X POST http://127.0.0.1:7888/stop
```

Expected logs (abridged)
```
# Server
 * Running on http://0.0.0.0:7887
 POST /generate_action 200 ...

# Client
 Starting Client Flask on 0.0.0.0:7888
 [loop_msg] type=image_base64 content=...  
 [loop_msg] type=text content=Observations...  
 [loop_msg] type=text content=Reasoning...  
```

Configure
- Edit `config/config.yaml` for models/paths.
- Provide API keys via env vars or `config/api_keys.json` (git-ignored).


### Roadmap

- [ ] Add more models and actions support
- [ ] OmniParser
- [ ] Benchmark Experiment: OS-World
- [ ] Add Linux support
- [ ] Demo video
