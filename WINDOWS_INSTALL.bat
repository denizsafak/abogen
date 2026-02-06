@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: Set misaki language
:: English: "en"
:: Chinese: "zh"
:: Japanese: "ja"
set MISAKI_LANG=en

:::
:::      _    ____   ___   ____  _____ _   _ 
:::     / \  | __ ) / _ \ / ___|| ____| \ | |
:::    / _ \ |  _ \| | | | |  _ |  _| |  \| |
:::   / ___ \| |_) | |_| | |_| || |___| |\  |
:::  /_/   \_\____/ \___/ \____||_____|_| \_|
:::                                           
:::

for /f "delims=: tokens=*" %%A in ('findstr /b ::: "%~f0"') do @echo(%%A

set CURRENT_DIR="%CD%"
set "UV_CACHE_DIR=%~dp0.uv_cache"
set NAME=abogen
set PROJECTFOLDER=abogen
set RUN=python_embedded\Scripts\abogen.exe
set PYPROJECT_FILE=pyproject.toml
set LAST_DIR_FILE=%PROJECTFOLDER%\last_known_directory.txt
set refrenv=%PROJECTFOLDER%\refrenv.bat
set PYTHON_PATH=python_embedded\pythonw.exe
set PYTHON_CONSOLE_PATH=python_embedded\python.exe

:: ---------------------------------------------------------
:: Version Selection
:: ---------------------------------------------------------
echo.
echo Select installation version:
echo [1] Stable (PyPI)  - Safer, recommended for most users.
echo [2] Dev (Local)    - Install from current folder (may include commits after the latest release).
echo.
choice /C 12 /M "Your choice"

if errorlevel 2 (
    set INSTALL_SOURCE=dev
    echo.
    echo Selected: Dev - Local Editable
) else (
    set INSTALL_SOURCE=pypi
    echo.
    echo Selected: Stable - PyPI
)
echo.
:: ---------------------------------------------------------

:: Check for updates
echo Checking for updates...
set VERSION_FILE=%PROJECTFOLDER%\VERSION
set VERSION_URL=https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/abogen/VERSION
set UPDATE_ZIP_URL=https://github.com/denizsafak/abogen/archive/refs/heads/main.zip
set UPDATE_ZIP=%PROJECTFOLDER%\update.zip

if exist "%VERSION_FILE%" (
    set /p LOCAL_VERSION=<"%VERSION_FILE%"
    :: Remove any dots from the version string
    set "LOCAL_VERSION_CLEAN=!LOCAL_VERSION:.=!"

    :: First verify GitHub is accessible by checking HTTP status code
    for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%VERSION_URL%"') do set abogen_http_status=%%i
    
    if not "!abogen_http_status!"=="200" (
        echo Failed to access GitHub repository ^(HTTP status: !abogen_http_status!^). Continuing with current version.
        goto continue_with_current_version
    )
    
    :: Get the remote version (only if GitHub is accessible)
    for /f "delims=" %%i in ('curl -s "%VERSION_URL%"') do set abogen_remote_version=%%i
    
    if "!abogen_remote_version!"=="" (
        echo Empty version information received. Continuing with current version.
        goto continue_with_current_version
    )
    
    :: Remove any dots from the remote version string
    set "abogen_remote_version_CLEAN=!abogen_remote_version:.=!"
    
    :: Double-verify that both version values are numeric
    echo !LOCAL_VERSION_CLEAN!| findstr /r "^[0-9]*$" >nul
    if errorlevel 1 (
        echo Invalid local version format. Continuing with current version.
        goto continue_with_current_version
    )
    
    echo !abogen_remote_version_CLEAN!| findstr /r "^[0-9]*$" >nul
    if errorlevel 1 (
        echo Invalid remote version format. Continuing with current version.
        goto continue_with_current_version
    )
    
    if !abogen_remote_version_CLEAN! GTR !LOCAL_VERSION_CLEAN! (
        echo Update available ^(!LOCAL_VERSION! -^> !abogen_remote_version!^).
        
        echo Do you want to download the latest update?
        choice /C YN /M "Y=Yes, N=No"
        if errorlevel 2 (
            echo Update skipped. Continuing with current version.
            goto continue_with_current_version
        )
        
        echo Downloading the latest update...
        
        :: Test the zip URL before downloading
        for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%UPDATE_ZIP_URL%"') do set abogen_zip_status=%%i
        
        if not "!abogen_zip_status!"=="302" (
            echo Failed to access update zip file ^(HTTP status: !abogen_zip_status!^). Continuing with current version.
            goto continue_with_current_version
        )
        
        curl -L -o "%UPDATE_ZIP%" "%UPDATE_ZIP_URL%"
        if not exist "%UPDATE_ZIP%" (
            echo Failed to download update with curl. Trying with PowerShell method...
            powershell -Command "Invoke-WebRequest -Uri '%UPDATE_ZIP_URL%' -OutFile '%UPDATE_ZIP%'"
        )
        
        if exist "%UPDATE_ZIP%" (
            echo Extracting update...
            :: Create a temp directory for extraction
            if not exist "%TEMP%\abogen_update" mkdir "%TEMP%\abogen_update"
            powershell -Command "Expand-Archive -Path '%UPDATE_ZIP%' -DestinationPath '%TEMP%\abogen_update' -Force"
            
            if exist "%TEMP%\abogen_update\abogen-main" (
                :: Copy files from the extracted directory to the current directory
                echo Installing update...
                xcopy /E /Y /I "%TEMP%\abogen_update\abogen-main\*" "."
                
                :: Clean up
                rmdir /S /Q "%TEMP%\abogen_update"
                del "%UPDATE_ZIP%"
                echo Update completed successfully!
                echo Restarting...
                start "" "%~f0" %*
                exit
            ) else (
                echo Failed to extract update. Continuing with current version.
            )
        ) else (
            echo Failed to download update. Continuing with current version.
        )
    ) else (
        echo Current version: !LOCAL_VERSION!, Remote version: !abogen_remote_version!
        echo You are using the latest version.
    )
) else (
    echo VERSION file not found. Cannot check for updates.
)

:continue_with_current_version

REM Python embedded download configuration for different architectures
if "%PROCESSOR_ARCHITECTURE%"=="x86" (
    set PYTHON_EMBEDDED_FILE=%PROJECTFOLDER%\python_embedded_win32.zip
    set PYTHON_EMBEDDED_URL=https://github.com/wojiushixiaobai/Python-Embed-Win64/releases/download/3.12.12/python-3.12.12-embed-win32.zip
) else (
    set PYTHON_EMBEDDED_FILE=%PROJECTFOLDER%\python_embedded_amd64.zip
    set PYTHON_EMBEDDED_URL=https://github.com/wojiushixiaobai/Python-Embed-Win64/releases/download/3.12.12/python-3.12.12-embed-amd64.zip
)

:: Check if Python exists
%PYTHON_CONSOLE_PATH% -m pip --version >nul 2>&1 && (set python_installed=true) || (set python_installed=false)
if "%python_installed%"=="false" (
    if not exist %PYTHON_EMBEDDED_FILE% (
        echo Downloading embedded Python...
        curl -L -o %PYTHON_EMBEDDED_FILE% %PYTHON_EMBEDDED_URL%
        if errorlevel 1 (
            echo Failed to download embedded Python with curl. Trying with PowerShell method...
            powershell -Command "Invoke-WebRequest -Uri %PYTHON_EMBEDDED_URL% -OutFile %PYTHON_EMBEDDED_FILE%"
            if errorlevel 1 (
                echo Failed to download embedded Python.
                pause
                exit /b
            )
        )
    )

    if not exist "python_embedded" (
        echo Creating python_embedded directory...
        mkdir python_embedded
        if errorlevel 1 (
            echo Failed to create python_embedded directory.
            pause
            exit /b
        )
    )
    
    echo Unzipping embedded Python...
    tar -xf %PYTHON_EMBEDDED_FILE% -C python_embedded
    if errorlevel 1 (
        echo Failed to unzip embedded Python with tar. Trying with PowerShell method...
        powershell -Command "Expand-Archive -Path %PYTHON_EMBEDDED_FILE% -DestinationPath python_embedded"
        if errorlevel 1 (
            echo Failed to unzip embedded Python.
            pause
            exit /b
        )
    )

    ::del %PYTHON_EMBEDDED_FILE%
    echo Editing python312._pth file...
    echo import site >> python_embedded\python312._pth
    echo .  >> python_embedded\python312._pth
        if errorlevel 1 (
            echo Failed to add import site and . to python312._pth file. Please edit the file manually and try again. You need to add 'import site' and '.' to the file. You can find the file in python_embedded directory. After editing, please run this script again.
            pause
            exit /b
        )
    )

:: Display provided argument if any
if not "%~1"=="" (
    echo Open with: "%~1"
)

:: Update pip and install uv
echo Updating pip and installing uv...
%PYTHON_CONSOLE_PATH% -m pip install --upgrade pip --no-warn-script-location
%PYTHON_CONSOLE_PATH% -m pip install uv --no-warn-script-location
if errorlevel 1 (
    echo Failed to install uv.
    pause
    exit /b
)

:: Install docopt's fixed version
echo Installing fixed version of docopt...
%PYTHON_CONSOLE_PATH% -m uv pip install --system --force-reinstall https://github.com/denizsafak/abogen/raw/refs/heads/main/abogen/resources/docopt-0.6.2-py2.py3-none-any.whl
if errorlevel 1 (
    echo Failed to install fixed version of docopt.
    pause
    exit /b
)

:: Install progress's fixed version
echo Installing fixed version of progress...
%PYTHON_CONSOLE_PATH% -m uv pip install --system --force-reinstall https://github.com/denizsafak/abogen/raw/refs/heads/main/abogen/resources/progress-1.6-py3-none-any.whl
if errorlevel 1 (
    echo Failed to install fixed version of progress.
    pause
    exit /b
)

:: Install setup requirements
echo Installing setup requirements...
%PYTHON_CONSOLE_PATH% -m uv pip install --system --upgrade setuptools setuptools-scm wheel sphinx hatchling editables
if errorlevel 1 (
    echo Failed to install setup requirements.
    pause
    exit /b
)

:: Install gpustat
echo Installing gpustat...
%PYTHON_CONSOLE_PATH% -m uv pip install --system gpustat
if errorlevel 1 (
    echo Failed to install gpustat.
    pause
    exit /b
)

:: Install project based on user selection
if "%INSTALL_SOURCE%"=="pypi" (
    echo Installing stable version from PyPI...
    %PYTHON_CONSOLE_PATH% -m uv pip install --system abogen
    if errorlevel 1 (
        echo Failed to install abogen from PyPI.
        pause
        exit /b
    )
) else (
    echo Checking and installing project dependencies...
    if exist %PYPROJECT_FILE% (
        echo Installing project from pyproject.toml using uv...
        :: Using uv pip install --system --editable
        %PYTHON_CONSOLE_PATH% -m uv pip install --system --editable .
        if errorlevel 1 (
            echo Failed to install from pyproject.toml.
            pause
            exit /b
        )
    ) else (
        echo Warning: pyproject.toml not found in current directory.
        pause
    )
)

:: Install misaki again if MISAKI_LANG is not set to "en" via uv
if "%MISAKI_LANG%" NEQ "en" (
    echo Configuring language pack: %MISAKI_LANG%
    %PYTHON_CONSOLE_PATH% -m uv pip install --system misaki[%MISAKI_LANG%] --upgrade
    if errorlevel 1 (
        echo Failed to install misaki language pack.
        pause
        exit /b
    )
)

:: Check for NVIDIA GPU via is_nvidia()
for /f %%i in ('%PYTHON_CONSOLE_PATH% -c "from abogen.is_nvidia import check; print(check())"') do set IS_NVIDIA=%%i

:: Check if torch is installed with CUDA support
echo.
echo Checking CUDA availability...
if /I "%IS_NVIDIA%"=="true" (
    for /f %%i in ('%PYTHON_CONSOLE_PATH% %PROJECTFOLDER%\check_cuda.py') do set cuda_available=%%i

    if "%cuda_available%"=="False" (
        echo "Installing PyTorch with CUDA (12.8) support..."
        :: We need to use an older version of PyTorch (2.8.0) until this issue is fixed: https://github.com/pytorch/pytorch/issues/166628
        :: Solution mentioned by @mazenemam19 in #99:
        %PYTHON_CONSOLE_PATH% -m uv pip install --system torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
        echo.
        if errorlevel 1 (
            echo Failed to install PyTorch.
            pause
            exit /b
        )
    ) else (
        echo CUDA is available on NVIDIA GPU.
    )
) else (
    echo.
    echo Unable to detect an NVIDIA GPU in your system.
    echo.
    echo Do you want to install PyTorch anyway?
    echo.
    echo If you DO have an NVIDIA GPU, please press Y.
    echo If you DO NOT have an NVIDIA GPU, please press N.
    echo.
    choice /C YN /M "Y=Yes, N=No"
    if errorlevel 2 (
        echo Skipping PyTorch installation.
    ) else (
        echo "Installing PyTorch with CUDA (12.8) support..."
        :: We need to use an older version of PyTorch (2.8.0) until this issue is fixed: https://github.com/pytorch/pytorch/issues/166628
        :: Solution mentioned by @mazenemam19 in #99:
        %PYTHON_CONSOLE_PATH% -m uv pip install --system torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
        if errorlevel 1 (
            echo Failed to install PyTorch.
            pause
            exit /b
        )
    )
)

:: Ask user if they want to create a desktop shortcut
echo.
echo Do you want to create a desktop shortcut for %NAME%?                                       
choice /C YN /M "Y=Yes, N=No"
if errorlevel 2 goto :skip_shortcut
if errorlevel 1 (
    if exist "%PROJECTFOLDER%\assets\create_shortcuts.bat" (
        call "%PROJECTFOLDER%\assets\create_shortcuts.bat"
    ) else (
        echo Shortcut creation script not found: %PROJECTFOLDER%\assets\create_shortcuts.bat
    )
    goto :continue
)

:skip_shortcut
call "%PROJECTFOLDER%\assets\create_shortcuts.bat" --no-create-desktop-shortcut
echo Skipping desktop shortcut creation.

:continue

:: Run the program
echo Starting %NAME%...
start "" %RUN% %*

exit /b
