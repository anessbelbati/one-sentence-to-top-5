#!/bin/bash
# One rented GPU pod of the "one sentence to #1" pilot. /workspace/inj_bundle.tgz holds this repo's code and the pilot's
# candidate files (a tar of the repo, uploaded). Everything lands in /workspace/bench/cache.
#
# MODE=oj   SIZE=2B|9B NSERV=<server copies> SHARDS="<k ...>" NSHARDS=<n> RATE=<USD/h>
#           Open-Jev servers on the card and run.py's jev-noul-pair through them, on inj-pair (the edited page alone).
# MODE=hf   RATE GPU: inject/hf_runner.py, plain Qwen3.5-4B and Together's tev1-4B, on inj-pair.
# MODE=laya RATE GPU: small_models_runner.py laya-score-pair on inj-pair.
# MODE=bm25 inject/bm25_edit.py (CPU; downloads the eight corpora).
# V / RUNV: the kinds to run (default: the pilot's six / run.py --variant inject). The follow-up passes
#           V="para related offtopic offecho offpara offstuff" RUNV=followup.
set -x
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_BREAK_SYSTEM_PACKAGES=1 TOKENIZERS_PARALLELISM=false
cd /workspace
mkdir -p bench && tar --no-same-owner -xzf inj_bundle.tgz -C bench && mkdir -p bench/cache bench/results
for f in bench/candidates/*.docs.jsonl.gz; do [ -e "$f" ] && [ ! -e "${f%.gz}" ] && gunzip -k "$f"; done   # the runners read plain files
V=${V:-"clean echo claim order stuff hidden"}; RUNV=${RUNV:-inject}
case "$MODE" in
oj)
  [ -d Open-Jev ] || git clone --depth 1 https://github.com/Zefan-Cai/Open-Jev.git
  cd Open-Jev
  python -c "import transformers, peft" 2>/dev/null || pip install -q -e '.[train]' requests python-dotenv tqdm 2>&1 | tail -3
  if [ "$SIZE" = "9B" ]; then REV=47e966881e489511c0c7f5633a9e1960a676a551; else REV=0c7aa498b1627be8da4acf34c863ff0ee0a92785; fi
  [ -d models/Open-Jev-$SIZE/package ] || python -c "from huggingface_hub import snapshot_download; print(snapshot_download('ZefanCai/Open-Jev-$SIZE', revision='$REV', local_dir='models/Open-Jev-$SIZE'))"
  CKPT=models/Open-Jev-$SIZE/package/checkpoint
  for j in $(seq 0 $((NSERV-1))); do
    PORT=$((8791+j))
    nohup python -m jev.server --checkpoint $CKPT --device cuda:0 --max-length 4096 --batch-size 32 --port $PORT > /workspace/server_$j.log 2>&1 &
    until curl -sf http://127.0.0.1:$PORT/health; do sleep 5; done; echo " server $j ready"
  done
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
  size=$(echo $SIZE | tr A-Z a-z); cd /workspace/bench
  PER=$(python -c "print($RATE/$NSERV)"); j=-1
  for K in $SHARDS; do
    j=$((j+1))
    JEV_URL=http://127.0.0.1:$((8791+j))/v1/systemone JEV_MODEL=open-jev JEV_GPU_RATE=$PER nohup python run.py --model jev-noul-pair --cache-as open-jev-$size-noul-pair --dataset inj-pair --variant $RUNV --workers 2 --shard $K/$NSHARDS > /workspace/run_$j.log 2>&1 &
  done
  wait; echo OJ_DONE ;;
hf)
  pip install -q -U "transformers>=5" accelerate 2>&1 | tail -2
  pip install -q flash-linear-attention 2>&1 | tail -1
  cd /workspace/bench && python inject/hf_runner.py --root /workspace/bench --rate $RATE --gpu "$GPU" --models qwen35-4b-yesno-pair tev1-4b-pair --variants $V ;;
laya)
  pip install -q laya==0.3.3 2>&1 | tail -2
  cd /workspace/bench && python small_models_runner.py --root /workspace/bench --rate $RATE --gpu "$GPU" --models laya-score-pair --datasets inj-pair --variants $V ;;
bm25)
  pip install -q bm25s==0.3.11 PyStemmer pyarrow python-dotenv requests huggingface_hub 2>&1 | tail -2
  cd /workspace/bench && python inject/bm25_edit.py --root /workspace/bench --variants $V ;;
esac
