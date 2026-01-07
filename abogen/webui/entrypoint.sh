#!/bin/bash
# Entrypoint script for abogen container
# Performs CUDA diagnostics and starts the web server

set -e

echo "=== Abogen Container Starting ==="

# Check CUDA availability
if command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA Driver detected:"
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi query failed)"
    
    # Check PyTorch CUDA support
    python3 -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA version (PyTorch): {torch.version.cuda}')
    print(f'GPU count: {torch.cuda.device_count()}')
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        print(f'  GPU {i}: {props.name} ({props.total_memory // 1024**2} MB)')
else:
    print('WARNING: PyTorch cannot access CUDA. Running on CPU.')
" 2>&1 || echo "PyTorch CUDA check failed"
else
    echo "No NVIDIA driver detected. Running on CPU."
fi

echo "================================="
echo ""

# Start the application
exec "$@"
