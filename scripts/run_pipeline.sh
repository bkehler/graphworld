cd ..
module load singularity
mkdir -p out
singularity exec -B ${PWD}/src:/app,${PWD}/out:/app/out graphworld.sif python3 /app/beam_benchmark_main.py \
    --gin_files /app/configs/nodeclassification_mwe.gin \
    --runner DirectRunner \
    --output /app/out