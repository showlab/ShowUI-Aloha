import json
import re
import os
import argparse
import glob

class LogProcessor:
    def __init__(self):
        self.actions = []
        
    def timestamp_to_seconds(self, timestamp_str):
        """Convert timestamp string to seconds"""
        try:
            time_parts = timestamp_str.split(":")
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds_parts = time_parts[2].split(".")
            seconds = int(seconds_parts[0])
            if len(seconds_parts) > 1:
                milliseconds = int(seconds_parts[1].ljust(3, "0"))
            else:
                milliseconds = 0
            total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
            return total_seconds
        except Exception as e:
            print(f"Error parsing timestamp: {timestamp_str}")
            return None
    
    def process_input_log(self, log_file_path):
        """Process the input log file and extract actions"""
        if not os.path.exists(log_file_path):
            raise FileNotFoundError(f"Log file not found: {log_file_path}")
            
        actions = []
        current_software = None
        coord_pattern = r'\((\d+),\s*(\d+)\)'
        
        with open(log_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                    
                try:
                    event_data = json.loads(line)
                    
                    # Skip video start time info
                    if "video_start_time" in event_data:
                        continue
                        
                    timestamp = event_data.get("timestamp")
                    message = event_data.get("message")
                    window = event_data.get("window")
                    
                    # Skip Screen Recorder events
                    if window and "Screen Recorder" in window:
                        if isinstance(message, str):
                            if (message.startswith("Initial Active Window")
                                or message.startswith("Active Window")):
                                continue
                    
                    if message.startswith("Active Window"):
                        continue
                    # Convert timestamp to seconds
                    timestamp_seconds = self.timestamp_to_seconds(timestamp)
                    if timestamp_seconds is None:
                        continue
                    
                    # Parse coordinates
                    coords = []
                    coord_matches = re.finditer(coord_pattern, message)
                    for coord_match in coord_matches:
                        coords.append({
                            "x": int(coord_match.group(1)),
                            "y": int(coord_match.group(2))
                        })
                    
                    # Handle special cases
                    if "Initial Active Window:" in message or "Active Window:" in message:
                        current_software = window
                        action = "Active Window"
                    else:
                        action = message
                        # Clean coordinates from action description
                        if coords:
                            action = re.sub(r'\s*\(\d+,\s*\d+\)', '', action)
                    
                    # Handle configuration info (first line)
                    if timestamp == "00:00:00.000" and current_software is None:
                        try:
                            config_data = json.loads(message)
                            action_dict = {
                                "timestamp": timestamp_seconds,
                                "action": "CONFIG",
                                "coords": config_data,
                                "current_software": "System Info"
                            }
                            actions.append(action_dict)
                            continue
                        except:
                            pass
                    
                    action_dict = {
                        "timestamp": timestamp_seconds,
                        "action": action,
                        "coords": coords if coords else None,
                        "current_software": window
                    }
                    actions.append(action_dict)
                    
                except json.JSONDecodeError as e:
                    print(f"Warning: JSON parsing error: {line}")
                    continue
                except Exception as e:
                    print(f"Warning: Processing error: {line}\nError: {str(e)}")
                    continue
        
        if not actions:
            raise ValueError("No valid actions found in log file")
            
        self.actions = actions
        return actions
    
    def calculate_backspace_deletions(self, duration, base_rate=10):
        """Calculate how many characters to delete based on backspace duration"""
        # Characters per second when holding backspace
        if duration <= 0.05:  # Single tap
            return 1
        elif duration <= 0.5:  # Short hold
            return max(1, int(duration * base_rate))
        else:  # Long hold - accelerated deletion
            # First 0.5s at base rate, then accelerated
            base_deletions = int(0.5 * base_rate)
            accelerated_time = duration - 0.5
            accelerated_deletions = int(accelerated_time * base_rate * 2)  # 2x speed
            return base_deletions + accelerated_deletions

    def merge_keyboard_events(self, actions, time_threshold=5.0):
        """Merge consecutive keyboard events into typing actions with backspace handling"""
        merged_actions = []
        buffer = []
        last_timestamp = None
        current_window = None
        last_click_coords = None
        special_keys = {'ENTER'}
        
        i = 0
        while i < len(actions):
            action = actions[i]
            
            if action["action"] == "CONFIG":
                merged_actions.append(action)
                i += 1
                continue
                
            timestamp = action["timestamp"]
            message = action["action"]
            window = action["current_software"]
            
            if window:
                current_window = window
            
            # Track click coordinates for typing position
            if "Click" in message and action["coords"]:
                last_click_coords = action["coords"]
            
            # Handle backspace events (including with modifiers)
            if ("BACKSPACE" in message and 
                ("Key Press:" in message or "Hotkey:" in message)):
                
                # Find the end of backspace sequence
                backspace_start = timestamp
                backspace_end = timestamp
                j = i + 1
                
                # Look for release or next non-backspace event
                while j < len(actions):
                    next_action = actions[j]
                    next_message = next_action["action"]
                    
                    if "Key Release:" in next_message and "BACKSPACE" in next_message:
                        backspace_end = next_action["timestamp"]
                        break
                    elif not ("BACKSPACE" in next_message and 
                            ("Key Press:" in next_message or "Hotkey:" in next_message)):
                        # Next non-backspace event
                        break
                    j += 1
                
                # Calculate deletion duration and characters to delete
                duration = backspace_end - backspace_start
                chars_to_delete = self.calculate_backspace_deletions(duration)
                
                # Apply deletions to buffer
                if buffer:
                    original_length = len(buffer)
                    if chars_to_delete >= original_length:
                        # Delete entire buffer
                        buffer = []
                    else:
                        # Delete from end
                        buffer = buffer[:-chars_to_delete]
                
                # Skip to after the backspace sequence
                i = j
                continue
            
            # Handle regular key press events
            elif "Key Press:" in message:
                key = message.replace("Key Press:", "").strip()
                
                if key in special_keys:
                    # Flush current typing before ENTER
                    if buffer:
                        merged_message = "".join(buffer)
                        merged_actions.append({
                            "timestamp": last_timestamp,
                            "action": f"Type: {merged_message}",
                            "coords": last_click_coords,
                            "current_software": current_window
                        })
                        buffer = []
                    # Record ENTER explicitly as its own action (at press time)
                    merged_actions.append({
                        "timestamp": timestamp,
                        "action": "Press ENTER",
                        "coords": last_click_coords,
                        "current_software": current_window
                    })

                elif key == 'SPACE':
                    # Include space character in typing buffer
                    if last_timestamp and (timestamp - last_timestamp) > time_threshold and buffer:
                        merged_message = "".join(buffer)
                        merged_actions.append({
                            "timestamp": last_timestamp,
                            "action": f"Type: {merged_message}",
                            "coords": last_click_coords,
                            "current_software": current_window
                        })
                        buffer = []
                    buffer.append(" ")
                    last_timestamp = timestamp
                    current_window = current_window or action.get("current_software")
                    if action.get("coords") is not None:
                        last_click_coords = action.get("coords")
                
                elif key == 'DELETE' or key == 'BACKSPACE':
                    # Surface DELETE as an explicit action (not typing)
                    # Flush any buffered typing first
                    if buffer:
                        merged_message = "".join(buffer)
                        merged_actions.append({
                            "timestamp": last_timestamp,
                            "action": f"Type: {merged_message}",
                            "coords": last_click_coords,
                            "current_software": current_window
                        })
                        buffer = []
                    merged_actions.append({
                        "timestamp": timestamp,
                        "action": "Press " + key,
                        "coords": last_click_coords,
                        "current_software": current_window
                    })
                        
                elif len(key) == 1:
                    # Check time gap
                    if last_timestamp and (timestamp - last_timestamp) > time_threshold and buffer:
                        merged_message = "".join(buffer)
                        merged_action = {
                            "timestamp": last_timestamp,
                            "action": f"Type: {merged_message}",
                            "coords": last_click_coords,
                            "current_software": current_window
                        }
                        merged_actions.append(merged_action)
                        buffer = []
                    
                    buffer.append(key)
                    last_timestamp = timestamp
            
            # Handle shift+key combinations (but not shift+backspace which is handled above)
            elif ("Hotkey: SHIFT+" in message and 
                  "BACKSPACE" not in message and 
                  len(message.replace("Hotkey: SHIFT+", "").strip()) == 1):
                key = message.replace("Hotkey: SHIFT+", "").strip()
                buffer.append(key)
                last_timestamp = timestamp
            
            elif message.startswith("Hotkey: CTRL+"):
                # Record CTRL hotkeys (e.g., CTRL+S, CTRL+C) as separate actions
                merged_actions.append({
                    "timestamp": timestamp,
                    "action": message,   # e.g., "Hotkey: CTRL+S"
                    "coords": last_click_coords,
                    "current_software": current_window
                })
            
            # Skip key release events and standalone hotkeys
            elif ("Key Release:" in message or 
                  message == "Hotkey: SHIFT" or
                  ("Hotkey:" in message and "BACKSPACE" not in message)):
                pass
            
            # Other events - flush buffer first
            else:
                if buffer:
                    merged_message = "".join(buffer)
                    merged_action = {
                        "timestamp": last_timestamp,
                        "action": f"Type: {merged_message}",
                        "coords": last_click_coords,
                        "current_software": current_window
                    }
                    merged_actions.append(merged_action)
                    buffer = []
                
                merged_actions.append(action)
            
            i += 1
        
        # Handle remaining buffer
        if buffer:
            merged_message = "".join(buffer)
            merged_action = {
                "timestamp": last_timestamp,
                "action": f"Type: {merged_message}",
                "coords": last_click_coords,
                "current_software": current_window
            }
            merged_actions.append(merged_action)
        
        return merged_actions

    
    def merge_mouse_events(self, actions):

        def coords_close(a, b, tol=3):
            if a is None or b is None:
                return False
            return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= tol
        """Merge click and release events"""
        merged_actions = []
        i = 0
        
        while i < len(actions):
            current_action = actions[i]
            message = current_action["action"]
            
            # Handle click events
            if "Click" in message and current_action["coords"]:
                coords = current_action["coords"][0]
                click_coords = (coords["x"], coords["y"])
                
                # Look for corresponding release event
                if i + 1 < len(actions):
                    next_action = actions[i + 1]
                    
                # Case 1: Click followed by Release
                if i + 1 < len(actions):
                    next_action = actions[i + 1]
                    if ("Release" in next_action["action"] and next_action.get("coords")):
                        r0 = next_action["coords"][0]
                        rel_coords = (r0["x"], r0["y"])
                        if coords_close(click_coords, rel_coords, 5):
                            merged_actions.append({
                                "timestamp": next_action["timestamp"],
                                "action": message,  # e.g., "LClick at"
                                "coords": current_action["coords"],  # keep the click coords
                                "current_software": current_action.get("current_software")
                            })
                            i += 2
                            continue

                # Case 2: Click → Active Window → Release
                if i + 2 < len(actions):
                    mid_action = actions[i + 1]
                    rel_action = actions[i + 2]
                    if ("Active Window" in mid_action["action"] and
                        "Release" in rel_action["action"] and rel_action.get("coords")):
                        r0 = rel_action["coords"][0]
                        rel_coords = (r0["x"], r0["y"])
                        if coords_close(click_coords, rel_coords, 5):
                            merged_actions.append({
                                "timestamp": rel_action["timestamp"],
                                "action": message,
                                "coords": current_action["coords"],
                                "current_software": current_action.get("current_software")
                            })
                            i += 3
                            continue
            merged_actions.append(current_action)
            i += 1
        
        return merged_actions
    
    def process_scroll_events(self, actions):
        """Group consecutive scroll events"""
        processed_actions = []
        i = 0
        
        while i < len(actions):
            current_action = actions[i]
            message = current_action["action"]
            
            if "Scroll" in message:
                scroll_down_count = 0
                scroll_up_count = 0
                coords_events = []
                
                # Count initial scroll
                if "ScrollDown" in message:
                    scroll_down_count += 1
                elif "ScrollUp" in message:
                    scroll_up_count += 1
                
                coords_events.append((current_action["timestamp"], 
                                   current_action["coords"][0] if current_action["coords"] else None))
                
                # Look for consecutive scroll events
                while i + 1 < len(actions) and "Scroll" in actions[i + 1]["action"]:
                    i += 1
                    next_action = actions[i]
                    if "ScrollDown" in next_action["action"]:
                        scroll_down_count += 1
                    elif "ScrollUp" in next_action["action"]:
                        scroll_up_count += 1
                    
                    coords_events.append((next_action["timestamp"], 
                                       next_action["coords"][0] if next_action["coords"] else None))
                
                # Find most common coordinate
                coords_count = {}
                for timestamp, coord in coords_events:
                    if coord:
                        coord_str = f"{coord['x']},{coord['y']}"
                        if coord_str in coords_count:
                            coords_count[coord_str][0] += 1
                        else:
                            coords_count[coord_str] = [1, timestamp, coord]
                
                # Get most frequent coordinate
                max_count = 0
                best_timestamp = current_action["timestamp"]
                best_coord = current_action["coords"][0] if current_action["coords"] else None
                
                for coord_str, (count, timestamp, coord) in coords_count.items():
                    if count > max_count:
                        max_count = count
                        best_timestamp = timestamp
                        best_coord = coord
                
                # Create merged scroll event
                if scroll_down_count >= scroll_up_count:
                    scroll_action = "ScrollDown"
                    scroll_count = scroll_down_count - scroll_up_count
                else:
                    scroll_action = "ScrollUp"
                    scroll_count = scroll_up_count - scroll_down_count
                
                merged_action = {
                    "timestamp": best_timestamp,
                    "action": f"{scroll_action} at",
                    "coords": [best_coord] if best_coord else None,
                    "current_software": current_action["current_software"],
                    "scroll_count": scroll_count
                }
                processed_actions.append(merged_action)
            else:
                processed_actions.append(current_action)
            
            i += 1
        
        return processed_actions
    
    def merge_adjacent_typing(self, actions, time_threshold=5.0):
        """Merge adjacent typing actions that are close in time and location"""
        if not actions:
            return actions
            
        merged_actions = []
        i = 0
        
        while i < len(actions):
            current_action = actions[i]
            
            # Check if this is a typing action
            if current_action["action"].startswith("Type:"):
                # Collect consecutive typing actions within threshold
                typing_sequence = [current_action]
                j = i + 1
                
                while j < len(actions):
                    next_action = actions[j]
                    
                    # Check if next action is also typing
                    if not next_action["action"].startswith("Type:"):
                        break
                    
                    # Check time gap
                    time_gap = next_action["timestamp"] - typing_sequence[-1]["timestamp"]
                    if time_gap > time_threshold:
                        break
                    
                    # Check if coordinates are similar (same text field)
                    if (current_action["coords"] and next_action["coords"] and
                        abs(current_action["coords"][0]["x"] - next_action["coords"][0]["x"]) <= 10 and
                        abs(current_action["coords"][0]["y"] - next_action["coords"][0]["y"]) <= 10):
                        typing_sequence.append(next_action)
                        j += 1
                    else:
                        break
                
                # Merge the typing sequence if more than one action
                if len(typing_sequence) > 1:
                    # Combine all text
                    combined_text = ""
                    for typing_action in typing_sequence:
                        text = typing_action["action"].replace("Type: ", "")
                        combined_text += text
                    
                    # Create merged action using the last timestamp and first coordinates
                    merged_action = {
                        "timestamp": typing_sequence[-1]["timestamp"],
                        "action": f"Type: {combined_text}",
                        "coords": typing_sequence[0]["coords"],
                        "current_software": typing_sequence[0]["current_software"]
                    }
                    merged_actions.append(merged_action)
                    i = j
                else:
                    # Single typing action, keep as is
                    merged_actions.append(current_action)
                    i += 1
            else:
                # Non-typing action, keep as is
                merged_actions.append(current_action)
                i += 1
        merged_actions = [
            a for a in merged_actions if "Active Window" not in (a.get("action") or "")
        ]
        return merged_actions
   
    def merge_drag_events(self, actions):
        merged = []
        i = 0
        while i < len(actions):
            a0 = actions[i]
            msg0 = a0.get("action") or ""
            # Detect DragStart
            if msg0.startswith("DragStart") and a0.get("coords"):
                start_coord = a0["coords"][0] if a0["coords"] else None
                path = []
                path.append(start_coord)
                j = i + 1
                end_action = None
                while j < len(actions):
                    aj = actions[j]
                    msgj = aj.get("action") or ""
                    # Collect DragMove points
                    if msgj.startswith("DragMove") and aj.get("coords"):
                        path.append(aj["coords"][0])
                        j += 1
                        continue
                    # Allow Active Window noise
                    if "Active Window" in msgj:
                        j += 1
                        continue
                    # Termination on DragEnd (LDragEnd variants)
                    if "DragEnd" in msgj:
                        path.append(aj["coords"][0])
                        # Build outputs
                        start_out = {
                            "timestamp": a0["timestamp"],
                            "action": "DragStart at",
                            "coords": [start_coord] if start_coord else None,
                            "current_software": a0.get("current_software"),
                        }
                        if path:
                            start_out["path"] = path                       
                        merged.append(start_out)
                        i = j + 1
                        end_action = True
                        break
                    # Unexpected break in drag sequence -> fall back to emitting the original DragStart and continue
                    break
                if end_action:
                    continue
                # No end found — keep original DragStart and advance one
                merged.append(a0)
                i += 1
                continue
            # Not a DragStart — keep as-is
            merged.append(a0)
            i += 1
        return merged
    
    def cleanup_preceded_double_clicks(self, actions, tol=5):
        """If a DoubleClick is immediately preceded by a Click in ~same spot, drop the single Click.
        This should run as the last filter before output."""
        def get_xy(act):
            try:
                c = act.get("coords") or []
                if not c:
                    return None
                return (int(c[0]["x"]), int(c[0]["y"]))
            except Exception:
                return None
        def is_click(act):
            msg = (act.get("action") or "").lower()
            # single click but not double click
            return ("click" in msg) and ("dblclick" not in msg) and ("double" not in msg)
        def is_dblclick(act):
            msg = (act.get("action") or "").lower()
            return ("dblclick" in msg) or ("doubleclick" in msg) or ("double click" in msg)
        def close(a, b, t=tol):
            if a is None or b is None:
                return False
            return max(abs(a[0]-b[0]), abs(a[1]-b[1])) <= t

        out = []
        for act in actions:
            if is_dblclick(act) and out:
                prev = out[-1]
                if is_click(prev) and close(get_xy(prev), get_xy(act), tol):
                    # Drop the preceding single click; keep the double click
                    out.pop()
                    out.append(act)
                    continue
            out.append(act)
        return out
    
    def cleanup_click_before_drag(self, actions, tol=5):
        def get_xy(act):
            try:
                c = act.get("coords") or []
                if not c:
                    return None
                return (int(c[0]["x"]), int(c[0]["y"]))
            except Exception:
                return None

        def is_lclick(act):
            msg = (act.get("action") or "").lower()
            # single left click only (not double click, not drag)
            return ("lclick" in msg or "left click" in msg) and ("double" not in msg) and ("dblclick" not in msg)

        def is_dragstart(act):
            msg = (act.get("action") or "").lower()
            return msg.startswith("dragstart")

        def close(a, b):
            if a is None or b is None:
                return False
            return max(abs(a[0]-b[0]), abs(a[1]-b[1])) <= tol

        out = []
        for act in actions:
            if is_dragstart(act) and out and is_lclick(out[-1]) and close(get_xy(out[-1]), get_xy(act)):
                # Drop the LClick immediately before this DragStart
                out.pop()
            out.append(act)
        return out


    def process_log_file(self, log_file_path, output_path=None, time_threshold=5.0):
        """Main processing function"""
        # Step 1: Parse input log
        actions = self.process_input_log(log_file_path)
        print(f"Parsed {len(actions)-1} raw actions")
        
        # Step 2: Merge keyboard events with custom time threshold
        actions = self.merge_keyboard_events(actions, time_threshold)
        print(f"After keyboard merge: {len(actions)-1} actions")
        
        # Step 3: Merge mouse events
        actions = self.merge_mouse_events(actions)
        print(f"After mouse merge: {len(actions)-1} actions")

        # Step 4: Merge drag events
        actions = self.merge_drag_events(actions)
        print(f"After drag merge: {len(actions)-1} actions")
        
        # Step 5: Process scroll events
        actions = self.process_scroll_events(actions)
        print(f"After scroll processing: {len(actions)-1} actions")
        
        # Step 6: Merge adjacent typing actions
        actions = self.merge_adjacent_typing(actions, time_threshold)
        print(f"After typing merge: {len(actions)-1} actions")

        # Step 7: Remove single-click directly preceding a nearby double-click
        actions = self.cleanup_preceded_double_clicks(actions, tol=5)
        print(f"After double-click cleanup: {len(actions)-1} actions")

        # Step 8: Remove single-click directly preceding a nearby drag
        actions = self.cleanup_click_before_drag(actions, tol=5)
        if actions:
            actions.pop()
        print(f"After click-before-drag and final recording cleanup: {len(actions)-1} actions")
        
        # Step 9: Sort and Save processed log
        actions.sort(key=lambda a: a.get("timestamp", 0))
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(actions, f, indent=2, ensure_ascii=False)
            print(f"Processed log saved to: {output_path}")
        
        return actions

def main():
    """Command line interface for the log processor"""
    parser = argparse.ArgumentParser(
        description='Process GUI automation log files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python log_processor.py --project qatar_booking
  python log_processor.py --project qatar_booking --output result.json
  python log_processor.py --project qatar_booking --typing-delay 10
  python log_processor.py -p qatar_booking -o result.json -t 3.5
        """
    )
    
    parser.add_argument(
        '--project', '-p',
        required=True,
        help='Project name (required). Will look for log file in /projects/{project_name}/inputs/'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output JSON file path (default: /projects/{project_name}/outputs/processed_log.json)'
    )
    
    parser.add_argument(
        '--typing-delay', '-t',
        type=float,
        default=5.0,
        help='Maximum time gap (seconds) between keystrokes to consider them as one typing action (default: 5.0)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Construct input directory path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(base_dir, "projects", args.project, "inputs")
    
    # Check if input directory exists
    if not os.path.exists(input_dir):
        print(f"Error: Project directory not found: {input_dir}")
        print(f"Please ensure the project '{args.project}' exists and has an inputs folder.")
        return 1
    
    # Find log file in input directory
    log_files = []
    for ext in ['*.txt', '*.log', '*.json']:
        log_files.extend(glob.glob(os.path.join(input_dir, ext)))
    
    if not log_files:
        print(f"Error: No log files found in {input_dir}")
        print("Supported formats: .txt, .log, .json")
        return 1
    
    if len(log_files) > 1:
        print(f"Error: Multiple log files found in {input_dir}")
        print("Found files:")
        for f in log_files:
            print(f"  {os.path.basename(f)}")
        print("Please ensure only one log file exists in the inputs directory.")
        return 1
    
    input_file = log_files[0]
    
    # Set default output path if not provided
    if not args.output:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.join(base_dir, "projects", args.project)
        os.makedirs(project_dir, exist_ok=True)
        args.output = os.path.join(project_dir, f"{args.project}_processed_log.json")
    else:
        # Create output directory if needed
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
    
    try:
        processor = LogProcessor()
        
        if args.verbose:
            print(f"Project: {args.project}")
            print(f"Input file: {input_file}")
            print(f"Output file: {args.output}")
            print(f"Typing delay threshold: {args.typing_delay}s")
            print("-" * 50)
        
        processed_actions = processor.process_log_file(
            input_file, 
            args.output, 
            time_threshold=args.typing_delay
        )
        
        # Print summary
        print(f"Processing completed successfully")
        print(f"Total actions: {len(processed_actions)}")
        print(f"Output saved to: {args.output}")
        
        if args.verbose:
            action_types = {}
            for action in processed_actions:
                action_type = action["action"].split()[0] if action["action"] else "Unknown"
                action_types[action_type] = action_types.get(action_type, 0) + 1
            
            print("\nAction breakdown:")
            for action_type, count in sorted(action_types.items()):
                print(f"  {action_type}: {count}")
        
        return 0
        
    except Exception as e:
        print(f"Error processing log: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

# Example usage
if __name__ == "__main__":
    exit_code = main()