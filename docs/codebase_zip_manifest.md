# Codebase Zipping Manifest for Remote Analysis

This document outlines the manifest of necessary codebase files and folders required for remote analysis of `notion2api`. It lists what should be included, what must be excluded (to prevent leaking API keys, credentials, and uploading large dependencies), and provides copy-paste commands to perform the zipping.

---

## 1. Directory Exclusion & Inclusion Rules

When zipping the project for remote analysis, you must omit local dependencies, caches, git history, and local user data (such as active accounts and log folders).

### Exclude List
*   **Caches:** `__pycache__/`, `.pytest_cache/`
*   **Dependencies:** `.venv/`, `node_modules/`, `frontend/node_modules/`
*   **Data & Logs:** `data/`, `logs/`
*   **Version Control:** `.git/`

---

## 2. Codebase Manifest

### Required Files & Directories
*   `app/` — Core Python app modules.
*   `frontend/` — Next.js/Vite frontend (components, config).
*   `prompts/` & `scripts/` & `tests/` — Prompts, helper utilities, and test suites.
*   **Root Configs:** `main.py`, `login.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `README.md`, `accounts.README.md`

---

## 3. Zipping Commands

Run these commands from the root of `notion2api` directory:

### Option A: PowerShell (Windows)
```powershell
Get-ChildItem -Path . -Recurse | 
  Where-Object { 
    $_.FullName -notmatch 'node_modules|venv|__pycache__|data|\.git|\.pytest_cache|logs' 
  } | 
  Compress-Archive -DestinationPath notion2api_clean.zip -Force
```

### Option B: Bash (macOS/Linux)
```bash
zip -r notion2api_clean.zip . -x "node_modules/*" "frontend/node_modules/*" ".venv/*" "data/*" ".git/*" "*/__pycache__/*" ".pytest_cache/*" "logs/*"
```
