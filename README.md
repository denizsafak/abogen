# abogen <img width="40px" title="abogen icon" src="https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/abogen/assets/icon.ico" align="right" style="padding-left: 10px; padding-top:5px;">

[![Build Status](https://github.com/denizsafak/abogen/actions/workflows/test_pip.yml/badge.svg)](https://github.com/denizsafak/abogen/actions)
[![GitHub Release](https://img.shields.io/github/v/release/denizsafak/abogen)](https://github.com/denizsafak/abogen/releases/latest)
![abogen PyPi Python Versions](https://img.shields.io/pypi/pyversions/abogen)
[![Operating Systems](https://img.shields.io/badge/os-windows%20%7C%20linux%20%7C%20macos%20-blue)](https://github.com/denizsafak/abogen/releases/latest)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-maroon.svg)](https://opensource.org/licenses/MIT)

Abogen is a powerful text-to-speech conversion tool that makes it easy to turn ePub, PDF, or text files into high-quality audio with matching subtitles in seconds. Use it for audiobooks, voiceovers for Instagram, YouTube, TikTok, or any project that needs natural-sounding text-to-speech, using [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M).

<img title="Abogen Main" src='https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/demo/abogen.png' width="380"> <img title="Abogen Processing" src='https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/demo/abogen2.png' width="380">

## Demo
https://github.com/user-attachments/assets/cb66512d-0a52-48c3-bda4-f1e6a03fb8d6


> This demo was generated in just 5 seconds, producing ∼1 minute of audio with perfectly synced subtitles. To create a similar video, see [the demo guide](https://github.com/denizsafak/abogen/tree/main/demo).

## `How to install?`
### Windows
Go to [espeak-ng latest release](https://github.com/espeak-ng/espeak-ng/releases/latest) download and run the *.msi file.
```bash
# For NVIDIA GPUs:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install abogen
pip install abogen
```
Alternatively, for an easier setup on Windows:
1. [Download](https://github.com/denizsafak/abogen/archive/refs/heads/main.zip) the repository
2. Extract the ZIP file
3. Run `WINDOWS_INSTALL.bat` by double-clicking it

This method handles everything automatically - installing all dependencies including CUDA in a self-contained environment without requiring a separate Python installation. (You still need to install [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases/latest).)

### Mac
```bash
# Install espeak-ng
brew install espeak-ng

# Install abogen
pip install abogen # (I have not tested it)
```
### Linux
```bash
# Install espeak-ng

# Ubuntu/Debian
sudo apt install espeak-ng
# Arch Linux
sudo pacman -S espeak-ng
# Fedora
sudo dnf install espeak-ng

# Install abogen
pip install abogen
```
> If you get "No matching distribution found" error, try installing it on supported Python (3.10 to 3.12). You can use [pyenv](https://github.com/pyenv/pyenv) to manage multiple Python versions easily in Linux. Watch this [video](https://www.youtube.com/watch?v=MVyb-nI4KyI) by NetworkChuck for a quick guide.

Then simply run by typing:

```bash
abogen
```

## `How to use?`
1) Drag and drop any ePub, PDF, or text file (or use the built-in text editor)
2) Configure the settings:
    - Set speech speed
    - Select a voice (or create a custom voice using voice mixer)
    - Select subtitle generation style (by sentence, word, etc.)
    - Select output format
    - Select where to save the output
3) Hit Start

## `In action`
<img title="Abogen in action" src='https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/demo/abogen.gif'> 

Here’s Abogen in action: in this demo, it processes ∼3,000 characters of text in just 11 seconds and turns it into 3 minutes and 28 seconds of audio, and I have a low-end **RTX 2060 Mobile laptop GPU**. Your results may vary depending on your hardware.

## `Key Features`
- **Supported formats**: `ePub`, `PDF`, or `.TXT` files (or use built-in text editor)
- **Speed**: Adjust speech rate from `0.1x` to `2.0x`
- **Voices**: First letter of the language code (e.g., `a` for American English, `b` for British English, etc.), second letter is for `m` for male and `f` for female.
- **Voice mixer**: Create custom voices by mixing different voice models with a profile system.
- **Generate subtitles**: `Disabled`, `Sentence`, `Sentence + Comma`, `1 word`, `2 words`, `3 words`, etc. (Represents the number of words in each subtitle entry)
- **Output formats**: `.WAV`, `.FLAC`, `.MP3`, and `M4B (with chapters)` (Special thanks to [@jborza](https://github.com/jborza) for chapter support in PR [#10](https://github.com/denizsafak/abogen/pull/10))
- **Save location**: `Save next to input file`, `Save to desktop`, or `Choose output folder`
- **Chapter Control**: Select specific `chapters` from ePUBs or `chapters + pages` from PDFs.
- **Options**:
    - **Replace single newlines with spaces**: Replaces single newlines with spaces in the text. This is useful for texts that have imaginary line breaks.
    - **Configure max words per subtitle**: Configures the maximum number of words per subtitle entry.
    - **Create desktop shortcut**: Creates a shortcut on your desktop for easy access.
    - **Open config.json directory**: Opens the directory where the configuration file is stored.
    - **Open temp directory**: Opens the temporary directory where converted text files are stored.
    - **Clear all temporary files**: Deletes all temporary files created during the conversion process.
    - **Check for updates at startup**: Automatically checks for updates when the program starts.
- **After conversion**: `Open file`, `Go to folder`, `New conversion`, or `Go back`.

## `Voice Mixer`
<img title="Abogen Voice Mixer" src='https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/demo/voice_mixer.png'>

With voice mixer, you can create custom voices by mixing different voice models. You can adjust the weight of each voice and save your custom voice as a profile for future use. The voice mixer allows you to create unique and personalized voices. (Huge thanks to [@jborza](https://github.com/jborza) for making this possible through his contributions in [#5](https://github.com/denizsafak/abogen/pull/5))

## `About Chapter Markers`
When you process ePUB or PDF files, abogen converts them into text files stored in your temporary directory. When you click "Edit," you're actually modifying these converted text files. In these text files, you'll notice tags that look like this:

```
<<CHAPTER_MARKER:Chapter Title>>
```
These are chapter markers. They are automatically added when you process ePUB or PDF files, based on the chapters you select. They serve an important purpose:
-  Allow you to split the text into separate audio files for each chapter
-  Save time by letting you reprocess only specific chapters if errors occur, rather than the entire file

You can manually add these markers to plain text files for the same benefits. Simply include them in your text like this:

```
<<CHAPTER_MARKER:Introduction>>
This is the beginning of my text...  

<<CHAPTER_MARKER:Main Content>> 
Here's another part...  
```
When you process the text file, abogen will detect these markers automatically and ask if you want to save each chapter separately and create a merged version.

![Abogen Chapter Marker](https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/demo/chapter_marker.png)


## `Supported Languages`
```
# 🇺🇸 'a' => American English, 🇬🇧 'b' => British English
# 🇪🇸 'e' => Spanish es
# 🇫🇷 'f' => French fr-fr
# 🇮🇳 'h' => Hindi hi
# 🇮🇹 'i' => Italian it
# 🇯🇵 'j' => Japanese: pip install misaki[ja]
# 🇧🇷 'p' => Brazilian Portuguese pt-br
# 🇨🇳 'z' => Mandarin Chinese: pip install misaki[zh]
```
For a complete list of supported languages and voices, refer to Kokoro's [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md). To listen to sample audio outputs, see [SAMPLES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/SAMPLES.md).

## `MPV Config`
I highly recommend using [MPV](https://mpv.io/installation/) to play your audio files, as it supports displaying subtitles even without a video track. Here's my `mpv.conf`:
```
save-position-on-quit
keep-open=yes
--audio-device=openal
--sub-margin-x=235
--sub-pos=60
# --- Audio Quality ---
audio-spdif=ac3,dts,eac3,truehd,dts-hd
audio-channels=auto
audio-samplerate=48000
volume-max=200
```

## `Docker Guide`
If you want to run Abogen in a Docker container:
1) [Download the repository](https://github.com/denizsafak/abogen/archive/refs/heads/main.zip) and extract, or clone it using git.
2) Go to `abogen` folder. You should see `Dockerfile` there.
3) Open your termminal in that directory and run the following commands:

```bash
# Build the Docker image:
docker build --progress plain -t abogen .

# Note that building the image may take a while.
# After building is complete, run the Docker container:

# Windows
docker run --name abogen -v %cd%:/shared -p 5800:5800 -p 5900:5900 --gpus all abogen

# Linux
docker run --name abogen -v $(pwd):/shared -p 5800:5800 -p 5900:5900 --gpus all abogen

# MacOS
docker run --name abogen -v $(pwd):/shared -p 5800:5800 -p 5900:5900 abogen

# We expose port 5800 for use by a web browser, 5900 if you want to connect with a VNC client.
```

Abogen launches automatically inside the container. 
- You can access it via a web browser at [http://localhost:5800](http://localhost:5800) or connect to it using a VNC client at `localhost:5900`.
- You can use `/shared` directory to share files between your host and the container.
- For later use, start it with `docker start abogen` and stop it with `docker stop abogen`.

Known issues:
- Audio preview is not working inside container (ALSA error).
- `Open temp directory` and `Open configuration directory` options in settings not working. (Tried pcmanfm, did not work with abogen).

(Special thanks to [@geo38](https://www.reddit.com/user/geo38/) from Reddit, who provided the Dockerfile and instructions in [this comment](https://www.reddit.com/r/selfhosted/comments/1k8x1yo/comment/mpe0bz8/).)

## `Similar Projects`
Abogen is a standalone project, but it is inspired by and shares some similarities with other projects. Here are a few:
- [audiblez](https://github.com/santinic/audiblez): Generate audiobooks from e-books. **(Has CLI and GUI support)**
- [autiobooks](https://github.com/plusuncold/autiobooks): Automatically convert epubs to audiobooks
- [pdf-narrator](https://github.com/mateogon/pdf-narrator): Convert your PDFs and EPUBs into audiobooks effortlessly.
- [epub_to_audiobook](https://github.com/p0n1/epub_to_audiobook): EPUB to audiobook converter, optimized for Audiobookshelf

## `Roadmap`
- [ ] Improve PDF support for better text extraction.
- [x] Add chapter metadata for .m4a files. (Issue [#9](https://github.com/denizsafak/abogen/issues/9), PR [#10](https://github.com/denizsafak/abogen/pull/10))
- [ ] Add support for different languages in GUI.
- [x] Add voice formula feature that enables mixing different voice models. (Issue [#1](https://github.com/denizsafak/abogen/issues/1), PR [#5](https://github.com/denizsafak/abogen/pull/5))
- [ ] Add support for kokoro-onnx.
- [ ] Add dark mode.

## `Troubleshooting`
If you encounter any issues while running Abogen, try launching it from the command line with:
```
abogen-cli
```
This will start Abogen in command-line mode and display detailed error messages. Please open a new issue on the [Issues](https://github.com/denizsafak/abogen/issues) page with the error message and a description of your problem.

## `Contributing`
I welcome contributions! If you have ideas for new features, improvements, or bug fixes, please fork the repository and submit a pull request.
### For developers and contributors
If you'd like to modify the code and contribute to development, you can [download the repository](https://github.com/denizsafak/abogen/archive/refs/heads/main.zip), extract it and run the following commands to build **or** install the package:
```bash
# Go to the directory where you extracted the repository and run:
pip install -e .      # Installs the package in editable mode
pip install build     # Install the build package
python -m build       # Builds the package in dist folder (optional)
abogen                # Opens the GUI
```
Feel free to explore the code and make any changes you like.

## `Credits`
- Abogen uses [Kokoro](https://github.com/hexgrad/kokoro) for its high-quality, natural-sounding text-to-speech synthesis. Huge thanks to the Kokoro team for making this possible.
- Thanks to [@wojiushixiaobai](https://github.com/wojiushixiaobai) for [Embedded Python](https://github.com/wojiushixiaobai/Python-Embed-Win64) packages. These modified packages include pip pre-installed, enabling Abogen to function as a standalone application without requiring users to separately install Python in Windows.
- Thanks to creators of [EbookLib](https://github.com/aerkalov/ebooklib), a Python library for reading and writing ePub files, which is used for extracting text from ePub files.
- Special thanks to the [PyQt](https://www.riverbankcomputing.com/software/pyqt/) team for providing the cross-platform GUI toolkit that powers Abogen's interface.
- Icons: [US](https://icons8.com/icon/aRiu1GGi6Aoe/usa), [Great Britain](https://icons8.com/icon/t3NE3BsOAQwq/great-britain), [Spain](https://icons8.com/icon/ly7tzANRt33n/spain), [France](https://icons8.com/icon/3muzEmi4dpD5/france), [India](https://icons8.com/icon/esGVrxg9VCJ1/india), [Italy](https://icons8.com/icon/PW8KZnP7qXzO/italy), [Japan](https://icons8.com/icon/McQbrq9qaQye/japan), [Brazil](https://icons8.com/icon/zHmH8HpOmM90/brazil), [China](https://icons8.com/icon/Ej50Oe3crXwF/china), [Female](https://icons8.com/icon/uI49hxbpxTkp/female), [Male](https://icons8.com/icon/12351/male) and [Voice Id](https://icons8.com/icon/GskSeVoroQ7u/voice-id) icons by [Icons8](https://icons8.com/).

## `License`
This project is available under the MIT License - see the [LICENSE](https://github.com/denizsafak/abogen/blob/main/LICENSE) file for details.
[Kokoro](https://github.com/hexgrad/kokoro) is licensed under [Apache-2.0](https://github.com/hexgrad/kokoro/blob/main/LICENSE) which allows commercial use, modification, distribution, and private use.

> [!IMPORTANT]
> Subtitle generation currently works only for English. This is because Kokoro provides timestamp tokens only for English text. If you want subtitles in other languages, please request this feature in the [Kokoro project](https://github.com/hexgrad/kokoro). For more technical details, see [this line](https://github.com/hexgrad/kokoro/blob/6d87f4ae7abc2d14dbc4b3ef2e5f19852e861ac2/kokoro/pipeline.py#L383) in the Kokoro's code.

> Tags: audiobook, kokoro, text-to-speech, TTS, audiobook generator, audiobooks, text to speech, audiobook maker, audiobook creator, audiobook generator, voice-synthesis, text to audio, text to audio converter, text to speech converter, text to speech generator, text to speech software, text to speech app, epub to audio, pdf to audio, content-creation, media-generation
