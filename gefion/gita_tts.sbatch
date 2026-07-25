#!/bin/bash -l
#SBATCH --job-name=gita-tts
#SBATCH --account=YOUR_ACCOUNT
#SBATCH --partition=defq
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:20:00
#SBATCH --output=/path/to/your/project/logs/gita_tts_%j.log
#SBATCH --error=/path/to/your/project/logs/gita_tts_%j.log

set -euo pipefail
module load CUDA/12.8.0

VENV=/path/to/your/project/venvs/parler-tts-venv
WORK=/path/to/your/project/sanskrit-tts/tandem/gefion
export HF_HOME=/path/to/your/project/hf
export HF_HUB_CACHE=$HF_HOME/hub
export PYTHONUNBUFFERED=1

cd "$WORK"
nvidia-smi --query-gpu=name --format=csv,noheader || true
"$VENV/bin/python" synth_gita.py gita.sa out
echo "SBATCH_DONE"
