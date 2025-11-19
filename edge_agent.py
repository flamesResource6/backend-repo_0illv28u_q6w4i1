import argparse
import time
import base64
from datetime import datetime

import cv2
import numpy as np
import requests

# Optional: import face_recognition with a helpful error if missing
try:
    import face_recognition
except Exception as e:
    raise SystemExit("face_recognition is required. Install with: pip install face_recognition opencv-python numpy requests\nError: " + str(e))


def load_known_faces(backend_url: str):
    resp = requests.get(f"{backend_url}/students")
    resp.raise_for_status()
    students = resp.json()
    known_encodings = []
    known_ids = []
    known_names = []
    for s in students:
        enc = s.get("encoding")
        if enc and isinstance(enc, list) and len(enc) >= 128:
            known_encodings.append(np.array(enc))
            known_ids.append(s.get("id") or s.get("_id"))
            known_names.append(s.get("name"))
    return known_encodings, known_ids, known_names


def mark_present(backend_url: str, student_id: str, room_id: str, source: str = "agent"):
    try:
        requests.post(f"{backend_url}/attendance/mark", json={
            "student_id": student_id,
            "room_id": room_id,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
        }, timeout=5)
    except Exception:
        pass


def log_unknown(backend_url: str, room_id: str, snapshot_b64: str):
    try:
        requests.post(f"{backend_url}/unknown", json={
            "room_id": room_id,
            "snapshot_b64": snapshot_b64,
        }, timeout=5)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Edge Agent for AI Attendance (per room)")
    parser.add_argument("--backend", required=True, help="Backend base URL, e.g., http://localhost:8000")
    parser.add_argument("--room-id", required=True, help="Room ID (from backend)")
    parser.add_argument("--camera", default="0", help="Camera index or RTSP/HTTP URL")
    parser.add_argument("--scale", type=float, default=0.25, help="Frame downscale for faster processing (0.25 recommended)")
    parser.add_argument("--tolerance", type=float, default=0.5, help="Face match tolerance (lower is stricter)")
    parser.add_argument("--unknown", action="store_true", help="Log unknown faces to backend")
    args = parser.parse_args()

    backend = args.backend.rstrip('/')

    # Open camera
    cam_source = 0
    if args.camera.isdigit():
        cam_source = int(args.camera)
    else:
        cam_source = args.camera

    cap = cv2.VideoCapture(cam_source)
    if not cap.isOpened():
        raise SystemExit("Could not open camera " + str(args.camera))

    known_encodings, known_ids, known_names = load_known_faces(backend)
    print(f"Loaded {len(known_encodings)} known encodings")

    last_mark = {}

    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue

        # Resize for speed
        small = cv2.resize(frame, (0, 0), fx=args.scale, fy=args.scale)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_small)
        face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

        for enc, (top, right, bottom, left) in zip(face_encodings, face_locations):
            if len(known_encodings) > 0:
                matches = face_recognition.compare_faces(known_encodings, enc, tolerance=args.tolerance)
                face_distances = face_recognition.face_distance(known_encodings, enc)
                best_match_index = np.argmin(face_distances) if len(face_distances) else None
            else:
                matches = []
                best_match_index = None

            name_to_show = "Unknown"
            student_id = None

            if best_match_index is not None and matches[best_match_index]:
                student_id = known_ids[best_match_index]
                name_to_show = known_names[best_match_index]

                # Rate limit marking to once per 10 seconds per student
                now = time.time()
                if now - last_mark.get(student_id, 0) > 10:
                    mark_present(backend, student_id, args.room_id)
                    last_mark[student_id] = now
            else:
                if args.unknown:
                    # Crop and encode snapshot
                    t, r, b, l = int(top/args.scale), int(right/args.scale), int(bottom/args.scale), int(left/args.scale)
                    crop = frame[t:b, l:r]
                    _, buf = cv2.imencode('.jpg', crop)
                    b64 = base64.b64encode(buf).decode('utf-8')
                    log_unknown(backend, args.room_id, b64)

            # Draw rectangle (optional for local preview)
            t, r, b, l = int(top/args.scale), int(right/args.scale), int(bottom/args.scale), int(left/args.scale)
            cv2.rectangle(frame, (l, t), (r, b), (0, 255, 0) if student_id else (0, 0, 255), 2)
            cv2.putText(frame, name_to_show, (l, t - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Show window for local monitoring
        cv2.imshow('Attendance - Room', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
