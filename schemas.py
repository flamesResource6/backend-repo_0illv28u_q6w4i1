"""
Database Schemas for AI Attendance System

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Room(BaseModel):
    name: str = Field(..., description="Room name e.g., Room 101")
    camera_url: Optional[str] = Field(None, description="RTSP/HTTP camera URL for reference")
    is_active: bool = Field(True, description="Whether room is actively tracked")

class Student(BaseModel):
    name: str = Field(..., description="Full name of the student")
    roll_no: Optional[str] = Field(None, description="Roll number / student ID")
    room_id: Optional[str] = Field(None, description="Assigned room ID if fixed; can be None for floating")
    photo_url: Optional[str] = Field(None, description="Reference photo URL (for dashboard display)")
    
    # Store one primary encoding; edge agent may maintain multiple, but we keep a canonical vector here
    encoding: Optional[List[float]] = Field(None, description="128-d face encoding vector from face_recognition")

class Attendance(BaseModel):
    room_id: str = Field(..., description="Room ID")
    student_id: str = Field(..., description="Student ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When attendance was captured (UTC)")
    source: str = Field("agent", description="Source of mark: agent/manual/api")

class UnknownFace(BaseModel):
    room_id: str = Field(..., description="Room ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    snapshot_b64: Optional[str] = Field(None, description="Optional base64 image snippet for later review")
    note: Optional[str] = Field(None)
