# Setup on Windows

Run these commands in PowerShell from the project folder. You need Python 3.11,
Node LTS, and an NVIDIA GPU with a current driver. No ffmpeg installation is needed.

1. Create the main environment and install the project requirements:

   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\python -m pip uninstall -y onnxruntime
   .venv\Scripts\python -m pip install --force-reinstall --no-deps 'onnxruntime-gpu[cuda,cudnn]>=1.32'
   ```

2. Install the official Plaud CLI and sign in yourself:

   ```powershell
   npm install -g @plaud-ai/cli
   plaud login
   ```

3. Accept the terms for [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1),
   then create its separate environment and sign in to Hugging Face:

   ```powershell
   py -3.11 -m venv .venv-pyannote
   .venv-pyannote\Scripts\python -m pip install pyannote.audio
   .venv-pyannote\Scripts\python -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cu126 --force-reinstall --no-deps
   .venv\Scripts\hf auth login
   ```

4. Print the model download commands, then run them:

   ```powershell
   .venv\Scripts\python -m app.doctor --fetch-models
   ```

   These use `onnx-asr` for Parakeet and the official sherpa model releases
   ([segmentation](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/speaker-diarization/models.rst),
   [speaker embeddings](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)).
   The printed paths match the defaults in `app/config.py`; use your configured paths if you changed them.
   Whisper and pyannote download their models on first use.

5. Install and sign in to the provider CLIs you use: `claude`, `codex`, or `agy`.
   The default is `claude`; doctor reports installed names without making AI calls.

6. Create `config.json` in the project folder, pointing to your Obsidian vault:

   ```json
   {"vault": "C:/Users/YourName/Documents/Obsidian Vault"}
   ```

   On an 8 GiB graphics card shared with the desktop, you can also set
   `"whisper_compute_type": "int8_float16"` in this file. This is the setting used
   for the ticket 11 import. The default is `float16`. Restart the server after changing it.

7. Start `.venv\Scripts\python -m app.server` and open <http://127.0.0.1:8377>.
   To start at Windows sign-in, run this yourself:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1
   ```

   It registers **Plaud dashboard** for the current user, without administrator rights,
   and restarts failures up to three times at one-minute intervals. Add `-Check` to
   inspect registration and its last result without changing anything. Sign out/in to check startup.

8. Finish with the read-only setup check:

   ```powershell
   .venv\Scripts\python -m app.doctor
   ```

Every check should say `ok` (ffmpeg says `not needed`). Fix anything else using the
message shown. For the sandbox, add `--config data/sandbox/config.json`.

The dashboard refreshes setup status every ten minutes. Jobs and retries live in
`<data_dir>/jobs.db`, logs in `<data_dir>/server.log` (5 MB with three backups).
An interrupted import resumes after its last saved stage. Most errors get three
automatic retries, after 5 minutes, 30 minutes, then 2 hours. A provider usage limit
waits 2 hours for each retry. For an expired provider login, sign in again and use
the dashboard's **AI** check to resume its paused notes. CUDA out-of-memory errors
require **Retry**. Expired Plaud sign-in pauses downloads without consuming attempts.
Run `plaud login` yourself and the next successful account check resumes them.
