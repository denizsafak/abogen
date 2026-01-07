# Unreleased
- Added an EPUB 3 packaging pipeline that builds media-overlay EPUBs from generated audio and chunk metadata.
- Persisted chunk timing metadata in job artifacts and exercised the exporter with automated tests.
- Added Flask-based Web UI (`abogen-web`) for Docker and headless server deployments.
- Reorganized codebase to support both PyQt6 desktop GUI and Web UI from a shared core.
- Added Supertonic TTS engine support with GPU acceleration.
- Added entity analysis and pronunciation override system for proper nouns.
- Added speaker/role assignment for multi-voice "theatrical" audiobooks.
- Added Calibre OPDS and Audiobookshelf integration.

# 1.2.5
- Added new option: `Override item settings with current selection` in the queue manager. When enabled, all items in the queue will be processed using the current global settings selected in the main GUI, overriding their individual settings. When disabled, each item will retain its own specific settings.
- Fixed `Error "Could not load the Qt platform plugin "xcb"` error that occurred in some Linux distributions due to missing `libxcb-cursor0` library by conditionally loading the bundled library when the system version is unavailable, issue mentioned by @bmcgonag in #101.
- Fixed the `No module named pip` error that occurred for users who installed Abogen via the [**uv**](https://github.com/astral-sh/uv) installer.
- Fixed defaults for `replace_single_newlines` not being applied correctly in some cases.
- Fixed `Save chapters separately for queued epubs is ignored`, issue mentioned by @dymas-cz in #109.
- Fixed incorrect sentence segmentation when using spaCy, where text would erroneously split after opening parentheses.
- Improvements in code and documentation.

# 1.2.4
- **Subtitle generation is now available for all languages!** Abogen now supports subtitle generation for non-English languages using audio duration-based timing. Available modes include `Line`, `Sentence`, and `Sentence + Comma`. (Note: Word-level subtitle modes remain English-only due to Kokoro's timestamp token limitations.)
- New option: **"Use spaCy for sentence segmentation"** You can now use [spaCy](https://spacy.io/) to automatically detect sentence boundaries and produce cleaner, more readable subtitles. Quick summary:
    - **What it does:** Splits text into natural sentences so subtitle entries read better and align more naturally with speech.
    - **Why this helps:** The previous punctuation-based splitting could break sentences incorrectly at common abbreviations (e.g. "Mr.", "Dr.", "Prof.") or initials, producing wrong subtitle breaks. spaCy avoids those false splits by using linguistic rules to detect real sentence boundaries.
    - **For Non-English:** spaCy runs **before** audio generation to create better sentence chunks for TTS.
    - **For English:** spaCy runs **during** subtitle generation to find accurate sentence breaks after TTS.
    - **Note:** spaCy segmentation is only applied when subtitle mode is `Sentence` or `Sentence + Comma`. When turned off, it falls back to simple punctuation-based splitting.
- New option: **Pre-download models and voices for offline use** You can now pre-download all required Kokoro models, voices, and spaCy language models using this option in the settings menu. Allowing you to use Abogen completely offline without any internet connection.
- Added support for `.` separator in timestamps (e.g. `HH:MM:SS.ms`) for timestamp-based text files.
- Optimized regex compilation and eliminated busy-wait loops.
- Possibly fixed `Silent truncation of long paragraphs` issue mentioned in [#91](https://github.com/denizsafak/abogen/issues/91) by [@xklzlxr](https://github.com/xklzlxr)
- Fixed unused regex patterns and variable naming conventions.
- Improvements in code and documentation.

# 1.2.3
- Same as 1.2.2, re-released to fix an issue with subtitle timing when using timestamp-based text files.

# 1.2.2
- **You can now voice your subtitle files!** Simply add `.srt`, `.ass` or `.vtt` files to generate timed audio. Alternatively, add a text file with timestamps in `HH:MM:SS` or `HH:MM:SS,ms` format to generate audio that matches the timestamps. See [here](https://github.com/denizsafak/abogen?tab=readme-ov-file#about-timestamp-based-text-files) for detailed instructions.
    - New option: **"Use silent gaps between subtitles"**: Prevents unnecessary audio speed-up by letting speech continue into the silent gaps between subtitles.
    - New option: **"Subtitle speed adjustment method"**: Choose how to speed up audio when needed:
        - **TTS Regeneration (better quality):** Re-generates the audio at a faster speed for more natural sound.
        - **FFmpeg Time-stretch (better speed):** Quickly speeds up the generated audio.
- Added support for embedding cover images in M4B files. Abogen now automatically extracts cover images from EPUB and PDF files. You can also manually specify a cover image using the `<<METADATA_COVER_PATH:path>>` tag in your text file. (To prevent MPV from showing the cover image, you can add `audio-display=no` to your MPV config file.)
- Fixed `[WinError 1114] A dynamic link library (DLL) initialization routine failed` error on Windows, pre-loading PyTorch DLLs before initializing PyQt6 to avoid DLL initialization errors, mentioned in #98 by @ephr0n.
- Potential fix for `CUDA GPU is not available` issue, by ensuring PyTorch is installed correctly with CUDA support on Windows using the installer script.
- Improvements in code and documentation.

# 1.2.1
- Upgraded Abogen's interface from PyQt5 to PyQt6 for better compatibility and long-term support.
- Added tooltip indicators in queue manager to display book handler options (`Save chapters separately` and `Merge chapters at the end`) for queued items.
- Added `Open processed file` and `Open input file` options for items in the queue manager, instead of just `Open file` option.
- Added loading gif animation to book handler window.
- Fixed light theme slider colors in voice mixer for better visibility (for non-Windows users).
- Fixed subtitle word-count splitting logic for more accurate segmentation.
- Improvements in code and documentation.

# 1.2.0
- Added `Line` option to subtitle generation modes, allowing subtitles to be generated based on line breaks in the text, by @mleg in #94.
- Added a loading indicator to the book handler window for better user experience during book preprocessing.
- Fixed `cannot access local variable 'is_narrow'` error when subtitle format `SRT` was selected, mentioned by @Kinasa0096 in #88.
- Fixed folder and filename sanitization to properly handle OS-specific illegal characters (Windows, Linux, macOS), ensuring compatibility across all platforms when creating chapter folders and files.
- Fixed `/` and `\` path display by normalizing paths.
- Fixed book reprocessing issue where books were being processed every time the chapters window was opened, improving performance when reopening the same book.
- Fixed taskbar icon not appearing correctly in Windows.
- Fixed "Go to folder" button not opening the chapter output directory when only separate chapters were generated.
- Improvements in code and documentation.

# 1.1.9
- Fixed the issue where spaces were deleted before punctuation marks while generating subtitles.
- Fixed markdown TOC generation breaks when "Replace single newlines" is enabled.
- Improvements in code and documentation.

# 1.1.8
- Added `.md` (Markdown) file extension support by @brianxiadong in PR #75
- Added new option `Configure silence between chapters` that lets you configure the silence between chapters, mentioned by @lfperez1982 in #79
- Better indicators and options while displaying and managing the input and processing files.
- Improved the markdown logic to better handle various markdown structures and cases.
- Fixed subtitle splitting before commas by combining punctuation with preceding words.
- Fixed save options not working correctly in queue mode, mentioned by @jborza in #78
- Fixed `No Qt platform plugin could be initialized` error, mentioned by @sunrainxyz in #59
- Fixed ordered list numbers not being included in EPUB content conversion. The numbers are now properly included in the converted content, mentioned by @jefro108 in #47
- Potentially fixed subtitle generation stucks at 9:59:59, mentioned by @bolaykim in #73
- Improvements in code and documentation.

# 1.1.7
- Added MPS GPU acceleration support for Silicon Mac, mentioned in https://github.com/denizsafak/abogen/issues/32#issuecomment-3155902040 by @jefro108. **Please read the [Mac](https://github.com/denizsafak/abogen?tab=readme-ov-file#mac) section in the documentation again, as it requires additional configuration.**
- Added word-by-word karaoke highlighting feature by @robmckinnon in PR #65
- Fixed sleep inhibition error occurring on some Linux systems that do not use systemd, mentioned in #67 by @hendrack
- Improvements in code and documentation.

# 1.1.6
- Improved EPUB chapter detection: Now reliably detects chapters from NAV HTML (TOC) files, even in non-standard EPUBs, fixes the issue mentioned by @jefro108 in #33
- Fixed SRT subtitle numbering issue, mentioned by @page-muncher in #41
- Fixed missing chapter contents issue in some EPUB files.
- Windows installer script now prompts the user to install the CUDA version of PyTorch even if no NVIDIA GPU is detected.
- Abogen now includes Mandarin Chinese (misaki[zh]) by default; manual installation is no longer required.

# 1.1.5
- Changed the temporary directory path to user's cache directory, which is more appropriate for storing cache files and avoids issues with unintended cleanup.
- Fixed the isssue where extra metadata information was not being saved to M4B files when they have no chapters, ensuring that all metadata is correctly written to the output file.
- Fixed sleep prevention process not ending if program exited using Ctrl+C or kill.
- Improved automatic filename suffixing to better prevent overwriting files with the same name, even if they have different extensions.
- Improvements in code and documentation.

# 1.1.4
- Fixed extra metadata information not being saved to M4B files, ensuring that all metadata is correctly written to the output file.
- Reformatted the code using Black for better readability and consistency.

# 1.1.3
- `M4B (with chapters)` generation is faster now, as it directly generates `m4b` files instead of converting from `wav`, which significantly reduces processing time, fixes the issue mentioned by @Milor123 in #39 
- Better sleep state handling for Linux.
- The app window now tries to fit the screen if its height would exceed the available display area.
- Fixed issue where the app would not restart properly on Windows.
- Fixed last sentence/subtitle entry timing in generated subtitles, the end time of the final subtitle entry now correctly matches the end of the audio chunk, preventing zero or invalid timings at the end.

# v1.1.2
- Now you can play the audio files while they are processing.
- Audio and subtitle files are now written directly to disk during generation, which significantly reduces memory usage.
- Added a better logic for detecting chapters from the epub, mentioned by @jefro108 in #33
- Added a new option: `Reset to default settings`, allowing users to reset all settings to their default values.
- Added a new option: `Disable Kokoro's internet access`. This lets you prevent Kokoro from downloading models or voices from HuggingFace Hub, which can help avoid long waiting times if your computer is offline.
- HuggingFace Hub telemetry is now disabled by default for improved privacy. (HuggingFace Hub is used by Kokoro to download its models)
- cPotential fix for #37 and #38, where the program was becoming slow while processing large files.
- Fixed `Open folder` and `Open file` buttons in the queue manager GUI.
- Improvements in code structure.

# v1.1.1
- Fixed adding wrong file in queue for EPUB and PDF files, ensuring the correct file is added to the queue.
- Reformatted the code using Black.

# v1.1.0
- Added queue system for processing multiple items, allowing users to add multiple files and process them in a queue, mentioned by @jborza in #30 (Special thanks to @jborza for implementing this feature in PR #35)
- Added a feature that allows selecting multiple items in book handler (in right click menu) by @jborza in #31, that fixes #28
- Added dark theme support, allowing users to switch between light and dark themes in the settings.
- Added auto-accept system to the chapter options dialog in conversion process, allowing the dialog to auto-accept after a certain time if no action is taken.
- Added new option: `Configure max lines in log window` that allows configuring the maximum number of lines to display in the log window.
- Improvements in documentation and code.

# v1.0.9
- Added chunking/segmenting system that fixes memory outage issues when processing large audio files.
- Added new option: `Subtitle format`, allowing users to choose between `srt` , `ass (wide)`, `ass (narrow)`, and `ass (centered wide)` and `ass (centered narrow)`
- Improved chapter filename generation with smart word-boundary truncation at 80 characters, preventing mid-word cuts in filenames.
- `Composer` and `Genre` metadata fields for M4B files are now editable from the text editor.
- Improvements in documentation and code.

# v1.0.8
- Added support for AMD GPUs in Linux (Special thanks to @hg000125 for his contribution in #23)
- Added voice preview caching system that stores generated previews in the cache folder, mentioned by @jborza in #22
- Added extra metadata support for chaptered M4B files, ensuring better compatibility with audiobook players.
- Added new option: `Separate chapters audio format`, allowing to choose between `wav`, `mp4`, `flac` and `opus` formats for chaptered audio files.
- Added a download tracker that displays informative messages while downloading Kokoro models or voices from HuggingFace.
- Skipping PyTorch CUDA installation if GPU is not NVIDIA in WINDOWS_INSTALL.bat script, preventing unnecessary installation of PyTorch.
- Removed `abogen_` prefix that was adding to converted books in temp directory.
- Fixed voice preview player keeps playing silently at the background after preview ends.
- Fixed not writing separate chapters audio when output is OPUS.
- Improved input box background color handling, fixed display issues in Linux.
- Updated profile and voice mixer icons, better visibility and aesthetics in voice mixer.
- Better sleep state handling for Linux.
- Improvements in documentation and code.

# v1.0.7
- Improve chaptered audio generation by outputting directly as `m4b` instead of converting from `wav`.
- Ignore chapter markers and single newlines when calculating text length, improving the accuracy of the text length calculation.
- Prevent cancellation if process is at 99%, ensuring the process is not interrupted at the last moment.
- Improved process handling for subpprocess calls, ensuring better management of subprocesses.
- Improved PDF handling, ignoring empty pages/chapters and better chapter handling.
- Added `Save in a project folder with metadata` option in the book handler, allowing users to save the converted items in a project folder with available metadata files. Useful if you want to work with the converted files in the future, issue mentioned by @Darthagnon in #15
- Added `Go to folder` button in input box, allowing users to open the folder containing the converted file.
- Added `.opus` as output format for generated audio files, which is a more efficient format for audio files.
- Added `Create desktop shortcut and install` option to Linux version, allowing users to create a shortcut and install 
- Added "Playing..." indicator for "Preview" button in the voice mixer.

# v1.0.6
- Added `Insert chapter marker` button in text editor to insert chapter markers at the current cursor position.
- Added `Preview` button in voice mixer to preview the voice mix with the selected settings.
- Fixed `f-string: unmatched '['` error in Voice preview, mentioned in #14
- Fixed the issue with the content before first chapter not being included in the output.
- Fixed m4b chapter generation opens CMD window in Windows.

# v1.0.5
- Added new output format: `m4b`, enabling chapter metadata in audiobooks. Special thanks to @jborza for implementing this feature in PR #10.
- Better approach for determining the correct configuration folder for Linux and MacOS, using platformdirs. (Fixes Docker issue #12)
- Improvements in documentation and code.

# v1.0.4
- Merge pull request [#7](https://github.com/denizsafak/abogen/pull/7) by @jborza that improves voice preview and documentation.
- Fixed the issue when a voice is selected, the voice mixer tries to pre-select that voice and ignores existing profiles.
- Fixed the error while renaming the default "New profile" in the voice mixer.
- Fixed subtitle_combo enabling/disabling when a voice in the voice mixer is selected.
- Prevented using special characters in the profile name to avoid conflicts.
- Improved invalid profile handling in the voice mixer.

# v1.0.3
- Added voice mixing, allowing multiple voices to be combined into a single "Mixed Voice", a feature mentioned by @PulsarFTW in #1. Special thanks to @jborza for making this possible through his contributions in #5.
- Added profile system to voice mixer, allowing users to create and manage multiple voice profiles.
- Improvements in the voice mixer, mostly for organizing controls and enhancing user experience.
- Added icons for flags and genders in the GUI, making it easier to identify different options.
- Improved the content and chapter extraction process for EPUB files, ensuring better handling of various structures.
- Switched to platformdirs for determining the correct desktop path, instead of using old methods.
- Fixed preview voices was not using GPU acceleration, which was causing performance issues.
- Improvements in code and documentation.

# v1.0.2
- Enhanced EPUB handling by treating all items in chapter list (including anchors) as chapters, improving navigation and organization for poorly structured books, mentioned by @Darthagnon in #4
- Fixed the issue with some chapters in EPUB files had missing content.
- Fixed the issue with some EPUB files only having one chapter caused the program to ignore the entire book.
- Fixed "utf-8' codec can't decode byte" error, mentioned by @nigelp in #3
- Added "Replace single newlines with spaces" option in the menu. This can be useful for texts that have imaginary line breaks.
- Improvements in code and documentation.

# v1.0.1
- Added abogen-cli command for better troubleshooting and error handling.
- Switched from setuptools to hatchling for packaging.
- Added classifiers to the package metadata.
- Fixed "No module named 'docopt'" and "setuptools.build_meta" import errors while using .bat installer in Windows, mentioned by @nigelp in #2
- Improvements in code and documentation.
