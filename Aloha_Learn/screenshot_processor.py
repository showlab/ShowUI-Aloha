import os
import cv2
import json
from pathlib import Path
import numpy as np


class VideoScreenshotExtractor:
    """Extract full + crop screenshots per action and scale coordinates to a target resolution."""

    def __init__(self, target_width=1920, target_height=1080, jpeg_quality=95, crop_size=256, x_size=30, x_thick=6):
        self.target_width = target_width
        self.target_height = target_height
        self.jpeg_quality = jpeg_quality
        self.crop_size = crop_size
        self.x_size = x_size
        self.x_thick = x_thick

    def scale_path(self, path, scale_x, scale_y):
        """Scale a list of {x,y} points for drag path."""
        if not path:
            return path
        out = []
        for p in path:
            out.append({
                "x": p["x"] * scale_x,
                "y": p["y"] * scale_y
            })
        return out

    def _bbox_with_padding(self, pts, w, h, pad=50):
        """Compute bbox of points with padding, clamped to frame bounds."""
        xs = [int(p["x"]) for p in pts]
        ys = [int(p["y"]) for p in pts]
        x1 = max(0, min(xs) - pad)
        y1 = max(0, min(ys) - pad)
        x2 = min(w, max(xs) + pad)
        y2 = min(h, max(ys) + pad)
        # Ensure non-empty crop
        if x2 <= x1: x2 = min(w, x1 + 1)
        if y2 <= y1: y2 = min(h, y1 + 1)
        return x1, y1, x2, y2

    def _get_frame_at(self, video_path, timestamp_seconds):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            frame = cv2.resize(frame, (self.target_width, self.target_height), interpolation=cv2.INTER_LANCZOS4)
            return frame
        finally:
            cap.release()

    def _save_jpg(self, path, img):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])

    def _safe_crop(self, frame, x, y, crop_size=256):
        if x is None or y is None:
            return frame
        h, w = frame.shape[:2]
        half = crop_size // 2
        x1, y1 = max(0, x - half), max(0, y - half)
        x2, y2 = min(w, x + half), min(h, y + half)
        return frame[y1:y2, x1:x2]

    def _primary_point_from_coords(self, coords):
        if not coords:
            return None
        if isinstance(coords, list):
            c = coords[0]
        elif isinstance(coords, dict):
            c = next(iter(coords.values()))
        else:
            return None
        return int(c.get("x", 0)), int(c.get("y", 0))

    def _parse_config_resolution(self, actions):
        for a in actions:
            if (a.get("action") or "").startswith("CONFIG"):
                monitors = a.get("coords", {})
                # Prefer primary monitor "0"; fallback to any
                primary = monitors.get("0") if isinstance(monitors, dict) else None
                if primary is None and isinstance(monitors, dict) and monitors:
                    primary = next(iter(monitors.values()))

                if not primary:
                    return None, None

                width = primary.get("width")
                height = primary.get("height")
                sf = primary.get("scale_factor", 1.0) or 1.0

                # Use *logical* resolution as base for coords / video
                logical_w = int(round(width / sf))
                logical_h = int(round(height / sf))

                return logical_w, logical_h

        return None, None

    def scale_coordinates(self, coords, scale_x, scale_y):
        if not coords:
            return coords
        # Only handle list of dicts with x/y
        if isinstance(coords, list):
            out = []
            for c in coords:
                if isinstance(c, dict) and ("x" in c) and ("y" in c):
                    out.append({"x": c["x"] * scale_x, "y": c["y"] * scale_y})
            # If we got valid points, return them; else fall back to original
            return out if out else coords
        # e.g. CONFIG block uses a dict schema; leave it as-is
        return coords

    def process_actions(self, actions, video_path, screenshots_path, need_scaling, scale_x, scale_y):
        updated = []
        for a in actions:
            act_str = (a.get("action") or "").strip()
            if act_str == "CONFIG" or act_str.startswith("Active Window"):
                continue
            ua = a.copy()
            raw_coords = a.get('coords')
            ua['coords'] = self.scale_coordinates(raw_coords, scale_x, scale_y) if need_scaling else raw_coords
            if act_str == "DragStart at" and "path" in a and isinstance(a["path"], list):
                ua["path"] = self.scale_path(a["path"], scale_x, scale_y) if need_scaling else a["path"]
            else:
                ua["path"] = None
            timestamp = abs(a['timestamp']-0.1)
            base = f"{timestamp:.3f}s"
            full_fn = f"{base}.jpg"
            crop_fn = f"{base}.crop.jpg"

            full_path = screenshots_path / full_fn
            crop_path = screenshots_path / crop_fn

            frame = self._get_frame_at(video_path, timestamp)
            if frame is None:
                ua['screenshot_full'] = None
                ua['screenshot_crop'] = None
                updated.append(ua)
                continue

            H, W = frame.shape[:2]
            pt = self._primary_point_from_coords(ua.get('coords'))
            actt = act_str.lower()
            no_coor = ("scroll" in actt) or ("wheel" in actt) or ("hotkey" in actt) or ("type" in actt) or ("presss" in actt)

            if act_str == "DragStart at" and ua.get('path') and len(ua['path']) >= 2:
                # === DragStart special handling ===
                # Full image: UNCHANGED
                full_ok = self._save_jpg(str(full_path), frame)

                # Compute tight bbox around path with 25px padding
                x1, y1, x2, y2 = self._bbox_with_padding(ua['path'], W, H, pad=25)
                crop_region = frame[y1:y2, x1:x2].copy()

                # Prepare polyline points relative to crop
                pts = []
                for p in ua['path']:
                    px = int(round(p["x"])) - x1
                    py = int(round(p["y"])) - y1
                    pts.append([px, py])
                # Simplify to "best-fit" polyline using approxPolyDP
                pts_arr = cv2.approxPolyDP(
                    np.array(pts, dtype=np.int32), epsilon=2.0, closed=False
                )
                if pts_arr.ndim == 3:
                    pts_arr = pts_arr.reshape(-1, 2)
                # Draw the simplified polyline in RED
                for i in range(1, len(pts_arr)):
                    cv2.line(
                        crop_region,
                        tuple(pts_arr[i - 1]),
                       tuple(pts_arr[i]),
                        (0, 0, 255),
                        max(2, self.x_thick)  # a bit thicker for visibility
                    )

                crop_ok = self._save_jpg(str(crop_path), crop_region)
            elif (no_coor):
                full_ok = self._save_jpg(str(full_path), frame)
                crop_ok = self._save_jpg(str(crop_path), frame)
            else:
                # === Default handling (pad crop first, then draw centered semi-transparent X) ===
                draw_frame = frame.copy()

                # 1) Crop around click with black padding (keeps center fixed, no shifting)
                cx_raw, cy_raw = (pt if pt else (None, None))
                crop_img = self._crop_with_black_padding(draw_frame, cx_raw, cy_raw, crop_size=self.crop_size)

                # 2) Draw semi-transparent X AFTER padding so it's fully visible
                if pt:
                    # X centered in the crop
                    cx = cy = self.crop_size // 2
                    outline = self.x_thick + 2
                    # ensure the whole X (including outline) fits inside the crop
                    max_half = (self.crop_size // 2) - 1 - outline
                    half_x = max(1, min(self.x_size // 2, max_half))

                    overlay = crop_img.copy()
                    # white outline
                    cv2.line(overlay, (cx - half_x, cy - half_x), (cx + half_x, cy + half_x), (255, 255, 255), outline)
                    cv2.line(overlay, (cx - half_x, cy + half_x), (cx + half_x, cy - half_x), (255, 255, 255), outline)
                    # red core
                    cv2.line(overlay, (cx - half_x, cy - half_x), (cx + half_x, cy + half_x), (0, 0, 255), self.x_thick)
                    cv2.line(overlay, (cx - half_x, cy + half_x), (cx + half_x, cy - half_x), (0, 0, 255), self.x_thick)
                    # blend 50%
                    crop_img = cv2.addWeighted(overlay, 0.5, crop_img, 0.5, 0)

                full_ok = self._save_jpg(str(full_path), frame)
                crop_ok = self._save_jpg(str(crop_path), crop_img)


            ua['screenshot_full'] = f"screenshots/{full_fn}" if full_ok else None
            ua['screenshot_crop'] = f"screenshots/{crop_fn}" if crop_ok else None

            updated.append(ua)
        return updated
    
    def _crop_with_black_padding(self, frame, x, y, crop_size=256):
        if x is None or y is None:
            return frame

        h, w = frame.shape[:2]
        half = crop_size // 2

        # desired box
        x1 = int(x) - half
        y1 = int(y) - half
        x2 = x1 + crop_size
        y2 = y1 + crop_size

        # compute bounds and padding
        pad_left   = max(0, -x1)
        pad_top    = max(0, -y1)
        pad_right  = max(0,  x2 - w)
        pad_bottom = max(0,  y2 - h)

        x1c = max(0, x1)
        y1c = max(0, y1)
        x2c = min(w, x2)
        y2c = min(h, y2)

        crop = frame[y1c:y2c, x1c:x2c]

        # fill missing area with black canvas
        if pad_left or pad_top or pad_right or pad_bottom:
            crop = cv2.copyMakeBorder(
                crop, pad_top, pad_bottom, pad_left, pad_right,
                borderType=cv2.BORDER_CONSTANT, value=(0, 0, 0)
            )

        # ensure final shape
        if crop.shape[:2] != (crop_size, crop_size):
            crop = cv2.resize(crop, (crop_size, crop_size), interpolation=cv2.INTER_AREA)

        return crop


    def process_project(self, project_name):
        # --- Normalize input path ---
        project_path = Path(project_name)

        # If user passed only the name (e.g., "mathQuiz"), try to locate under ./projects/
        if not project_path.exists():
            possible_root = Path.cwd() / "projects" / project_name
            if possible_root.exists():
                project_path = possible_root
            else:
                raise FileNotFoundError(
                    f"Project folder not found: {project_path}\n"
                    f"Tried also: {possible_root}"
                )

        project_dir = project_path.resolve()
        inputs_dir = project_dir / "inputs"

        if not inputs_dir.exists():
            raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")

        # --- Locate video (with fallback search) ---
        preferred_name = project_dir.name.lower().replace("-", "_")
        candidate_videos = sorted(inputs_dir.glob("*.mp4"))
        video_path = None

        for v in candidate_videos:
            v_name = v.stem.lower().replace("-", "_")
            if v_name == preferred_name:
                video_path = v
                break

        if video_path is None:
            if not candidate_videos:
                raise FileNotFoundError(f"No .mp4 files found in {inputs_dir}")
            elif len(candidate_videos) == 1:
                video_path = candidate_videos[0]
                print(f"[Info] Using fallback video: {video_path.name}")
            else:
                candidate_videos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                video_path = candidate_videos[0]
                all_names = ", ".join(v.name for v in candidate_videos)
                print(f"[Warning] No exact match for '{preferred_name}.mp4'; using most recent: {video_path.name}")
                print(f"[Warning] All candidates: {all_names}")

        # --- Locate processed log (strict naming) ---
        log_path = project_dir / f"{project_dir.name}_processed_log.json"
        if not log_path.exists():
            raise FileNotFoundError(f"Processed log not found: {log_path}")

        screenshots_dir = project_dir / "screenshots"

        # --- Load actions ---
        with open(log_path, "r", encoding="utf-8") as f:
            actions = json.load(f)

        ow, oh = self._parse_config_resolution(actions)
        if ow is None or oh is None:
            raise ValueError("Could not find screen resolution in the CONFIG action")

        frame_w, frame_h = self.target_width, self.target_height
        need_scaling = not (ow == frame_w and oh == frame_h)
        scale_x = frame_w / ow if ow else 1.0
        scale_y = frame_h / oh if oh else 1.0

        updated_actions = self.process_actions(
            actions, video_path, screenshots_dir, need_scaling, scale_x, scale_y
        )
        out_json_sc = project_dir / f"{project_dir.name}_processed_log_sc.json"
        with open(out_json_sc, "w", encoding="utf-8") as f:
            json.dump(updated_actions, f, ensure_ascii=False, indent=2)

        meta = {
            "video_file": str(video_path),
            "log_file": str(log_path),
            "coordinate_scaling": need_scaling,
            "original_resolution": f"{ow}x{oh}" if ow and oh else "unknown",
            "target_resolution": f"{frame_w}x{frame_h}",
            "saved_log_sc": str(out_json_sc)
        }

        return updated_actions, screenshots_dir, meta
    
if __name__ == "__main__":
    import argparse
    import traceback
    import sys

    parser = argparse.ArgumentParser(description="Extract screenshots from project recordings.")
    parser.add_argument(
        "project_name",
        help="Project name or full path to the project folder (e.g., 'mathQuiz' or 'projects/mathQuiz')."
    )
    args = parser.parse_args()

    extractor = VideoScreenshotExtractor()

    try:
        actions, shots_dir, meta = extractor.process_project(args.project_name)
        print("\n=== Screenshot Extraction Complete ===")
        print(f"Project: {args.project_name}")
        print(f"Video File: {meta.get('video_file')}")
        print(f"Log File: {meta.get('log_file')}")
        print(f"Original Resolution: {meta.get('original_resolution')}")
        print(f"Target Resolution: {meta.get('target_resolution')}")
        print(f"Screenshots saved in: {shots_dir}")
        print(f"Updated log (with screenshot paths) saved to: {meta.get('saved_log_sc')}")
        print("=====================================\n")

    except Exception as e:
        print("\n!!! Extraction failed !!!")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")
        print("\n--- Full traceback ---")
        traceback.print_exc()
        print("----------------------\n")
        sys.exit(1)


