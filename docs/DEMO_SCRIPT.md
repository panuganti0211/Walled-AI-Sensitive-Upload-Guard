# Walled AI Sensitive Upload Guard — Live Demonstration & Evaluation Script

This document provides a step-by-step walkthrough for evaluating and recording the **Walled AI Sensitive Upload Guard** desktop application.

---

## Preparation & Prerequisites

1. Open PowerShell and navigate to the project directory:
   ```powershell
   cd "D:\Walled_AI_Assignments\Walled AI Sensitive Upload Guard"
   ```
2. Verify that the Python virtual environment and all dependencies are functional:
   ```powershell
   & ".venv\Scripts\python.exe" -m pytest tests/ -q
   ```
   *(Expected output: `137 passed in ~4s`)*
3. Create sample test files for upload evaluation:
   ```powershell
   # Safe test file
   Set-Content -Path "safe_notes.txt" -Value "Meeting notes: Discussing project timelines and team allocation."

   # Sensitive test file containing the exact marker
   Set-Content -Path "confidential_notes.txt" -Value "Internal Project Specs - Highly Confidential: WALLED_SENSITIVE - Do not distribute."
   ```

---

## Step 1: Launch the Desktop Guard Application

Execute the entry point:
```powershell
& ".venv\Scripts\python.exe" run.py
```

### Visual Verification:
- The **Walled AI Sensitive Upload Guard** desktop window appears on screen.
- **Guard Status** displays `Standby (Ready)`.
- **Active Sensitive Marker** clearly displays `'WALLED_SENSITIVE'`.
- All metric cards start at `0` (Prompts Blocked, Prompts Allowed, Files Blocked, Files Allowed).
- The **DLP Audit & Security Log** table is clean and ready.

---

## Step 2: Launch the Managed Browser

1. In the desktop application, click **Launch Edge (Guarded)** (or **Launch Chrome (Guarded)**).
2. An isolated browser window launches with two tabs:
   - Tab 1: `https://chatgpt.com`
   - Tab 2: `https://www.perplexity.ai`
3. Observe the desktop dashboard status indicators update in real time:
   - **Guard Status**: Changes to `Active (Running)` with dynamic port `127.0.0.1:<port>`.
   - **CDP Indicator**: Changes to `CDP: Connected` (green badge).
   - **Interception**: Changes to `Interception: Active (CDP Fetch)` (green badge).
   - **ChatGPT Status**: Switches to `Detected` (green border).
   - **Perplexity Status**: Switches to `Detected` (green border).

---

## Step 3: Demonstrate Safe Prompt Transmission (Zero Friction)

1. Switch to the managed browser tab for **ChatGPT** (`https://chatgpt.com`).
2. Type a regular, safe prompt:
   ```text
   Explain the difference between TCP and UDP in simple terms.
   ```
3. Press **Enter** to submit.
4. **Expected Result**:
   - The prompt transmits instantly without any interruption or modal dialog.
   - ChatGPT begins generating its answer immediately.
   - On the desktop app, `Observed Prompts` increments, but no sensitive detections are triggered.

---

## Step 4: Demonstrate Sensitive Prompt Detection & Blocking (Cancel Action)

1. In the same ChatGPT tab, type a prompt containing the sensitive marker:
   ```text
   Please review this draft press release: WALLED_SENSITIVE product roadmap for 2027.
   ```
2. Click **Send** (or press Enter).
3. **Expected Result**:
   - The outgoing request is immediately **paused in-flight** by Chromium.
   - The **native desktop approval dialog** appears on top of all windows with a red alert banner:
     - **Title**: `Walled AI Sensitive Upload Guard — DLP Warning`
     - **Platform**: `ChatGPT`
     - **Type**: `Prompt`
     - **Detection**: `WALLED_SENSITIVE marker detected in outgoing prompt`
     - **Snippet**: Displays the truncated context around the marker.
     - **Buttons**: `Cancel` (highlighted in red, default focus) and `Continue` (blue outline).
4. **Take the Safe Action (Cancel)**:
   - Press **Escape** or click **Cancel**.
5. **Observed Result**:
   - The network request is terminated locally (`BlockedByClient`).
   - ChatGPT shows a local network retry indicator, and **the prompt text remains in the input box** so the user does not lose their work.
   - The desktop dashboard updates:
     - **Prompts Blocked**: Increments by `1`.
     - **Total Detections**: Increments by `1`.
     - **Audit Table**: Inserts a new row with timestamp, `ChatGPT`, `Prompt`, `Cancel (Blocked)`, `Blocked by User`.

---

## Step 5: Demonstrate Sensitive Prompt Authorization (Continue Action)

1. Switch to the managed browser tab for **Perplexity** (`https://www.perplexity.ai`).
2. Type a query containing the sensitive marker:
   ```text
   Analyze recent research on quantum encryption and WALLED_SENSITIVE benchmarks.
   ```
3. Submit the search query.
4. **Expected Result**:
   - The request is paused in-flight.
   - The native desktop confirmation dialog appears.
5. **Take the Authorize Action (Continue)**:
   - Click **Continue**.
6. **Observed Result**:
   - The original request is resumed over CDP without modification.
   - Perplexity processes the query and generates the search answer.
   - The desktop dashboard updates:
     - **Prompts Allowed**: Increments by `1`.
     - **Total Detections**: Increments by `1`.
     - **Audit Table**: Inserts a new row with `Perplexity`, `Prompt`, `Continue (Allowed)`, `Allowed by User`.

---

## Step 6: Demonstrate Sensitive File Upload Protection

1. In ChatGPT or Perplexity, click the attachment / upload button (paperclip icon).
2. First, select the safe file `safe_notes.txt`:
   - **Result**: Upload proceeds cleanly without dialog.
3. Next, select the sensitive file `confidential_notes.txt` (containing `WALLED_SENSITIVE`):
   - **Result**:
     - The multipart upload request is paused at the browser layer.
     - The native desktop approval dialog appears:
       - **Platform**: `ChatGPT` (or `Perplexity`)
       - **Content Type**: `File Upload (TXT)`
       - **File Name**: `confidential_notes.txt`
       - **Detection**: `WALLED_SENSITIVE marker detected in file content`
4. Click **Cancel**:
   - The upload transmission is aborted before leaving the workstation.
   - **Files Blocked** increments on the desktop dashboard.

---

## Step 7: Demonstrate AI Response Text Color Modification

1. Review the generated response text from ChatGPT or Perplexity from the previous steps.
2. **Observe**:
   - The assistant's text paragraphs, lists, and headers are styled in the configured DLP color (`#2563EB` — distinct blue).
   - The user's input prompt bubble, the sidebar, the navigation bar, and action buttons retain their original standard styling.
   - The color modification was injected via native CDP scripts and dynamically persists across streaming responses.

---

## Step 8: Clean Application Shutdown

1. Click **Stop Managed Browser** in the desktop application:
   - The browser process tree terminates cleanly.
   - The desktop status returns to `Standby (Ready)`.
2. Close the desktop application window:
   - Background threads, sockets, and timers are released.
