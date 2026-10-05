# Aria
 
Aria ist ein persönlicher KI-Assistent mit Backend und Mobile-App.

> [!NOTE]
> Mobile Version source code nicht im repo
 
## Architektur
 
```
Mobile App (React Native / Expo)
        │  HTTPS
        ▼
Cloudflare Tunnel
        │
        ▼
Backend (Python / FastAPI)
```
 
| Komponente | Technologie |
|---|---|
| Backend | Python, FastAPI |
| Mobile Frontend | React Native (Expo) |
| Audio-Wiedergabe | `expo-audio` |
| Erreichbarkeit von außen | Cloudflare Tunnel |
 
## Aktueller Stand
 
- Tunnel-Routing zwischen App und Backend funktioniert.
- Die Kommunikation App ↔ Backend läuft stabil (Parameter-Mismatch in FastAPI und fehlende Klassenmethode behoben).
## Bekannte Probleme
 
- **Audio-Wiedergabe auf Android** (getestet auf Samsung S24): Ursache noch offen. Verdächtig sind:
  - Timing des `expo-audio`-Players
  - Konfiguration über `setAudioModeAsync`
  - Fehler beim Schreiben der Audiodatei
## Ideen / Roadmap
 
- Öffentliches Web-Frontend mit Chat-Seite
- Anime-Avatar (Live2D, Cubism) mit Animationen statt reinem Textchat
- Offen: Schutz des Servers vor Überlastung bei öffentlichem Zugriff

