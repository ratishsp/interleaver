#!/bin/bash
#SBATCH --account=YOUR_ACCOUNT
#SBATCH --partition=defq
#SBATCH --gres=gpu:1
#SBATCH --time=00:40:00
#SBATCH --job-name=maya_sa
#SBATCH --output=/path/to/your/project/logs/maya_sa_%j.out
# Synthesize a week's Sanskrit lines (per-line wavs) with indic-parler-tts.
# Usage: sbatch synth_week_sa.sbatch <weekdir> <out_dir>
set -euo pipefail
module load CUDA/12.8.0
export HF_HOME=/path/to/your/project/hf
export HF_HUB_OFFLINE=1                     # model is already cached; don't hit the network
REPO=/path/to/your/project/sanskrit-tts/tandem
VENV=/path/to/your/project/venvs/parler-tts-venv/bin/python
cd "$REPO"
"$VENV" gefion/synth_week_sa.py "${1:-year1/week01}" "${2:-/path/to/your/project/maya_sa_wk1}"
