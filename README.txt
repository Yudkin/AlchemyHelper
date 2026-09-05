ALCHEMY HELPER

Version: 0.0.1

Files:
- alchemy_helper.py   main program
- alchemy.json        720 elements + recipes
- translations.json   Russian names
- alchemy_helper.spec PyInstaller build file
- VERSION             current project version

Run from Python:
  python alchemy_helper.py

Build EXE on Windows:
  py -m pip install pyinstaller
  pyinstaller --clean --noconfirm alchemy_helper.spec

The EXE will be in dist\AlchemyHelper.exe.

The program creates progress.json automatically in its folder. It stores the Atlas progress between launches. progress.json should not be committed to Git.
