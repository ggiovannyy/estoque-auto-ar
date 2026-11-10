"""Onde ficam os dados do sistema (banco, chave da sessão, certificado). MAXX_DATA troca a pasta (ex.: testes)."""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MAXX_DATA", os.path.join(BASE, "data"))
DB_PATH = os.path.join(DATA, "estoque.db")
