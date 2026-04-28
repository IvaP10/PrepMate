import base64
import logging
import threading
import asyncio
import os
import urllib.request
from typing import Dict, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from deepface import DeepFace

logger = logging.getLogger("body_language")

executor = ThreadPoolExecutor(max_workers=2)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "face_landmarker.task")


def _ensure_model():
    if os.path.exists(MODEL_PATH):
        return
    os.makedirs(MODEL_DIR, exist_ok=True)
    logger.info(f"Downloading FaceLandmarker model to {MODEL_PATH}...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    logger.info(f"Model downloaded ({os.path.getsize(MODEL_PATH) / 1024 / 1024:.1f}MB)")


_ensure_model()

base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
landmarker_options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.IMAGE,
    num_faces=1,
)
face_landmarker = vision.FaceLandmarker.create_from_options(landmarker_options)
face_landmarker_lock = threading.Lock()

_emotion_lock = threading.Lock()
_emotion_cache: Dict = {
    "emotion": "neutral",
    "confidence": 0.5,
    "timestamp": None,
}

_prev_landmarks_lock = threading.Lock()
_prev_landmarks: Optional[list] = None

EMOTION_INTERVAL = 12
FIDGET_THRESHOLD = 0.012


async def analyze_frame(
    frame_base64: str,
    frame_count: int,
    interview_mode: str = "mock",
) -> Dict:
    try:
        raw = base64.b64decode(frame_base64)
        nparr = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            raise ValueError("Failed to decode frame")

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        loop = asyncio.get_running_loop()
        mediapipe_results = await loop.run_in_executor(
            executor, lambda: _run_face_mesh(rgb)
        )

        if frame_count % EMOTION_INTERVAL == 0:
            await _refresh_emotion(rgb)

        with _emotion_lock:
            cached_emotion = dict(_emotion_cache)

        return _build_response(mediapipe_results, cached_emotion, interview_mode)

    except Exception:
        logger.exception("Frame analysis failed")
        return _error_fallback()


def _run_face_mesh(rgb_frame) -> Dict:
    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        with face_landmarker_lock:
            results = face_landmarker.detect(mp_image)

        if not results.face_landmarks:
            return {
                "face_detected": False,
                "gaze_direction": "unknown",
                "head_pose": "unknown",
                "eye_contact": False,
                "blink_detected": False,
                "engagement_score": 0,
                "fidget_level": "unknown",
                "fidget_score": 0.0,
            }

        landmarks = results.face_landmarks[0]
        h, w = rgb_frame.shape[:2]

        gaze = _gaze_direction(landmarks, w, h)
        head = _head_pose(landmarks, w, h)
        eye_contact = _is_looking_at_camera(gaze, head)
        blink = _is_blinking(landmarks)
        fidget = _fidget_level(landmarks)
        engagement = _engagement_score(gaze, head, eye_contact, fidget)

        return {
            "face_detected": True,
            "gaze_direction": gaze["direction"],
            "gaze_horizontal": gaze["horizontal"],
            "gaze_vertical": gaze["vertical"],
            "head_pose": head["pose"],
            "head_pitch": head["pitch"],
            "head_yaw": head["yaw"],
            "eye_contact": eye_contact,
            "blink_detected": blink,
            "engagement_score": engagement,
            "fidget_level": fidget["level"],
            "fidget_score": fidget["score"],
        }

    except Exception:
        logger.exception("FaceLandmarker pass failed")
        return {"face_detected": False, "engagement_score": 0, "fidget_level": "unknown", "fidget_score": 0.0}


def _gaze_direction(landmarks, w: int, h: int) -> Dict:
    left_iris = landmarks[468]
    right_iris = landmarks[473]
    left_inner = landmarks[133]
    left_outer = landmarks[33]
    right_inner = landmarks[362]
    right_outer = landmarks[263]

    left_cx = (left_inner.x + left_outer.x) / 2
    left_cy = (left_inner.y + left_outer.y) / 2
    right_cx = (right_inner.x + right_outer.x) / 2
    right_cy = (right_inner.y + right_outer.y) / 2

    left_dx = left_iris.x - left_cx
    left_dy = left_iris.y - left_cy
    right_dx = right_iris.x - right_cx
    right_dy = right_iris.y - right_cy

    horiz = ((left_dx + right_dx) / 2) * 10
    vert = ((left_dy + right_dy) / 2) * 10

    if abs(horiz) < 0.15 and abs(vert) < 0.15:
        direction = "center"
    elif horiz < -0.15:
        direction = "left"
    elif horiz > 0.15:
        direction = "right"
    elif vert < -0.15:
        direction = "up"
    elif vert > 0.15:
        direction = "down"
    else:
        direction = "center"

    return {
        "direction": direction,
        "horizontal": round(horiz, 3),
        "vertical": round(vert, 3),
    }


def _head_pose(landmarks, w: int, h: int) -> Dict:
    nose = landmarks[1]
    chin = landmarks[152]
    left_ear = landmarks[234]
    right_ear = landmarks[454]

    ear_diff = right_ear.x - left_ear.x
    yaw = float(np.clip((ear_diff - 0.1) * 5, -1, 1))

    nose_chin = chin.y - nose.y
    pitch = float(np.clip((nose_chin - 0.08) * 10, -1, 1))

    if abs(yaw) < 0.3 and abs(pitch) < 0.3:
        pose = "straight"
    elif yaw < -0.3:
        pose = "turned_left"
    elif yaw > 0.3:
        pose = "turned_right"
    elif pitch < -0.3:
        pose = "looking_up"
    elif pitch > 0.3:
        pose = "looking_down"
    else:
        pose = "slightly_off"

    return {"pose": pose, "yaw": round(yaw, 3), "pitch": round(pitch, 3)}


def _is_looking_at_camera(gaze: Dict, head: Dict) -> bool:
    gaze_centered = gaze["direction"] == "center"
    head_straight = head["pose"] in ("straight", "slightly_off")

    gaze_ok = abs(gaze["horizontal"]) < 0.25 and abs(gaze["vertical"]) < 0.25
    head_ok = abs(head["yaw"]) < 0.4 and abs(head["pitch"]) < 0.4

    return (gaze_centered and head_straight) or (gaze_ok and head_ok)


def _is_blinking(landmarks) -> bool:
    def ear(top, bot, left, right):
        height = abs(landmarks[top].y - landmarks[bot].y)
        width = abs(landmarks[right].x - landmarks[left].x)
        return height / (width + 1e-6)

    left = ear(159, 145, 33, 133)
    right = ear(386, 374, 263, 362)
    return (left + right) / 2 < 0.15


def _fidget_level(landmarks) -> Dict:
    global _prev_landmarks

    key_points = [1, 10, 152, 234, 454, 6, 197]
    current = [(landmarks[i].x, landmarks[i].y) for i in key_points]

    with _prev_landmarks_lock:
        prev = _prev_landmarks
        _prev_landmarks = current

    if prev is None or len(prev) != len(current):
        return {"level": "low", "score": 0.0}

    deltas = [abs(c[0] - p[0]) + abs(c[1] - p[1]) for c, p in zip(current, prev)]
    mean_delta = sum(deltas) / len(deltas)

    if mean_delta > FIDGET_THRESHOLD * 2:
        level = "high"
    elif mean_delta > FIDGET_THRESHOLD:
        level = "medium"
    else:
        level = "low"

    return {"level": level, "score": round(mean_delta, 5)}


def _engagement_score(gaze: Dict, head: Dict, eye_contact: bool, fidget: Dict) -> int:
    score = 50

    if eye_contact:
        score += 25
    elif gaze["direction"] == "center":
        score += 15

    if head["pose"] == "straight":
        score += 20
    elif head["pose"] == "slightly_off":
        score += 10

    if gaze["direction"] in ("left", "right", "down"):
        score -= 15

    if head["pose"] in ("turned_left", "turned_right", "looking_down"):
        score -= 10

    if fidget["level"] == "high":
        score -= 15
    elif fidget["level"] == "medium":
        score -= 5

    return max(0, min(100, score))


async def _refresh_emotion(rgb_frame):
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            executor,
            lambda: DeepFace.analyze(
                rgb_frame,
                actions=["emotion"],
                enforce_detection=False,
                detector_backend="opencv",
            ),
        )

        if result and len(result) > 0:
            emotions = result[0].get("emotion", {})
            dominant = result[0].get("dominant_emotion", "neutral")
            confidence = emotions.get(dominant, 0) / 100

            with _emotion_lock:
                _emotion_cache["emotion"] = dominant
                _emotion_cache["confidence"] = confidence
                _emotion_cache["timestamp"] = datetime.utcnow()

    except Exception:
        logger.exception("DeepFace emotion pass failed")


def _build_response(mp_data: Dict, emotion: Dict, mode: str) -> Dict:
    if not mp_data.get("face_detected"):
        return {
            "face_detected": False,
            "confidence": 20,
            "emotion": "unknown",
            "eye_contact": False,
            "posture": "not_visible",
            "engagement": 0,
            "fidget_level": "unknown",
            "feedback": ["Face not detected — ensure good lighting and camera position"],
        }

    confidence = mp_data.get("engagement_score", 50)
    detected_emotion = emotion.get("emotion", "neutral")
    emotion_conf = emotion.get("confidence", 0.5)

    emotion_weights = {
        "happy": 10, "neutral": 5, "surprised": 0,
        "sad": -10, "angry": -15, "fear": -20, "disgust": -10,
    }
    confidence += emotion_weights.get(detected_emotion, 0) * emotion_conf
    confidence = max(0, min(100, int(confidence)))

    fidget_level = mp_data.get("fidget_level", "low")

    feedback = []
    if mode == "practice":
        if not mp_data.get("eye_contact"):
            feedback.append("Try to maintain eye contact with the camera")
        if mp_data.get("head_pose") == "looking_down":
            feedback.append("Keep your head up and face the camera")
        if detected_emotion in ("fear", "sad", "angry"):
            feedback.append("Take a breath and stay composed")
        if mp_data.get("gaze_direction") in ("left", "right"):
            feedback.append("Avoid looking away frequently — it affects engagement")
        if fidget_level == "high":
            feedback.append("Try to sit still — excessive movement can be distracting")
        elif fidget_level == "medium":
            feedback.append("You're shifting around a bit — try to stay centered")
        if mp_data.get("eye_contact") and fidget_level == "low":
            feedback.append("Great body language — keep it up!")

    return {
        "face_detected": True,
        "confidence": confidence,
        "emotion": detected_emotion,
        "emotion_confidence": round(emotion_conf, 2),
        "eye_contact": mp_data.get("eye_contact", False),
        "gaze_direction": mp_data.get("gaze_direction", "unknown"),
        "posture": mp_data.get("head_pose", "unknown"),
        "head_yaw": mp_data.get("head_yaw", 0),
        "head_pitch": mp_data.get("head_pitch", 0),
        "engagement": mp_data.get("engagement_score", 0),
        "blink_detected": mp_data.get("blink_detected", False),
        "fidget_level": fidget_level,
        "fidget_score": mp_data.get("fidget_score", 0.0),
        "timestamp": datetime.utcnow().isoformat(),
        "analysis_method": "mediapipe_deepface",
        "feedback": feedback if mode == "practice" else [],
    }


def _error_fallback() -> Dict:
    return {
        "face_detected": False,
        "confidence": None,
        "emotion": None,
        "eye_contact": False,
        "posture": "unknown",
        "engagement": None,
        "fidget_level": "unknown",
        "analysis_method": "error_fallback",
        "feedback": [],
    }


def cleanup():
    if face_landmarker:
        face_landmarker.close()
    executor.shutdown(wait=False)
