# xiaomi-bootloader-unlocker

simple script to send timed unlock apply requests around beijing midnight reset.

## credit

some request/session handling ideas were inspired by community tooling:

- [offici5l/MiUnlockTool](https://github.com/offici5l/MiUnlockTool/tree/main/MiUnlockTool/src/miunlock)


## install

to get token after running script, install cookie editor and copy "new_bbs_serviceToken"
and paste into your terminal (while the script is running)

```bash
pip install -r requirements.txt
```

## run

interactive token:

```bash
python hyperosunlocker.py
```

non-interactive token:

```bash
python hyperosunlocker.py --token "your_new_bbs_serviceToken_here"
```

## useful flags

- `--phase-ms 200` -> start 200 ms before 00:00:00 bj
- `--burst-count 30`
- `--burst-gap-ms 30`
- `--normal-gap-ms 100`
- `--status-url ...`
- `--apply-url ...`
- `--version-code ...`
- `--version-name ...`

## env vars

- `HYPEROS_TOKEN`
- `HYPEROS_PHASE_MS`
- `HYPEROS_BURST_COUNT`
- `HYPEROS_BURST_GAP_MS`
- `HYPEROS_NORMAL_GAP_MS`
- `HYPEROS_STATUS_URL`
- `HYPEROS_APPLY_URL`
- `HYPEROS_USER_AGENT`
- `HYPEROS_VERSION_CODE`
- `HYPEROS_VERSION_NAME`
- `HYPEROS_NTP_SERVERS` (comma-separated)
