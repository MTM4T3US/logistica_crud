"""Abre o JARVIS OS como programa (sem console). Usado pelos atalhos e por "iniciar com o Windows"."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

from app.desktop_app import main  # noqa: E402

sys.exit(main())
