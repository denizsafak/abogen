import gpustat


def check():
    try:
        stats = gpustat.new_query()
    except Exception:
        return False

    nvidia_keywords = ["nvidia", "rtx", "gtx", "quadro", "tesla", "titan", "mx"]
    for gpu in stats.gpus:
        name = gpu.name.lower()
        if any(keyword in name for keyword in nvidia_keywords):
            return True
    return False


if __name__ == "__main__":
    stats = gpustat.new_query()
    for gpu in stats.gpus:
        print(gpu.name)
    print(check())
