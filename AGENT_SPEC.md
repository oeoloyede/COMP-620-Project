# Cyber Detective — Llama Agent Build Specification

## 1. Project Purpose
Build **Cyber Detective**, an interactive, browser-based cybersecurity training game where players act as security investigators for a fictional organization[cite: 1, 2]. Learners examine simulated digital evidence, log notes, make investigative decisions, and submit conclusions[cite: 2].

## 2. Hard Safety & Scope Rules (Non-Negotiable)
- **Simulated & Safe Data Only:** Use strictly fictional users, documentation-safe network addresses (e.g., `192.0.2.x`, `198.51.100.x`, `203.0.113.x`, `10.x.x.x`), fake domains (`example.com`, `acme-corp.test`), and simulated malware indicators[cite: 1, 2].
- **No Offensive or Live Tooling:** Do NOT include executable malware, real vulnerability scanning, credential brute-forcing, phishing delivery, or live external threat-intel API calls[cite: 1, 2].
- **Deterministic Game Logic:** Scoring, hint progression, case unlocks, and correct answers must be deterministic and enforced on the server[cite: 2]. The game must run completely even if Ollama/Llama is offline[cite: 2].
- **No Hardcoded Secrets:** Never hardcode credentials or commit `.env` files[cite: 2].

## 3. Target Architecture
- **Backend (`/backend`):** Python + FastAPI + SQLite + Pytest[cite: 2].
- **Frontend (`/frontend`):** React + TypeScript[cite: 2].
- **Case Data (`/cases`):** JSON files separating investigation content from game engine logic[cite: 2].

### Planned Backend REST Endpoints
- `GET /cases` — List all cases, difficulty, and unlock/completion status[cite: 2].
- `GET /cases/{case_id}/evidence` — Return briefing, objectives, and simulated evidence items[cite: 2].
- `POST /cases/{case_id}/decision` — Evaluate player choice against stored JSON answers, update score, and return educational feedback[cite: 2].
- `POST /cases/{case_id}/hint` — Return progressive prewritten hints (Level 1: general direction -> Level 2: evidence category -> Level 3: specific evidence -> Level 4+: concept explanation) and deduct hint points[cite: 2].
- `POST /cases/{case_id}/complete` — Evaluate final conclusion, award completion bonus, unlock next case, and save progress to SQLite[cite: 2].
- `GET /player/progress` — Retrieve saved scores, completed cases, and investigation notebook entries[cite: 2].

## 4. Core Gameplay Features
1. **Case Management:** Load unlocked cases, reset temporary investigation state on start, and track progress[cite: 2].
2. **Evidence Viewer:** Display simulated emails, login logs, employee records, process lists, file metadata, network records, and security alerts[cite: 2]. Include both relevant clues and irrelevant distractor items; allow players to inspect and flag clues[cite: 1, 2].
3. **Investigation Notebook:** Let players record observations linked to specific `evidenceID` items and review them throughout the case[cite: 2].
4. **Decision, Feedback & Hint System:** Award points for identifying key clues and making correct decisions; apply penalties and show educational explanations for wrong choices[cite: 1, 2].
5. **Scoring Formula:**
   `score = evidence_points + decision_points - incorrect_penalties - hint_costs + completion_bonus`[cite: 2]

## 5. Required Cybersecurity Cases (In Order of Difficulty)
1. **The Suspicious Email:** Phishing & social engineering (sender headers, URLs, message content)[cite: 1, 2].
2. **The Midnight Login:** Authentication logs (timestamps, failed vs. successful logins, usernames, source IPs)[cite: 1, 2].
3. **The Compromised Workstation:** Simulated malware indicators (files, running processes, startup entries, outbound connections)[cite: 1, 2].
4. **Breach in the Network:** Network investigation (IPs, ports, protocols, security alerts, event timelines)[cite: 1, 2].
5. *(Optional)* **Operation Blackout:** Capstone case combining phishing, authentication, workstation, and network clues[cite: 1, 2].

## 6. Agent Execution Rules
- Work on one scoped module or case per run.
- Write or run automated tests (`pytest` for backend, TypeScript build/tests for frontend) after code changes[cite: 2].
- Never modify existing test assertions solely to force a passing build.
- Keep all generated files clean, modular, and documented for team code review.
