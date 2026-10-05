import rtmidi
import os

# Check MIDI ports
midi_out = rtmidi.MidiOut()
print("MIDI ports:", midi_out.get_ports())

# Check midi folder
print("midi/ exists:", os.path.exists("midi"))
if os.path.exists("midi"):
    print("files:", os.listdir("midi"))