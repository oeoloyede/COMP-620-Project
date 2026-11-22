# Cyber Detective

Cyber Detective is a cybersecurity training game for COMP 620. In the first playable case, **The Suspicious Email**, an employee receives an urgent request for account credentials. Players inspect fictional email evidence, flag clues, document their reasoning, and choose how to protect the account.

## Play the demo

Install Python 3.10 or newer. From the repository root, run the command for your system.

| System | Launch |
| --- | --- |
| Windows | Double-click **Open Cyber Detective.cmd**, or run `py -3 -m backend.demo` |
| macOS or Linux | Run `python3 -m backend.demo` |

The demo uses the Python standard library and opens a local browser tab. Click **Start investigation**. Inspect the message and headers, flag relevant clues, and add an observation to the notebook. Choose a response and submit a conclusion explaining your reasoning. Hints cost points. The case runs offline, including when Ollama is unavailable.

The terminal prints the local URL. Keep it open while playing and press Ctrl+C to stop. SQLite saves the local demo player's progress across launches. Use **Play again** after completion for a fresh attempt. For an isolated presentation run, choose a fresh directory with `python -m backend.demo --data-dir ./practice-session` using your system's Python command.

## Build on the visual design

The current interface is a starting point for the team. If you have a different visual direction, you can redesign the entire investigation screen and keep the tested gameplay underneath it.

| What you want to change | Where to start |
| --- | --- |
| Colors, type, spacing, mobile layout, or the order of panels | Edit the HTML and CSS in [the demo template](frontend/demo.html). Refresh the browser to see changes. For example, you can move the notebook above the evidence on small screens by changing the mobile grid. |
| Evidence cards, notebook fields, answer choices, or button markup | Edit the form rendering in [the demo controller](backend/demo.py). Keep the form actions, input names, and hidden request token when changing markup. Restart the demo after Python edits. |
| A new React/TypeScript interface | Build the client in `frontend/` and add a FastAPI adapter around [GameEngine](backend/app/engine.py). The planned routes are in [the design spec](AGENT_SPEC.md). |
| Case clues, hints, or teaching content | Start from [the phishing case](cases/suspicious_email.json). The current demo selects this case and its first decision. Extend the case selector and decision rendering when adding the remaining cases. |

For a replacement UI, use `get_case_details` to supply player-visible evidence and choices. Keep the full case JSON on the server because it contains the answer key. Send player actions to the engine methods for flagging evidence, saving notes, requesting hints, evaluating decisions, and completing cases. Show the score and feedback returned by those methods. Use `get_player_progress` to resume an attempt after refresh. The engine owns scoring, answer checks, and case unlocks, so a teammate can change the look or navigation independently.

## Run the tests

From the repository root, use your Python interpreter to install pytest and run the suite.

```sh
python -m pip install "pytest>=8,<9"
python -m pytest -q
```

The tests cover clue scoring, repeat submissions, hint costs, notes, completion, case unlocks, and SQLite persistence. A walkthrough test plays the shipped JSON case through the engine and reloads the saved result.

## Project status

The local single-player demo and its engine are playable. Conclusion grading checks case-defined keywords, so it has limited ability to judge the meaning of a written answer. The [Llama build agent](agent/build_agent.py) is a development tool. The team's planned FastAPI/React application, a demonstration of AI's contribution to the product, and three additional cases are open work. The Part 3 submission also calls for the seven-section PowerPoint, a demo, and an upload from each team member.
