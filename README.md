AI Attendance System (Multi-Room)

Overview
- Multi-room attendance with real-time face recognition at the edge (per-room laptop/mini PC) and a lightweight central backend + dashboard.
- Scales to 5+ rooms and ~100 students.
- Edge agents process IP/web cameras and POST attendance to the server.

Components
- Backend API (FastAPI + MongoDB): rooms, students, attendance, exports, dashboard status.
- Frontend dashboard (React + Tailwind): view live status per room and manually mark attendance.
- Edge Agent (Python + face_recognition + OpenCV): runs per room, recognizes faces from camera, calls the backend.

Prerequisites
- Python 3.10+
- MongoDB instance (DATABASE_URL + DATABASE_NAME)
- For Edge Agent only: Windows 10/11 recommended with CPU support; install Visual C++ Build Tools if needed for dlib/face_recognition.

Quick Start
1) Configure environment
- Set DATABASE_URL and DATABASE_NAME in an .env file for the backend.
- Set VITE_BACKEND_URL for the frontend when running locally (default http://localhost:8000).

2) Start services
- Use the included dev runner (handled by this environment). For your own machine:
  - Backend: pip install -r requirements.txt; uvicorn main:app --reload --port 8000
  - Frontend: npm install; npm run dev (port 3000)

3) Seed data
- Create 5 rooms with camera URLs (optional): POST /rooms
- Create students: POST /students (include optional room_id and encoding). Encoding can be uploaded later by the edge agent helper.

4) Run the Edge Agent per room
- Install dependencies for the agent:
  pip install face_recognition opencv-python numpy requests
- Run (example RTSP or webcam 0):
  python edge_agent.py --backend http://localhost:8000 --room-id <ROOM_ID> --camera 0

Exports
- CSV export for any date: GET /attendance/export.csv?date_str=YYYY-MM-DD&room_id=<optional>

Design Notes
- Heavy AI runs on local room machines; backend stays light for Railway/Vercel.
- Unknown faces are logged; you can review and convert to new students later.
- Manual overrides are supported from the dashboard.
