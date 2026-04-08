# Installing project requirements

This repository includes a `requirements.txt` file at the project root. Use the provided PowerShell script to install the Python dependencies on Windows.

Quick steps (PowerShell):

- Run the script from the repository root:

  `.\\install_requirements.ps1`

- If `ExecutionPolicy` prevents running the script, run:

  `powershell -ExecutionPolicy Bypass -File .\\install_requirements.ps1`

- If `python` is not on your PATH, run the script by calling your Python executable directly, for example:

  `& 'C:\\Users\\ariel\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' -m pip install -r requirements.txt`

Troubleshooting:

- If you see `No module named 'docx'` after running your script, ensure `requirements.txt` contains `python-docx` (the package that provides `docx`).
- You can also manually install a single package:

  `python -m pip install python-docx`

If you want, I can also add a small `.bat` wrapper for CMD or update the `README.md` with these instructions. ¿Lo quieres? 
