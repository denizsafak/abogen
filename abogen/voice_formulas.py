import re
from abogen.constants import VOICES_INTERNAL


# Calls parsing and loads the voice to gpu or cpu
def get_new_voice(pipeline, formula, use_gpu):
    try:
        weighted_voice = parse_voice_formula(pipeline, formula)
        # device = "cuda" if use_gpu else "cpu"
        # Setting the device "cuda" gives "Error occurred: split_with_sizes(): argument 'split_sizes' (position 2)"
        # error when the device is gpu. So disabling this for now.
        device = "cpu"
        return weighted_voice.to(device)
    except Exception as e:
        raise ValueError(f"Failed to create voice: {str(e)}")


# Parse the formula and get the combined voice tensor
def parse_voice_formula(pipeline, formula):
    if not formula.strip():
        raise ValueError("Empty voice formula")

    # Initialize the weighted sum
    weighted_sum = None

    total_weight = calculate_sum_from_formula(formula)

    # Split the formula into terms
    voices = formula.split("+")

    for term in voices:
        # Parse each term (format: "voice_name*0.333")
        voice_name, weight = term.strip().split("*")
        weight = float(weight.strip())
        # normalize the weight
        weight /= total_weight if total_weight > 0 else 1.0
        voice_name = voice_name.strip()

        # Get the voice tensor
        if voice_name not in VOICES_INTERNAL:
            raise ValueError(f"Unknown voice: {voice_name}")

        voice_tensor = pipeline.load_single_voice(voice_name)

        # Add to weighted sum
        if weighted_sum is None:
            weighted_sum = weight * voice_tensor
        else:
            weighted_sum += weight * voice_tensor

    return weighted_sum


def calculate_sum_from_formula(formula):
    weights = re.findall(r"\* *([\d.]+)", formula)
    total_sum = sum(float(weight) for weight in weights)
    return total_sum
