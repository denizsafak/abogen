log_callback = None
show_warning_signal_emitter = None  # Renamed for clarity


def set_log_callback(cb):
    global log_callback
    log_callback = cb


def set_show_warning_signal_emitter(emitter):  # Renamed for clarity
    global show_warning_signal_emitter
    show_warning_signal_emitter = emitter


from huggingface_hub import hf_hub_download


def tracked_hf_hub_download(*args, **kwargs):
    try:
        local_kwargs = dict(kwargs)
        local_kwargs["local_files_only"] = True
        hf_hub_download(*args, **local_kwargs)
    except Exception:
        repo_id = kwargs.get("repo_id", "<unknown repo>")
        filename = kwargs.get("filename", "<unknown file>")
        if filename.endswith(".pth"):
            msg = f"\nDownloading model '{filename}' from Hugging Face ({repo_id}). This may take a while. Please wait..."
            if show_warning_signal_emitter:  # Check if the emitter is set
                show_warning_signal_emitter.emit(
                    "Downloading Model",
                    f"Downloading model '{filename}' from Hugging Face repository '{repo_id}'. This may take a while, please wait.",
                )
        else:
            msg = f"\nDownloading '{filename}' from Hugging Face ({repo_id}). Please wait..."
        if log_callback:
            print(msg, flush=True)
            log_callback(msg)
        else:
            print(msg, flush=True)
    return hf_hub_download(*args, **kwargs)


import huggingface_hub

huggingface_hub.hf_hub_download = tracked_hf_hub_download
