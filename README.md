# Powston simulator — starter

A minimal repo that lets you tune your Powston inverter rule against your own
historical meter data, in a GitHub Codespace, without installing anything
locally.

## What you need

1. A Powston account with at least one inverter on it.
2. A `POWSTON_API_KEY` (ask your Powston contact if you don't have one).
3. A GitHub account.

## Run a tune

1. **Fork this repo** into your own GitHub account.
2. **Add your API key as a Codespaces secret.** In your fork, go to
   *Settings → Secrets and variables → Codespaces → New repository secret*.
   Name it `POWSTON_API_KEY` and paste your key.
3. **Open a Codespace.** Click the green *Code* button → *Codespaces* →
   *Create codespace on main*. The first start takes a couple of minutes
   while it downloads the compiled wheel and installs dependencies.
   
   ```bash
   export POWSTON_API_KEY=your_api_key_here
   curl --fail --location     -H "Authorization: Bearer $POWSTON_API_KEY"     -o /tmp/powston-wheels/powston_simulator.whl     "/api/v1/wheels/latest?platform=linux_x86_64&py=cp312"
   pip install /tmp/powston-wheels/powston_simulator.whl
   ```
4. **Run the tuner.** In the Codespace terminal:

   ```
   python run-site-sim.py --inverter_id <YOUR_INVERTER_ID> --days 7
   ```

5. The script logs every evaluation to `tune_logs/<inverter_id>_<timestamp>.jsonl`
   and prints the variable values that produced the lowest simulated bill.
   Copy those values back into your Powston rule by hand.

## Common flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--inverter_id` | `2051` | Inverter ID on Powston (required for your data) |
| `--days` | `7` | How many days of meter history to tune over |
| `--days_ago` | `7` | Where to start the window (days back from today) |
| `--battery_loss` | `40` | Round-trip battery efficiency loss in percent |
| `--fast` | `7` | If `3`, only tune `BATTERY_SOC_NEEDED`, `GOOD_SUN_DAY`, `ALWAYS_IMPORT_SOC` |

## Updating to a new release

Re-create the Codespace, or run the post-create script again:

```
bash .devcontainer/post-create.sh
```

This always pulls the latest wheel for your platform from the Powston API.

## Troubleshooting

- **`POWSTON_API_KEY is not set`.** Either the Codespaces secret wasn't
  added, or the Codespace was started before you added it. Stop and recreate
  the Codespace after saving the secret.
- **`curl ... 401`.** Your API key is invalid or has been revoked. Check it
  in your Powston account dashboard.
- **`curl ... 404`.** No wheel is available for this Python version yet.
  The default targets cp312 on Linux x86_64 (Codespaces). If you've started
  the Codespace with a different Python, override `PYTHON_TAG` in
  `.devcontainer/devcontainer.json`.
- **`No data available for inverter ...`.** The Powston account associated
  with your API key doesn't have meter data for that inverter ID, or the
  date range is outside what's recorded.
