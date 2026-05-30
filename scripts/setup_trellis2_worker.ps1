param(
    [string]$ProjectRoot = "",
    [switch]$DownloadModels
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$workerRoot = Join-Path $ProjectRoot "data\models\trellis2-worker"
$srcRoot = Join-Path $workerRoot "src"
$trellisSrc = Join-Path $srcRoot "ComfyUI-Trellis2"
$researchSrc = Join-Path $ProjectRoot "data\research\ComfyUI-Trellis2"
$venvDir = Join-Path $workerRoot "venv"
$python = Join-Path $venvDir "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $workerRoot, $srcRoot | Out-Null

if (-not (Test-Path (Join-Path $trellisSrc "trellis2\pipelines\trellis2_image_to_3d.py"))) {
    if (Test-Path (Join-Path $researchSrc "trellis2\pipelines\trellis2_image_to_3d.py")) {
        Write-Host "Copying ComfyUI-Trellis2 from data/research..."
        Copy-Item -LiteralPath $researchSrc -Destination $srcRoot -Recurse -Force
    } else {
        Write-Host "Cloning ComfyUI-Trellis2..."
        git clone --depth 1 https://github.com/visualbruno/ComfyUI-Trellis2.git $trellisSrc
    }
}

if (-not (Test-Path $python)) {
    Write-Host "Creating Python 3.12 venv for TRELLIS.2..."
    py -3.12 -m venv $venvDir
}

Write-Host "Upgrading pip..."
& $python -m pip install --upgrade pip wheel setuptools

Write-Host "Installing Torch 2.8.0 CUDA 12.8..."
& $python -m pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0

$wheelDir = Join-Path $trellisSrc "wheels\Windows\Torch280"
if (-not (Test-Path $wheelDir)) {
    throw "Missing TRELLIS.2 Windows Torch280 wheels at $wheelDir"
}

Write-Host "Installing TRELLIS.2 CUDA wheels..."
$wheelNames = @(
    "cumesh-1.0-cp312-cp312-win_amd64.whl",
    "custom_rasterizer-0.1-cp312-cp312-win_amd64.whl",
    "flex_gemm-0.0.1-cp312-cp312-win_amd64.whl",
    "nvdiffrast-0.4.0-cp312-cp312-win_amd64.whl",
    "nvdiffrec_render-0.0.0-cp312-cp312-win_amd64.whl",
    "o_voxel-0.0.1-cp312-cp312-win_amd64.whl"
)
foreach ($name in $wheelNames) {
    $wheel = Join-Path $wheelDir $name
    if (-not (Test-Path $wheel)) {
        throw "Missing wheel: $wheel"
    }
    & $python -m pip install --force-reinstall --no-deps $wheel
}

Write-Host "Installing TRELLIS.2 Python requirements..."
& $python -m pip install -r (Join-Path $trellisSrc "requirements.txt")
& $python -m pip install huggingface-hub safetensors "transformers>=4.56.0" accelerate einops easydict trimesh scikit-image sentencepiece plyfile zstandard triton-windows onnxruntime

if ($DownloadModels) {
    Write-Host "Downloading TRELLIS.2 FP8 model set..."
    $worker = Join-Path $ProjectRoot "jarvis\workers\trellis2_worker.py"
    $models = Join-Path $ProjectRoot "data\models\trellis2"
    & $python $worker --models-dir $models --trellis-src $trellisSrc --download-only
}

Write-Host "TRELLIS.2 worker setup complete."
