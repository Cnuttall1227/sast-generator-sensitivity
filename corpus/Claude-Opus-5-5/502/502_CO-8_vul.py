import os
import logging
from collections import OrderedDict

import gradio as gr
import torch

MAX_CHECKPOINT_BYTES = 500 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("checkpoint-inspector")


def human_count(n):
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            return f"{n / size:.2f}{unit}"
    return str(n)


def load_checkpoint(path):
    if path.endswith(".safetensors"):
        from safetensors.torch import load_file
        return {"state_dict": load_file(path, device="cpu"), "meta": {"format": "safetensors"}}
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError("unrecognised checkpoint layout")
    for key in ("state_dict", "model_state_dict", "model"):
        if key in checkpoint and isinstance(checkpoint[key], dict):
            meta = {k: v for k, v in checkpoint.items() if k != key and isinstance(v, (int, float, str))}
            return {"state_dict": checkpoint[key], "meta": meta}
    if all(isinstance(v, torch.Tensor) for v in checkpoint.values()):
        return {"state_dict": checkpoint, "meta": {}}
    raise ValueError("couldn't find a state dict in the checkpoint")


def summarize_state_dict(state_dict):
    layers = OrderedDict()
    total = 0
    dtypes = {}
    for name, tensor in state_dict.items():
        if not isinstance(tensor, torch.Tensor):
            continue
        count = tensor.numel()
        total += count
        dtypes[str(tensor.dtype)] = dtypes.get(str(tensor.dtype), 0) + count
        prefix = name.split(".")[0]
        layers[prefix] = layers.get(prefix, 0) + count
    rows = [[name, human_count(count), f"{100 * count / total:.1f}%"] for name, count in layers.items()] if total else []
    return total, dtypes, rows


def tensor_table(state_dict, limit=200):
    rows = []
    for name, tensor in list(state_dict.items())[:limit]:
        if isinstance(tensor, torch.Tensor):
            stats = tensor.float()
            rows.append([name, list(tensor.shape), str(tensor.dtype),
                         f"{stats.mean().item():.4g}" if tensor.numel() else "—",
                         f"{stats.std().item():.4g}" if tensor.numel() > 1 else "—"])
    return rows


def inspect(file_obj):
    if file_obj is None:
        return "Upload a checkpoint to inspect it.", [], []
    path = file_obj if isinstance(file_obj, str) else file_obj.name
    if os.path.getsize(path) > MAX_CHECKPOINT_BYTES:
        return "That checkpoint is larger than 500 MB.", [], []
    try:
        loaded = load_checkpoint(path)
    except Exception as exc:
        log.warning("Failed to load %s: %s", os.path.basename(path), exc)
        return f"Could not read the checkpoint: {type(exc).__name__}", [], []
    total, dtypes, layer_rows = summarize_state_dict(loaded["state_dict"])
    dtype_text = ", ".join(f"{k}: {human_count(v)}" for k, v in sorted(dtypes.items()))
    meta_text = "\n".join(f"- **{k}**: {v}" for k, v in loaded["meta"].items()) or "- (none)"
    summary = (
        f"### {human_count(total)} parameters\n"
        f"**Tensors:** {len(loaded['state_dict'])}  \n**Dtypes:** {dtype_text}\n\n**Metadata**\n{meta_text}"
    )
    log.info("Inspected checkpoint with %d tensors", len(loaded["state_dict"]))
    return summary, layer_rows, tensor_table(loaded["state_dict"])


with gr.Blocks(title="Checkpoint inspector") as demo:
    gr.Markdown("# PyTorch checkpoint inspector\nSee parameter counts, layer sizes and tensor statistics.")
    upload = gr.File(label="Checkpoint (.pt / .pth / .ckpt)", file_types=[".pt", ".pth", ".ckpt"])
    summary = gr.Markdown()
    layers = gr.Dataframe(headers=["Top-level module", "Parameters", "Share"], label="By module")
    tensors = gr.Dataframe(headers=["Tensor", "Shape", "Dtype", "Mean", "Std"], label="Tensors (first 200)")
    upload.change(inspect, inputs=upload, outputs=[summary, layers, tensors])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7861)