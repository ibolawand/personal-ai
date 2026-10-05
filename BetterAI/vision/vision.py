"""
aria_vision.py — Face Recognition using DB-backed profiles
===========================================================
All face data stored in aria_memory.db via AriaMemory.
No more separate model.yml / labels.pkl files.

Requires:
    pip install opencv-contrib-python
"""
import base64

import cv2
import numpy as np
import os
import threading
import time
from collections import Counter

import ollama

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACES_DIR    = os.path.join(PROJECT_ROOT, "aria_faces")
MODEL_PATH   = os.path.join(FACES_DIR, "model.yml")
CONFIDENCE_THRESHOLD = 75   # lower = stricter match
CAMERA_INDEX = 1

# How many consecutive frames must agree before we fire a callback
RECOGNITION_CONFIRM_FRAMES = 8


class AriaVision:
    def __init__(self, on_known_user, on_unknown_user, on_user_gone, memory, is_user_known=False):
        self.on_known_user   = on_known_user
        self.on_unknown_user = on_unknown_user
        self.on_user_gone    = on_user_gone
        self.memory          = memory
        self._present        = False
        self._running        = False
        self._current_user   = None

        os.makedirs(FACES_DIR, exist_ok=True)

        self._detector   = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._recogniser = cv2.face.LBPHFaceRecognizer_create()
        self._trained    = False
        self._label_map  = {}

        self._load_model()

    # ── Model ─────────────────────────────────────────────────────────────────

    def _load_model(self):
        profiles = self.memory.get_face_profiles()
        if not profiles:
            print("[Vision] No face profiles in DB yet — run learn_face() first")
            return

        self._label_map = profiles

        all_faces  = []
        all_labels = []

        for label_id, name in profiles.items():
            profile    = self.memory.get_face_profile_by_name(name)
            sample_dir = profile[1] if profile else os.path.join(FACES_DIR, name)
            if not os.path.exists(sample_dir):
                print(f"[Vision] ⚠  Sample dir missing for {name}: {sample_dir}")
                continue
            for fname in os.listdir(sample_dir):
                img_path = os.path.join(sample_dir, fname)
                img      = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    all_faces.append(cv2.resize(img, (200, 200)))
                    all_labels.append(label_id)

        if all_faces:
            self._recogniser.train(all_faces, np.array(all_labels, dtype=np.int32))
            self._trained = True
            print(f"[Vision] Loaded {len(profiles)} profile(s): {list(profiles.values())}")
        else:
            print("[Vision] ⚠  No sample images found — re-run learn_face()")

    def _save_model(self):
        os.makedirs(FACES_DIR, exist_ok=True)
        self._recogniser.write(MODEL_PATH)

    # ── Learning ──────────────────────────────────────────────────────────────

    def learn_face(self, name: str, samples: int = 40):
        print(f"\n[Vision] Learning face for '{name}'")

        existing = self.memory.get_face_profile_by_name(name)
        if existing:
            label_id   = existing[0]
            sample_dir = existing[1]
        else:
            label_id   = self.memory.get_next_label_id()
            sample_dir = os.path.join(FACES_DIR, name)

        os.makedirs(sample_dir, exist_ok=True)

        cap   = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        count = 0

        while count < samples:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            dets = self._detector.detectMultiScale(
                gray, scaleFactor=1.03, minNeighbors=2, minSize=(30, 30)
            )

            for (x, y, w, h) in dets:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"Samples: {count}/{samples}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow("Learning face - press Q to cancel", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            for (x, y, w, h) in dets:
                face     = cv2.resize(gray[y:y + h, x:x + w], (200, 200))
                img_path = os.path.join(sample_dir, f"{count:04d}.jpg")
                cv2.imwrite(img_path, face)
                count   += 1
                print(f"  Sample {count}/{samples} captured ✓")
                if count >= samples:
                    break

            time.sleep(0.05)

        cap.release()
        cv2.destroyAllWindows()
        self.memory.save_face_profile(name, label_id, sample_dir)
        self._label_map[label_id] = name
        self._load_model()
        print(f"\n[Vision] ✅ Face '{name}' saved with {count} samples")

    def forget_face(self, name: str):
        profile = self.memory.delete_face_profile(name)
        if profile:
            sample_dir = profile[1]
            if os.path.exists(sample_dir):
                import shutil
                shutil.rmtree(sample_dir)
                print(f"[Vision] Deleted samples for '{name}'")
        self._label_map = self.memory.get_face_profiles()
        self._load_model()
        print(f"[Vision] Profile '{name}' removed")

    def list_known_faces(self) -> list:
        return list(self.memory.get_face_profiles().values())

    # ── Detection Loop ────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        print("👁  Vision started")

    def stop(self):
        self._running = False

    def _loop(self):
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print("⚠  No camera found — vision disabled")
            return

        consecutive_empty   = 0
        consecutive_full    = 0
        CONFIRM_PRESENT     = 4
        CONFIRM_GONE        = 15

        # Rolling buffer of recent recognition results for stability
        recent_results = []

        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            dets = self._detector.detectMultiScale(
                gray, scaleFactor=1.03, minNeighbors=2, minSize=(30, 30)
            )

            if len(dets) > 0:
                consecutive_empty  = 0
                consecutive_full  += 1

                if consecutive_full >= CONFIRM_PRESENT:
                    x, y, w, h = dets[0]
                    face = cv2.resize(gray[y:y + h, x:x + w], (200, 200))
                    name = self._recognise(face)

                    # Add to rolling buffer
                    recent_results.append(name)
                    if len(recent_results) > RECOGNITION_CONFIRM_FRAMES:
                        recent_results.pop(0)

                    # Only fire callback when buffer is full and majority agree
                    if len(recent_results) == RECOGNITION_CONFIRM_FRAMES:
                        counts  = Counter(recent_results)
                        top_name, top_count = counts.most_common(1)[0]

                        # Need 75% agreement to be confident
                        if top_count >= RECOGNITION_CONFIRM_FRAMES * 0.75:
                            if top_name != self._current_user:
                                self._current_user = top_name
                                self._present      = True

                                if top_name:
                                    label_id = self._get_label_id(top_name)
                                    if label_id:
                                        self.memory.record_face_seen(label_id)
                                        self.memory.forget_like("User's name is%")
                                        self.memory.save_memory(f"User's name is {top_name}")
                                    if self.on_known_user:
                                        self.on_known_user(top_name)
                                else:
                                    # Unknown — only fire if we haven't already
                                    # fired for this presence event
                                    if self._present is not True or self._current_user is not None:
                                        if self.on_unknown_user:
                                            self.on_unknown_user()

            else:
                consecutive_full   = 0
                consecutive_empty += 1
                recent_results.clear()  # reset buffer when face disappears

                if consecutive_empty >= CONFIRM_GONE and self._present:
                    self._present      = False
                    self._current_user = None
                    if self.on_user_gone:
                        self.on_user_gone()

            time.sleep(0.2)

        cap.release()

    def describe_current_frame(self) -> str:
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            return "I can't access the camera right now."

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dets = self._detector.detectMultiScale(gray, scaleFactor=1.03, minNeighbors=2, minSize=(30, 30))

        recognized_name = None
        if len(dets) > 0 and self._trained:
            x, y, w, h  = dets[0]
            face         = cv2.resize(gray[y:y + h, x:x + w], (200, 200))
            recognized_name = self._recognise(face)

        _, buffer   = cv2.imencode('.jpg', frame)
        img_base64  = base64.b64encode(buffer).decode('utf-8')

        try:
            response = ollama.chat(
                model="llava",
                messages=[{
                    "role": "user",
                    "content": "Describe what you see briefly. If there's a person, describe their appearance.",
                    "images": [img_base64]
                }]
            )
            description = response['message']['content']
        except Exception as e:
            return f"Vision error: {e}"

        if recognized_name:
            return f"I can see {recognized_name}. {description}"
        else:
            return f"I don't recognize who this is. {description}"

    def _recognise(self, face_gray) -> str | None:
        """Returns name if recognised with enough confidence, else None."""
        if not self._trained or not self._label_map:
            return None
        try:
            label, confidence = self._recogniser.predict(face_gray)
            if confidence < CONFIDENCE_THRESHOLD:
                return self._label_map.get(label)
            return None
        except Exception:
            return None

    def _get_label_id(self, name: str):
        for lid, n in self._label_map.items():
            if n == name:
                return lid
        return None

    @property
    def current_user(self):
        return self._current_user

    @property
    def is_present(self):
        return self._present