import os, json, base64, re, time, requests
from typing import List, Dict, Any, Optional

class TraceGenerator:
    """Generate step-by-step traces from GUI actions with crop+full screenshots."""

    def __init__(self, default_prompt_path: str = "default_prompt.json",
                 api_provider: str = "openai",
                 openai_model: str = "gpt-4o",
                 claude_model: str = "claude-sonnet-4-20250514",
                 api_keys_path: str = "config/api_keys.json"):
        """Load default prompt and API settings from config file or env vars."""
        with open(default_prompt_path, "r", encoding="utf-8") as f:
            self.default_prompt = json.load(f)

        self.api_provider = api_provider.lower()
        self.openai_model = openai_model
        self.claude_model = claude_model

        self.openai_key = ""
        self.claude_key = ""

        try:
            with open(api_keys_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.openai_key = cfg.get("OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
            self.claude_key = cfg.get("CLAUDE_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        except FileNotFoundError:
            self.openai_key = os.environ.get("OPENAI_API_KEY", "")
            self.claude_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not self.openai_key and not self.claude_key:
            raise RuntimeError("No API keys found. Please fill config/api_keys.json or set env vars.")

    def _val(self, d: Dict[str, Any], *keys, default=""):
        """Get dictionary value by key (case-insensitive)."""
        for k in keys:
            if k in d: return d[k]
            for dk in d.keys():
                if dk.lower() == k.lower():
                    return d[dk]
        return default

    def _encode_image(self, path: str) -> Optional[str]:
        """Read image file and return base64 data URI."""
        if not path or not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract first valid JSON object from a string."""
        if not text:
            return {}
        blocks = re.findall(r"\{.*\}", text, flags=re.S)
        for b in blocks:
            try:
                return json.loads(b)
            except:
                continue
        try:
            return json.loads(text)
        except:
            return {}

    def _sanitize_caption(self, cap: Dict[str, str]) -> Dict[str, str]:
        """Clean LLM output: strip coordinates, enforce crop-first observation."""
        patterns = [
            r"\bcoordinates?\b.*?\[[^\]]*\]",
            r"\bcoordinates?\b",
            r"\b(x\s*[:=]?\s*\d+|y\s*[:=]?\s*\d+)"
        ]

        def scrub(s: str) -> str:
            if not isinstance(s, str): return s
            for p in patterns:
                s = re.sub(p, "", s, flags=re.I)
            s = re.sub(r"\[\s*\d+\s*,\s*\d+\s*\]", "", s)
            return re.sub(r"\s{2,}", " ", s).strip()

        for k in ("observation", "think", "action", "expectation"):
            cap[k] = scrub(cap.get(k, ""))

        if re.search(r"\brelease\b.*\b(title\s*bar|top[-\s]*left)\b", cap.get("action", ""), re.I):
            cap["action"] = "Click the control shown in the cropped image"
            cap["think"] = "The cropped image shows a single actionable control; clicking it fulfills the intent."

        if not cap.get("observation", "").lower().startswith("cropped image shows"):
            cap["observation"] = ("Cropped image shows " + cap.get("observation", "")).strip()

        return cap

    def _coerce_release_to_click(self, items: List[Dict[str, Any]],
                                 ms_window: int = 500, px_window: int = 32) -> List[Dict[str, Any]]:
        """Convert stray mouse-up events into click actions if no matching down nearby."""
        def near(a, b) -> bool:
            try:
                ax, ay = a[0].get("x"), a[0].get("y")
                bx, by = b[0].get("x"), b[0].get("y")
            except Exception:
                return False
            if None in (ax, ay, bx, by):
                return False
            return abs(ax - bx) <= px_window and abs(ay - by) <= px_window

        last_down = None
        for it in items:
            ts = float(it.get("timestamp") or 0.0)
            act = (it.get("action") or "").lower()
            is_down = any(k in act for k in ("mousedown","lbuttondown","pointerdown"))
            is_up = any(k in act for k in ("mouseup","lbuttonup","pointerup"))
            if is_down:
                last_down = it
            elif is_up:
                recent = False
                if last_down:
                    dt = ts - float(last_down.get("timestamp") or 0.0)
                    recent = (dt <= ms_window/1000.0) and near(it.get("coords"), last_down.get("coords"))
                if not recent:
                    it["action"] = "LClick" if "right" not in act else "RClick"
        return items

    def _prompt(self, action: Dict[str, Any], overall_task: str, step_idx: int, recent_steps: List[Dict[str, Any]]) -> str:
        """Build the step prompt. Core rules live in default_prompt.json; add small action-type deltas conditionally."""
        base = self.default_prompt.get("Base Prompt", "")
        deltas_cfg = self.default_prompt.get("Deltas", {})
        modifier_guide = self.default_prompt.get("Modifier_Guide", "")
        sw = action.get("current_software") or ""
        ts = action.get("timestamp")
        act = (action.get("action") or "").strip()
        recent_json = json.dumps(recent_steps, ensure_ascii=False, indent=2)

        delta = self._action_delta(act, action, deltas_cfg, modifier_guide)

        return f"""{base}

Recent Steps (most recent first, up to 3):
{recent_json}

Step Index: {step_idx}
Action: {act}
Software: {sw}
Timestamp: {ts}s
Overall Task: {overall_task}

{delta}

Respond with JSON only. If your first attempt is not valid JSON, immediately re-emit a corrected JSON."""

    def _action_delta(self, act_str: str, action: Dict[str, Any], deltas_cfg: Dict[str, str], modifier_guide: str) -> str:
        a = (act_str or "").lower()
        key = None
        if "dragstart" in a or a.startswith("drag"):
            key = "Drag"
        elif "rclick" in a or "right click" in a:
            key = "RClick"
        elif "dbl" in a or "double" in a:
            key = "DblClick"
        elif "wheel" in a or "scroll" in a:
            key = "MouseWheel"
        elif "type" in a or "input" in a or "key" in a:
            key = "Type"
        elif "click" in a:
            key = "Click"
        elif "scroll" in a:
            key = "Scroll"
        # Fallback: no delta
        if not key:
            return "ActionTypeDelta: (none)"
        text = deltas_cfg.get(key, "")
        mod_txt = self._modifiers_text(action, modifier_guide)
        return text.replace("<MODIFIER_GUIDE>", mod_txt)

    def _modifiers_text(self, action: Dict[str, Any], modifier_guide: str) -> str:
        """Build a compact modifier summary only when modifiers are actually present.
       Expecting action.get('modifiers') as a list like ['Shift', 'Ctrl'] (case-insensitive)."""
        mods = action.get("modifiers") or action.get("modifier") or []
        if isinstance(mods, str):
            mods = [mods]
        mods = [m.capitalize() for m in mods if isinstance(m, str)]
        present = [m for m in ["Shift", "Ctrl", "Alt"] if m in mods]
        if not present:
            return ""  # remove placeholder cleanly
        # Keep guidance short by scoping to present modifiers only
        guide_map = {
            "Shift": "Shift—add to selection / constrain proportions or direction",
            "Ctrl": "Ctrl—multi-select / special function / precise control",
            "Alt":  "Alt—alternate mode / temporary tool / special functions"
        }
        tips = "; ".join(guide_map[m] for m in present)
        return f"Modifier: {tips}. "

    def _call_openai(self, prompt: str, crop_b64: Optional[str], full_b64: Optional[str]) -> str:
        """Send prompt+images to OpenAI API and return text output."""
        if not self.openai_key:
            raise RuntimeError("OPENAI_API_KEY missing in config/api_keys.json or environment.")
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
        content = [{"type": "text", "text": prompt}]
        if crop_b64: content.append({"type": "image_url", "image_url": {"url": crop_b64}})
        if full_b64: content.append({"type": "image_url", "image_url": {"url": full_b64}})
        data = {"model": self.openai_model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2}
        r = requests.post(url, headers=headers, json=data, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _call_claude(self, prompt: str, crop_b64: Optional[str], full_b64: Optional[str]) -> str:
        """Send prompt+images to Claude API and return text output."""
        if not self.claude_key:
            raise RuntimeError("CLAUDE_API_KEY missing in config/api_keys.json or environment.")
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.claude_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        content = [{"type": "text", "text": prompt}]
        if crop_b64:
            content.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": "image/jpeg",
                                       "data": crop_b64.split(",")[-1]}})
        if full_b64:
            content.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": "image/jpeg",
                                       "data": full_b64.split(",")[-1]}})
        data = {"model": self.claude_model,
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": content}]}
        r = requests.post(url, headers=headers, json=data, timeout=120)
        r.raise_for_status()
        return r.json()["content"][0]["text"]

    def generate_trace(self, recording_json_path: str,
                       screenshots_dir: str,
                       output_trace_path: str,
                       overall_task: str = ""):
        """Main pipeline: read log JSON, pair screenshots, call LLM, and save trace."""
        with open(recording_json_path, "r", encoding="utf-8") as f:
            items = json.load(f)

        items = [it for it in items if isinstance(it, dict)]
        by_ts = {float(it["timestamp"]): it for it in items if "timestamp" in it}
        items = self._coerce_release_to_click(items)

        traj, step_idx = [], 1

        for it in items:
            act_str = (it.get("action") or "").strip()
            if act_str.upper() == "CONFIG":
                continue
            if act_str.startswith("Active Window"):
                continue

            ts = float(it.get("timestamp") or 0.0)
            raw = by_ts.get(ts, it)

            crop = raw.get("screenshot_crop") or raw.get("screenshot")
            full = raw.get("screenshot_full") or raw.get("screenshot")
            if not crop and not full:
                continue

            if isinstance(crop, str) and crop.startswith("screenshots/"):
                crop = crop.replace("screenshots/", "")
            if isinstance(full, str) and full.startswith("screenshots/"):
                full = full.replace("screenshots/", "")

            crop_path = os.path.join(screenshots_dir, crop) if crop else None
            full_path = os.path.join(screenshots_dir, full) if full else None
            crop_b64 = self._encode_image(crop_path) if crop_path else None
            full_b64 = self._encode_image(full_path) if full_path else None
            if not crop_b64 and not full_b64:
                continue

            act = it.get("action") or ""
            coords = it.get("coords")
            if coords and isinstance(coords, list):
                coord_str = ", ".join(f"({c.get('x')},{c.get('y')})" for c in coords)
            else:
                coord_str = ""
            print(f"parsing Step {step_idx}: {act} {coord_str}", flush=True)

            recent = []
            for prev in reversed(traj[-3:]):
                cap = prev.get("caption", {}) or {}
                recent.append({
                    "step_idx": prev.get("step_idx"),
                    "Observation": cap.get("observation", ""),
                    "Think": cap.get("think", ""),
                    "Action": cap.get("action", ""),
                    "Expectation": cap.get("expectation", "")
                })

            prompt = self._prompt(it, overall_task, step_idx, recent)
            if self.api_provider == "claude":
                txt = self._call_claude(prompt, crop_b64, full_b64)
            else:
                txt = self._call_openai(prompt, crop_b64, full_b64)

            data = self._extract_json(txt)
            cap = {
                "observation": self._val(data, "Observation", "observation", default=""),
                "think": self._val(data, "Think", "think", default=""),
                "action": self._val(data, "Action", "action", default=""),
                "expectation": self._val(data, "Expectation", "expectation", default="")
            }
            cap = self._sanitize_caption(cap)

            traj.append({"step_idx": step_idx, "caption": cap})
            step_idx += 1
            time.sleep(0.1)

            with open(output_trace_path, "w", encoding="utf-8") as f:
                json.dump({"trajectory": traj}, f, ensure_ascii=False, indent=2)

            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                grandparent_dir = os.path.dirname(script_dir)
                trace_data_dir = os.path.join(grandparent_dir, "Aloha_Act", "trace_data")
                os.makedirs(trace_data_dir, exist_ok=True)
                alt_path = os.path.join(trace_data_dir, os.path.basename(output_trace_path))
                with open(alt_path, "w", encoding="utf-8") as f2:
                    json.dump({"trajectory": traj}, f2, ensure_ascii=False, indent=2)
                print(f"Trace also saved to: {alt_path}")
            except Exception as e:
                print(f"Warning: Failed to save copy to trace_data folder: {e}")          


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--shots", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--provider", default="openai", choices=["openai","claude"])
    parser.add_argument("--openai_model", default="gpt-4o")
    parser.add_argument("--claude_model", default="claude-sonnet-4-20250514")
    args = parser.parse_args()

    tg = TraceGenerator(default_prompt_path="default_prompt.json",
                        api_provider=args.provider,
                        openai_model=args.openai_model,
                        claude_model=args.claude_model,
                        api_keys_path="config/api_keys.json")
    tg.generate_trace(args.log, args.shots, args.out, overall_task=args.task)
