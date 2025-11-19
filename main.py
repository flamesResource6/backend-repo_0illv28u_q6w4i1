import os
from datetime import datetime, timedelta, timezone, date
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from database import db, create_document, get_documents

app = FastAPI(title="AI Attendance Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Utility ----------

def utc_start_end_for_day(day: Optional[date] = None):
    d = day or datetime.utcnow().date()
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def serialize_doc(doc: Dict[str, Any]):
    if not doc:
        return doc
    out = {**doc}
    if "_id" in out:
        out["id"] = str(out.pop("_id"))
    # Stringify any nested ObjectIds just in case
    for k, v in list(out.items()):
        try:
            from bson import ObjectId  # type: ignore
            if isinstance(v, ObjectId):
                out[k] = str(v)
        except Exception:
            pass
    return out


# ---------- Schemas for requests ----------

class RoomIn(BaseModel):
    name: str
    camera_url: Optional[str] = None
    is_active: bool = True


class StudentIn(BaseModel):
    name: str
    roll_no: Optional[str] = None
    room_id: Optional[str] = None
    photo_url: Optional[str] = None
    encoding: Optional[List[float]] = None


class AttendanceMarkIn(BaseModel):
    student_id: str
    room_id: str
    timestamp: Optional[datetime] = None
    source: str = Field("agent", description="agent|manual|api")


class ManualOverrideIn(BaseModel):
    student_id: str
    room_id: str


class UnknownFaceIn(BaseModel):
    room_id: str
    timestamp: Optional[datetime] = None
    snapshot_b64: Optional[str] = None
    note: Optional[str] = None


# ---------- Basic ----------

@app.get("/")
def read_root():
    return {"message": "AI Attendance Backend running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# ---------- Rooms ----------

@app.post("/rooms")
def create_room(room: RoomIn):
    room_id = create_document("room", room.dict())
    created = db["room"].find_one({"_id": db["room"].inserted_id}) if False else db["room"].find_one({"_id": __import__("bson").ObjectId(room_id)})
    return serialize_doc(created)


@app.get("/rooms")
def list_rooms():
    rooms = get_documents("room")
    return [serialize_doc(r) for r in rooms]


# ---------- Students ----------

@app.post("/students")
def create_student(student: StudentIn):
    student_id = create_document("student", student.dict())
    created = db["student"].find_one({"_id": __import__("bson").ObjectId(student_id)})
    return serialize_doc(created)


@app.get("/students")
def list_students(room_id: Optional[str] = None):
    filt = {"room_id": room_id} if room_id else {}
    students = get_documents("student", filt)
    return [serialize_doc(s) for s in students]


# ---------- Attendance ----------

@app.post("/attendance/mark")
def mark_attendance(payload: AttendanceMarkIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    ts = payload.timestamp or datetime.utcnow().replace(tzinfo=timezone.utc)
    start, end = utc_start_end_for_day(ts.date())

    # Ensure single mark per day per student per room
    existing = db["attendance"].find_one({
        "student_id": payload.student_id,
        "room_id": payload.room_id,
        "timestamp": {"$gte": start, "$lt": end},
    })
    if existing:
        return serialize_doc(existing)

    doc = {
        "student_id": payload.student_id,
        "room_id": payload.room_id,
        "timestamp": ts,
        "source": payload.source or "agent",
    }
    new_id = db["attendance"].insert_one(doc).inserted_id
    created = db["attendance"].find_one({"_id": new_id})
    return serialize_doc(created)


@app.post("/attendance/manual")
def manual_override(payload: ManualOverrideIn):
    return mark_attendance(AttendanceMarkIn(student_id=payload.student_id, room_id=payload.room_id, source="manual"))


@app.get("/attendance/today")
def attendance_today(room_id: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    start, end = utc_start_end_for_day()
    filt: Dict[str, Any] = {"timestamp": {"$gte": start, "$lt": end}}
    if room_id:
        filt["room_id"] = room_id
    rows = list(db["attendance"].find(filt))
    return [serialize_doc(r) for r in rows]


@app.get("/attendance/export.csv")
def export_attendance_csv(date_str: Optional[str] = Query(None, description="YYYY-MM-DD"), room_id: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    else:
        d = datetime.utcnow().date()

    start, end = utc_start_end_for_day(d)
    filt: Dict[str, Any] = {"timestamp": {"$gte": start, "$lt": end}}
    if room_id:
        filt["room_id"] = room_id

    rows = list(db["attendance"].find(filt))

    # Build CSV
    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["student_id", "student_name", "room_id", "room_name", "timestamp", "source"]) 

    # Create lookup maps for names
    student_ids = {r.get("student_id") for r in rows}
    room_ids = {r.get("room_id") for r in rows}
    students_map = {str(s["_id"]): s for s in db["student"].find({"_id": {"$in": [__import__("bson").ObjectId(sid) for sid in student_ids if sid]}})} if student_ids else {}
    rooms_map = {str(rm["_id"]): rm for rm in db["room"].find({"_id": {"$in": [__import__("bson").ObjectId(rid) for rid in room_ids if rid]}})} if room_ids else {}

    for r in rows:
        sid = r.get("student_id")
        rid = r.get("room_id")
        s_name = students_map.get(sid, {}).get("name", "")
        r_name = rooms_map.get(rid, {}).get("name", "")
        writer.writerow([
            sid or "",
            s_name,
            rid or "",
            r_name,
            (r.get("timestamp") or datetime.utcnow()).isoformat(),
            r.get("source", "agent"),
        ])

    buffer.seek(0)
    filename = f"attendance_{d.isoformat()}" + (f"_{room_id}" if room_id else "") + ".csv"
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------- Unknown faces ----------

@app.post("/unknown")
def log_unknown(payload: UnknownFaceIn):
    ts = payload.timestamp or datetime.utcnow().replace(tzinfo=timezone.utc)
    doc = {"room_id": payload.room_id, "timestamp": ts, "snapshot_b64": payload.snapshot_b64, "note": payload.note}
    new_id = db["unknown"].insert_one(doc).inserted_id
    return serialize_doc(db["unknown"].find_one({"_id": new_id}))


# ---------- Dashboard status ----------

@app.get("/dashboard/status")
def dashboard_status():
    # Rooms
    rooms = list(db["room"].find({}))
    start, end = utc_start_end_for_day()

    # Attendance today
    todays = list(db["attendance"].find({"timestamp": {"$gte": start, "$lt": end}}))

    # Build present-by-room map
    present_by_room: Dict[str, List[str]] = {}
    for a in todays:
        rid = a.get("room_id")
        sid = a.get("student_id")
        if rid and sid:
            present_by_room.setdefault(rid, [])
            if sid not in present_by_room[rid]:
                present_by_room[rid].append(sid)

    # Student counts per room
    room_ids = [str(r["_id"]) for r in rooms]
    students = list(db["student"].find({"room_id": {"$in": room_ids}}))
    students_by_room: Dict[str, List[Dict[str, Any]]] = {}
    for s in students:
        rid = s.get("room_id")
        students_by_room.setdefault(rid, []).append(s)

    # Compose response
    status = []
    for r in rooms:
        rid = str(r["_id"])
        total = len(students_by_room.get(rid, []))
        present_ids = present_by_room.get(rid, [])
        status.append({
            "id": rid,
            "name": r.get("name"),
            "present_count": len(present_ids),
            "total": total,
        })

    return {"rooms": status}


# ---------- Minimal schema endpoint (for reference) ----------

@app.get("/schema")
def schema_overview():
    return {
        "room": {"fields": ["name", "camera_url", "is_active"]},
        "student": {"fields": ["name", "roll_no", "room_id", "photo_url", "encoding"]},
        "attendance": {"fields": ["student_id", "room_id", "timestamp", "source"]},
        "unknown": {"fields": ["room_id", "timestamp", "snapshot_b64", "note"]},
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
