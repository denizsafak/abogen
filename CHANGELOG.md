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
- Added voice mixing, allowing multiple voices to be combined into a single “Mixed Voice”, a feature mentioned by @PulsarFTW in #1. Special thanks to @jborza for making this possible through his contributions in #5.
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
