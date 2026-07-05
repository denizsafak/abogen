def load_numpy_kpipeline():
    import numpy as np
    from kokoro import KPipeline  # type: ignore[import-not-found]

    return np, KPipeline
