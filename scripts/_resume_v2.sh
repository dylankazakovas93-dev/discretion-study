#!/bin/bash
# Persistent, restart-safe supervisor for the v2 multi-year run.
# Lives in the repo (survives container restarts, unlike /tmp).
cd /home/user/discretion-study
L=artifacts/multiyear_validation_v2/run_logs
LEDGER=artifacts/multiyear_validation_v2/all_hypothesis_variants.csv
mkdir -p $L
# don't double-start
if pgrep -f "multiyear_validation_v2.py$" >/dev/null; then
  echo "$(date -u +%H:%M) already running" >> $L/supervisor.log; exit 0
fi
if [ -f "$LEDGER" ] && [ -f artifacts/multiyear_validation_v2/acceptance_gates.json ]; then
  echo "$(date -u +%H:%M) already complete" >> $L/supervisor.log; exit 0
fi
nohup bash -c '
cd /home/user/discretion-study
L=artifacts/multiyear_validation_v2/run_logs
LEDGER=artifacts/multiyear_validation_v2/all_hypothesis_variants.csv
for a in $(seq 1 60); do
  [ -f "$LEDGER" ] && break
  echo "$(date -u +%H:%M) launch attempt $a ckpt=$(ls artifacts/multiyear_validation_v2/checkpoints/*.pkl 2>/dev/null | wc -l)/34" >> $L/supervisor.log
  PYTHONPATH=src python3 -u scripts/multiyear_validation_v2.py >> $L/engine.log 2>&1
  echo "$(date -u +%H:%M) engine exit=$? ckpt=$(ls artifacts/multiyear_validation_v2/checkpoints/*.pkl 2>/dev/null | wc -l)/34" >> $L/supervisor.log
  [ -f "$LEDGER" ] && break
  sleep 5
done
if [ -f "$LEDGER" ]; then
  echo "$(date -u +%H:%M) engine done, running analysis" >> $L/supervisor.log
  PYTHONPATH=src python3 -u scripts/multiyear_portfolio_analysis_v2.py >> $L/analysis.log 2>&1
  echo "$(date -u +%H:%M) ANALYSIS_EXIT=$? -- ALL COMPLETE" >> $L/supervisor.log
fi
' > /dev/null 2>&1 &
echo "$(date -u +%H:%M) supervisor started" >> $L/supervisor.log
