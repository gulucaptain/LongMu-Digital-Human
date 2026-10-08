#!/usr/bin/env bash
set -euo pipefail
# 从云服务器 LongMu 仓库根目录运行：bash /项目目录/run_pipeline.sh /实际部署/runtime.toml
runtime_config="${1:?请传入服务器已有的 runtime.toml 路径}"
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_file="$project_dir/project.json"
run_output="$project_dir/runs/default"
python -m longmu doctor --project "$project_file" --config "$runtime_config" --output "$run_output"
python -m longmu run --project "$project_file" --config "$runtime_config" --output "$run_output" --stage tts
python longmu-script-planner/scripts/prepare_project.py --repo . --project "$project_file" --config "$runtime_config" --output "$run_output" --use-audio --preview-dir "$project_dir/review_measured"
gpu_args=()
if [[ -n "${2:-}" ]]; then gpu_args=(--gpus "$2"); fi
python -m longmu run --project "$project_file" --config "$runtime_config" --output "$run_output" --stage video "${gpu_args[@]}"
