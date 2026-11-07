import cv2

from database import AriaMemory
from vision.vision import AriaVision


def add_face(name, samples=40):
    memory = AriaMemory()
    vision = AriaVision(None, None, None, memory)

    samples = input("How many samples? (default 40): ").strip()
    samples = int(samples) if samples.isdigit() else 40
    vision.learn_face(name, samples=samples, show_window=True)

    # Verify it saved to DB
    profiles = memory.get_face_profiles()
    print(f"\n✅ DB now contains: {list(profiles.values())}")
    facts = memory.get_memories(5)
    print(f"✅ Memory facts: {facts}")


def main():
    add_face(input("Name: ").strip())



if __name__ == "__main__":
    main()
