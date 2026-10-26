# Compatibility entry point: RITA Vision V2.13 uses Florence-2 instead of Ollama.
from server.vision.florence import analyze, prepare_image, run_task, MODEL_ID

MODEL = MODEL_ID
